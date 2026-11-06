import json
import math
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import get_logger
from backend.models import (
    ConditionType,
    Draft,
    DraftStatus,
    EbaySoldStats,
    PriceAnalysis,
    VerificationLinks,
)

logger = get_logger("occaision.ai")


def safe_price(val: Any, default: float = 0.0) -> float:
    try:
        n = float(val)
        if math.isnan(n) or math.isinf(n) or n < 0:
            return default
        return round(n, 2)
    except (ValueError, TypeError):
        return default

SWISS_LEGAL_DISCLAIMER = "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
GERMAN_LEGAL_DISCLAIMER = (
    "Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. "
    "Keine Garantie oder Rücknahme, da Privatverkauf."
)


class AIAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    identified_product: Optional[str] = None
    missing_photo_hints: List[str] = Field(default_factory=list)
    reasoning: Optional[str] = ""

    # Ricardo
    ricardo_title: Optional[str] = None
    ricardo_description: Optional[str] = None
    ricardo_condition: Optional[str] = None
    ricardo_start_chf: Optional[float] = None
    ricardo_buynow_chf: Optional[float] = None

    # Tutti
    tutti_title: Optional[str] = None
    tutti_description: Optional[str] = None
    tutti_category: Optional[str] = None
    tutti_condition: Optional[str] = None
    tutti_vhb_chf: Optional[float] = None

    # eBay DE
    ebay_de_title: Optional[str] = None
    ebay_de_description: Optional[str] = None
    ebay_de_category: Optional[str] = None
    ebay_de_condition: Optional[str] = None
    ebay_de_start_eur: Optional[float] = None
    ebay_de_buynow_eur: Optional[float] = None
    ebay_start_eur: Optional[float] = None
    ebay_buynow_eur: Optional[float] = None

    # Kleinanzeigen
    kleinanzeigen_title: Optional[str] = None
    kleinanzeigen_description: Optional[str] = None
    kleinanzeigen_category: Optional[str] = None
    kleinanzeigen_condition: Optional[str] = None
    kleinanzeigen_vb_eur: Optional[float] = None

    # New prices
    ch_new_price_chf: Optional[float] = None
    de_new_price_eur: Optional[float] = None

    @field_validator(
        "ricardo_start_chf",
        "ricardo_buynow_chf",
        "tutti_vhb_chf",
        "ebay_de_start_eur",
        "ebay_de_buynow_eur",
        "ebay_start_eur",
        "ebay_buynow_eur",
        "kleinanzeigen_vb_eur",
        "ch_new_price_chf",
        "de_new_price_eur",
        mode="before",
    )
    @classmethod
    def sanitize_price_field(cls, v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            n = float(v)
            if math.isnan(n) or math.isinf(n) or n < 0:
                return None
            return round(n, 2)
        except (ValueError, TypeError):
            return None


def is_draft_ready(draft: Draft) -> bool:
    """Validate completeness before setting status to READY."""
    if not (draft.identified_product and draft.identified_product.strip()):
        return False
    has_title = any(
        bool(listing.title and listing.title.strip())
        for listing in [draft.ricardo, draft.tutti, draft.ebay_de, draft.kleinanzeigen]
    )
    has_desc = any(
        bool(listing.description and listing.description.strip())
        for listing in [draft.ricardo, draft.tutti, draft.ebay_de, draft.kleinanzeigen]
    )
    return has_title and has_desc


def extract_and_parse_json(raw_text: str) -> Dict[str, Any]:
    text = raw_text.strip()
    # Check for Markdown code block ```json ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1).strip()
    else:
        # Look for outermost { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]

    # Clean up trailing commas before closing braces/brackets
    text = re.sub(r",\s*([\]}])", r"\1", text)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"AI response must be a JSON object, got {type(parsed).__name__}")
    return parsed


def _truncate_title(title: str, max_len: int) -> str:
    if len(title) > max_len:
        truncated = title[:max_len]
        last_space = truncated.rfind(" ")
        if last_space > int(max_len * 0.6):
            truncated = truncated[:last_space]
        return truncated.strip()
    return title.strip()


def post_process_ai_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    res = dict(payload)

    # 1. Swiss German orthography: replace 'ß' with 'ss' in CH- and general fields only
    # Do NOT apply to ebay_de_* or kleinanzeigen_* (standard German retains 'ß')
    for k, v in res.items():
        if not (k.startswith("ebay_de_") or k.startswith("kleinanzeigen_")):
            if isinstance(v, str):
                res[k] = v.replace("ß", "ss")
            elif isinstance(v, list):
                res[k] = [item.replace("ß", "ss") if isinstance(item, str) else item for item in v]

    # 2. Hard limits on titles
    if "ricardo_title" in res and isinstance(res["ricardo_title"], str):
        res["ricardo_title"] = _truncate_title(res["ricardo_title"], 60)

    if "tutti_title" in res and isinstance(res["tutti_title"], str):
        res["tutti_title"] = _truncate_title(res["tutti_title"], 60)

    if "ebay_de_title" in res and isinstance(res["ebay_de_title"], str):
        res["ebay_de_title"] = _truncate_title(res["ebay_de_title"], 80)

    if "kleinanzeigen_title" in res and isinstance(res["kleinanzeigen_title"], str):
        res["kleinanzeigen_title"] = _truncate_title(res["kleinanzeigen_title"], 65)

    # 3. Mandatory Swiss warranty disclaimer in descriptions
    ricardo_desc = res.get("ricardo_description") or ""
    if "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme" not in ricardo_desc:
        res["ricardo_description"] = f"{ricardo_desc.rstrip()}\n\n{SWISS_LEGAL_DISCLAIMER}".strip()

    tutti_desc = res.get("tutti_description") or ""
    disclaimer = SWISS_LEGAL_DISCLAIMER
    disclaimer_block = f"\n\n{disclaimer}"
    if "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme" not in tutti_desc:
        max_body_len = 4000 - len(disclaimer_block)
        if len(tutti_desc) > max_body_len:
            tutti_desc = tutti_desc[:max_body_len].rstrip()
        res["tutti_description"] = f"{tutti_desc.rstrip()}{disclaimer_block}".strip()
    else:
        if len(tutti_desc) > 4000:
            idx = tutti_desc.rfind(disclaimer)
            body = tutti_desc[:idx].rstrip()
            tail = tutti_desc[idx:]
            avail = 4000 - len(tail)
            if avail > 0:
                tutti_desc = f"{body[:avail].rstrip()}\n\n{tail}".strip()
            else:
                tutti_desc = tutti_desc[:4000].rstrip()
        res["tutti_description"] = tutti_desc

    # 4. Mandatory German warranty disclaimer in descriptions
    if "ebay_de_description" in res:
        ebay_desc = res.get("ebay_de_description") or ""
        if "Ausschluss jeglicher Sachmängelhaftung" not in ebay_desc:
            res["ebay_de_description"] = f"{ebay_desc.rstrip()}\n\n{GERMAN_LEGAL_DISCLAIMER}".strip()
    elif "ebay_de_title" in res and res.get("ebay_de_title"):
        res["ebay_de_description"] = GERMAN_LEGAL_DISCLAIMER

    if "kleinanzeigen_description" in res:
        klein_desc = res.get("kleinanzeigen_description") or ""
        if "Ausschluss jeglicher Sachmängelhaftung" not in klein_desc:
            res["kleinanzeigen_description"] = f"{klein_desc.rstrip()}\n\n{GERMAN_LEGAL_DISCLAIMER}".strip()
    elif "kleinanzeigen_title" in res and res.get("kleinanzeigen_title"):
        res["kleinanzeigen_description"] = GERMAN_LEGAL_DISCLAIMER

    return res


SYSTEM_INSTRUCTION = """
Du bist ein professioneller Verkaufs- und Preisfindungs-Assistent für Schweizer (Ricardo.ch, Tutti.ch) und deutsche Plattformen (eBay.de, Kleinanzeigen.de).
Deine Aufgabe:
1. Identifiziere den exakten Artikel (Marke, Modell, Spezifikationen) aus den Fotos und Benutzernotizen.
2. Führe einen visuellen Qualitätscheck durch: Falls für Käufer essenzielle Fotos fehlen (z.B. Typenschild/Modellnummer, Nahaufnahme sichtbarer Mängel, erwähntes Zubehör), gib diese als 'missing_photo_hints' auf Deutsch aus.
3. Marktrecherche & Preisfindung:
   - Nutze die Suchergebnisse für den aktuellen Schweizer Neupreis (Digitec/Galaxus/Toppreise.ch) und deutschen Neupreis (Idealo/Geizhals) sowie die übergebenen eBay-DE Sold Statistiken.
   - Beachte: In der Schweiz ist Elektronik neu wegen 8.1% MwSt. oft günstiger als in DE. Gib realistische Neupreise 'ch_new_price_chf' und 'de_new_price_eur' an.
   - CH-Preise:
     * Empfehle einen attraktiven Ricardo Startpreis 'ricardo_start_chf' (ca. 65-75% des realistischen Gebrauchtmarktwerts).
     * Empfehle einen realistischen Sofortkaufen-Preis 'ricardo_buynow_chf' (beachte ca. 10-12% Ricardo-Provision; nie über 80% des Schweizer Neupreises bei Gebrauchtware).
     * Empfehle eine Tutti Verhandlungsbasis 'tutti_vhb_chf' (mit ca. 5-10% Verhandlungsspielraum).
   - DE-Preise (in EUR):
     * Empfehle einen Startpreis für eBay.de Auktionen 'ebay_start_eur'.
     * Empfehle einen Sofort-Kaufen-Preis für eBay.de 'ebay_buynow_eur'.
     * Empfehle eine Kleinanzeigen Verhandlungsbasis 'kleinanzeigen_vb_eur'.
4. Erstelle suchbegriffsoptimierte Inserate für alle 4 Plattformen:
   - Ricardo: Titel STRIKT maximal 60 Zeichen (Marke Modell Kern-Specs Zustand). Strukturierte Beschreibung (Zustand, Lieferumfang, Technische Daten, Versand/Abholung). Schweizer Hochdeutsch (IMMER 'ss', NIEMALS 'ß'!). Pflichtklausel: "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
   - Tutti: Titel STRIKT maximal 60 Zeichen. Beschreibung maximal 4000 Zeichen. Passende Tutti-Kategorie. Freundlicher Kleinanzeigentext inkl. Abholung/Versand und TWINT. Schweizer Hochdeutsch (IMMER 'ss', NIEMALS 'ß'!). Pflichtklausel: "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
   - eBay.de: Titel STRIKT maximal 80 Zeichen (suchbegriffsoptimiert). Passende eBay-Kategorie. Strukturierter Text in Standard-Deutsch (inkl. 'ß'). Pflichtklausel: "Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."
   - Kleinanzeigen.de: Titel STRIKT maximal 65 Zeichen. Passende Kleinanzeigen-Kategorie. Freundlicher Text in Standard-Deutsch (inkl. 'ß') mit Hinweis auf Abholung/DHL/Direkt kaufen. Pflichtklausel: "Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt mit folgender Struktur:
{
  "identified_product": "string",
  "missing_photo_hints": ["string"],
  "ch_new_price_chf": float,
  "de_new_price_eur": float,
  "ricardo_start_chf": float,
  "ricardo_buynow_chf": float,
  "tutti_vhb_chf": float,
  "ebay_start_eur": float,
  "ebay_buynow_eur": float,
  "kleinanzeigen_vb_eur": float,
  "reasoning": "string",
  "ricardo_title": "string (max 60 Zeichen)",
  "ricardo_description": "string",
  "ricardo_condition": "neu" | "wie_neu" | "gebraucht" | "defekt",
  "tutti_title": "string (max 60 Zeichen)",
  "tutti_category": "string",
  "tutti_description": "string (max 4000 Zeichen)",
  "tutti_condition": "neu" | "wie_neu" | "gebraucht" | "defekt",
  "ebay_de_title": "string (max 80 Zeichen, Standard-Deutsch)",
  "ebay_de_category": "string",
  "ebay_de_description": "string",
  "ebay_de_condition": "neu" | "wie_neu" | "gebraucht" | "defekt",
  "kleinanzeigen_title": "string (max 65 Zeichen, Standard-Deutsch)",
  "kleinanzeigen_category": "string",
  "kleinanzeigen_description": "string",
  "kleinanzeigen_condition": "neu" | "wie_neu" | "gebraucht" | "defekt"
}
"""


def build_verification_links(query: str) -> VerificationLinks:
    trimmed = (query or "").strip()
    q = urllib.parse.quote_plus(trimmed)
    q_raw = urllib.parse.quote(trimmed)
    return VerificationLinks(
        ebay_sold_url=f"https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000",
        kleinanzeigen_search_url=f"https://www.kleinanzeigen.de/anbieter:privat/s-{q}/k0+global.zustand:alright%2Clike_new%2Cok",
        idealo_url=f"https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}",
        ricardo_search_url=f"https://www.ricardo.ch/de/s/{q_raw}/?item_condition=used&seller_type=individual",
        toppreise_url=f"https://www.toppreise.ch/produktsuche?q={q}",
        digitec_url=f"https://www.galaxus.ch/de/search?q={q}",
        tutti_search_url="https://www.tutti.ch/de",
    )


FALLBACK_MODELS: List[Dict[str, str]] = [
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash (Empfohlen)"},
    {"id": "gemini-3.7-flash", "label": "Gemini 3.7 Flash"},
    {"id": "gemini-3.6-flash", "label": "Gemini 3.6 Flash"},
    {"id": "gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
    {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash Lite"},
    {"id": "gemini-flash-latest", "label": "Gemini Flash Latest"},
    {"id": "gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
    {"id": "gemini-pro-latest", "label": "Gemini Pro Latest"},
    {"id": "gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
]


class AIService:
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3.8-flash",
        enable_search_grounding: bool = True,
        eur_to_chf: float = 0.94,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.enable_search_grounding = enable_search_grounding
        self.eur_to_chf = eur_to_chf
        self._client: Optional[genai.Client] = None
        self._models_cache: Optional[List[Dict[str, str]]] = None
        self._models_cache_time: float = 0.0
        self._models_cache_ttl: float = 3600.0

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def set_api_key(self, api_key: str, model_name: Optional[str] = None):
        """Update API key and optionally model name, resetting the client and cache."""
        self.api_key = api_key
        if model_name:
            self.model_name = model_name
        self._client = genai.Client(api_key=self.api_key)
        self._models_cache = None
        self._models_cache_time = 0.0

    def get_available_models(self) -> List[Dict[str, str]]:
        """Query Gemini API for available models or fallback to recommended list.
        Includes TTL caching and offline/test guards.
        """
        now = time.time()
        if self._models_cache and (now - self._models_cache_time < self._models_cache_ttl):
            return list(self._models_cache)

        is_offline = (
            os.environ.get("OCCAISION_OFFLINE") == "1"
            or "PYTEST_CURRENT_TEST" in os.environ
            or "pytest" in sys.modules
        )
        is_dummy_key = (
            not self.api_key
            or self.api_key in (
                "your_google_ai_studio_api_key_here",
                "test_key",
                "dummy",
                "test",
                "offline",
            )
        )

        if is_offline or is_dummy_key:
            return list(FALLBACK_MODELS)

        try:
            results = []
            for m in self.client.models.list():
                actions = (
                    getattr(m, "supported_actions", None)
                    or getattr(m, "supported_generation_methods", [])
                    or []
                )
                if "generateContent" not in actions:
                    continue
                name = m.name or ""
                if name.startswith("models/"):
                    name = name[7:]
                lower = name.lower()
                if any(
                    skip in lower
                    for skip in [
                        "tts", "live", "transcribe", "robotics", "embedding",
                        "lyria", "computer-use", "aqa", "banana", "nano",
                        "preview", "gemma", "argon", "omni", "deep-research",
                        "antigravity", "customtools", "gemini-2.5-flash",
                        "gemini-2.0-flash", "gemini-1.5", "image"
                    ]
                ):
                    continue
                disp = getattr(m, "display_name", "") or name
                label = f"{disp} (Empfohlen)" if "3.8-flash" in name else disp
                results.append({"id": name, "label": label})

            def sort_key(item):
                nid = item["id"]
                priority = 99
                if "3.8-flash" in nid:
                    priority = 1
                elif "3.7-flash" in nid:
                    priority = 2
                elif "3.6-flash" in nid:
                    priority = 3
                elif "3.5-flash" in nid:
                    priority = 4
                elif "flash-latest" in nid:
                    priority = 5
                elif "3.1-flash-lite" in nid:
                    priority = 6
                elif "3.5-flash-lite" in nid:
                    priority = 7
                elif "flash-lite-latest" in nid:
                    priority = 8
                elif "pro-latest" in nid:
                    priority = 9
                elif "2.5-pro" in nid:
                    priority = 10
                return (priority, nid)

            results.sort(key=sort_key)
            if results:
                self._models_cache = results
                self._models_cache_time = now
                return list(results)
        except Exception as e:
            if not is_offline:
                logger.warning(f"Konnte Modelle nicht von Gemini abrufen: {e}")

        # Fallback list of current production models
        return list(FALLBACK_MODELS)

    def get_generate_config(self, force_disable_grounding: bool = False) -> types.GenerateContentConfig:
        if self.enable_search_grounding and not force_disable_grounding:
            # Note: Do NOT set response_mime_type="application/json" when using google_search tool
            return types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                tools=[types.Tool(google_search=types.GoogleSearch())],
            )
        else:
            return types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.2,
                response_mime_type="application/json",
            )

    async def _call_gemini(self, contents: list, config: types.GenerateContentConfig) -> str:
        # Wrap async execution
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )
        return response.text or ""

    async def analyze_draft(
        self,
        draft: Draft,
        image_paths: List[Path],
        ebay_stats: Optional[EbaySoldStats] = None,
        enabled_sources: Optional[List[str]] = None,
    ) -> Draft:
        user_prompt_parts = []
        if draft.identified_product:
            user_prompt_parts.append(
                f"Produktname / Modell (vom Benutzer angegeben): {draft.identified_product}\n"
            )
        user_prompt_parts.append(
            f"Benutzernotizen / Kurzbeschreibung zum Artikel: {draft.user_notes or 'Keine Notizen'}\n"
        )

        existing_pa = draft.price_analysis
        market_sources = (
            dict(existing_pa.market_sources)
            if existing_pa and existing_pa.market_sources
            else {}
        )
        if enabled_sources is not None:
            market_sources = {
                k: v for k, v in market_sources.items()
                if k in enabled_sources
            }
            if "ebay_de_sold" not in enabled_sources:
                ebay_stats = None
        has_usable_samples = any(
            getattr(ms, "sample_count", 0) > 0 and getattr(ms, "median_price", None) is not None
            for ms in market_sources.values()
        )
        has_extension_prices = bool(has_usable_samples)

        if has_extension_prices and market_sources:
            logger.info(
                f"[AIService] Nutze {len(market_sources)} über die Firefox-Extension ermittelte Preisquellen "
                "(Google Search Grounding wird für diesen Aufruf deaktiviert)."
            )
            source_lines = [
                "Über die Firefox-Extension live ermittelte Marktpreise (bitte direkt für die Preisfindung nutzen):"
            ]
            for src_id, ms in market_sources.items():
                if ms.sample_count > 0 and ms.median_price is not None:
                    chf_info = (
                        f" (~{ms.median_chf} CHF)"
                        if ms.currency != "CHF" and ms.median_chf is not None
                        else ""
                    )
                    source_lines.append(
                        f"- {ms.label} ({src_id}): Stichprobe={ms.sample_count}, "
                        f"Median={ms.median_price} {ms.currency}{chf_info}, "
                        f"Spanne={ms.min_price} - {ms.max_price} {ms.currency}"
                    )
                else:
                    source_lines.append(f"- {ms.label} ({src_id}): Keine Treffer (0)")
            user_prompt_parts.append("\n".join(source_lines) + "\n")

            # Sync ebay_stats from extension ebay_de_sold if not explicitly provided
            if ebay_stats is None and "ebay_de_sold" in market_sources:
                eb_ms = market_sources["ebay_de_sold"]
                ebay_stats = EbaySoldStats(
                    query=draft.identified_product or draft.user_notes or "",
                    sample_count=eb_ms.sample_count,
                    min_eur=eb_ms.min_price,
                    max_eur=eb_ms.max_price,
                    median_eur=eb_ms.median_price,
                    median_chf=eb_ms.median_chf,
                    exchange_rate=self.eur_to_chf,
                )
        elif ebay_stats and ebay_stats.sample_count > 0:
            logger.debug(
                f"[AIService] Übernehme eBay-Statistik in den Prompt: "
                f"{ebay_stats.sample_count} Treffer, Median {ebay_stats.median_eur} EUR ({ebay_stats.median_chf} CHF)"
            )
            user_prompt_parts.append(
                f"eBay DE verkaufte Artikel (Transaktionspreise): "
                f"Stichprobe={ebay_stats.sample_count}, "
                f"Median EUR={ebay_stats.median_eur} €, "
                f"Median CHF={ebay_stats.median_chf} CHF (Wechselkurs {ebay_stats.exchange_rate}), "
                f"Spanne EUR={ebay_stats.min_eur} € - {ebay_stats.max_eur} €.\n"
            )
        else:
            logger.debug(
                f"[AIService] Keine eBay-Statistik im Prompt enthalten "
                f"(ebay_stats={ebay_stats.model_dump() if ebay_stats else None})."
            )

        user_prompt_parts.append(
            "Bitte analysiere die bereitgestellten Fotos und Informationen und liefere das JSON-Objekt."
        )

        user_prompt_text = "\n".join(user_prompt_parts)
        contents: list = [user_prompt_text]

        valid_images = []
        # Attach image files
        for p in image_paths:
            if p.exists():
                try:
                    img_bytes = p.read_bytes()
                    part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                    contents.append(part)
                    valid_images.append(f"{p.name} ({len(img_bytes) / 1024:.1f} KB)")
                except Exception as e:
                    logger.warning(f"Failed to read image {p}: {e}")

        effective_grounding = self.enable_search_grounding and not has_extension_prices
        config = self.get_generate_config(force_disable_grounding=has_extension_prices)

        logger.info(
            f"[AIService] Sende Anfrage an Gemini (Modell: {self.model_name}, Bilder: {len(valid_images)}, "
            f"Search Grounding: {effective_grounding}, Extension-Preise: {has_extension_prices})..."
        )

        logger.debug("=" * 70)
        logger.debug("--- [GEMINI AI PROMPT DEBUG START] ---")
        logger.debug(f"Modell: {self.model_name}")
        logger.debug(f"Search Grounding aktiv: {effective_grounding} (Extension-Preise: {has_extension_prices})")
        logger.debug(f"Bilder ({len(valid_images)}): {', '.join(valid_images) if valid_images else 'keine'}")
        logger.debug(f"\n[SYSTEM INSTRUCTION]:\n{SYSTEM_INSTRUCTION.strip()}")
        logger.debug(f"\n[USER PROMPT]:\n{user_prompt_text.strip()}")
        logger.debug("--- [GEMINI AI PROMPT DEBUG END] ---")
        logger.debug("=" * 70)

        raw_text = await self._call_gemini(contents=contents, config=config)

        logger.info(f"[AIService] Antwort von Gemini erhalten ({len(raw_text)} Zeichen).")
        logger.debug("=" * 70)
        logger.debug("--- [GEMINI AI RAW RESPONSE DEBUG START] ---")
        logger.debug(raw_text.strip())
        logger.debug("--- [GEMINI AI RAW RESPONSE DEBUG END] ---")
        logger.debug("=" * 70)
        raw_payload = extract_and_parse_json(raw_text)
        validated = AIAnalysisResponse.model_validate(raw_payload)
        payload = post_process_ai_output(validated.model_dump())

        # Update draft
        product_name = (
            payload.get("identified_product")
            or draft.identified_product
            or draft.user_notes
            or "Artikel"
        )
        draft.identified_product = product_name
        draft.missing_photo_hints = payload.get("missing_photo_hints", [])

        # Build verification links
        v_links = build_verification_links(product_name)

        ch_new_fallback = existing_pa.ch_new_price_chf if existing_pa else None
        if ch_new_fallback is None and market_sources:
            for k in ("toppreise", "digitec"):
                if k in market_sources and market_sources[k].median_price:
                    ch_new_fallback = market_sources[k].median_price
                    break

        de_new_fallback = existing_pa.de_new_price_eur if existing_pa else None
        if de_new_fallback is None and "idealo" in market_sources and market_sources["idealo"].median_price:
            de_new_fallback = market_sources["idealo"].median_price

        draft.price_analysis = PriceAnalysis(
            ebay_stats=ebay_stats or (existing_pa.ebay_stats if existing_pa and (enabled_sources is None or "ebay_de_sold" in enabled_sources) else None),
            market_sources=market_sources,
            prices_fetched_via_extension=has_extension_prices,
            ch_new_price_chf=payload.get("ch_new_price_chf") or ch_new_fallback,
            de_new_price_eur=payload.get("de_new_price_eur") or de_new_fallback,
            ricardo_start_chf=safe_price(payload.get("ricardo_start_chf"), 1.0),
            ricardo_buynow_chf=safe_price(payload.get("ricardo_buynow_chf"), 10.0),
            tutti_vhb_chf=safe_price(payload.get("tutti_vhb_chf"), 10.0),
            ebay_start_eur=safe_price(payload.get("ebay_start_eur"), 1.0),
            ebay_buynow_eur=safe_price(payload.get("ebay_buynow_eur"), 10.0),
            kleinanzeigen_vb_eur=safe_price(payload.get("kleinanzeigen_vb_eur"), 10.0),
            reasoning=payload.get("reasoning", ""),
            verification_links=v_links,
        )

        # Map condition safely
        def map_cond(val: Optional[str]) -> ConditionType:
            try:
                return ConditionType(str(val).lower())
            except (ValueError, TypeError):
                return ConditionType.GEBRAUCHT

        if payload.get("ricardo_title"):
            draft.ricardo.title = payload["ricardo_title"]
        if payload.get("ricardo_description"):
            draft.ricardo.description = payload["ricardo_description"]
        if payload.get("ricardo_condition"):
            draft.ricardo.condition = map_cond(payload.get("ricardo_condition"))
        if payload.get("ricardo_start_chf") is not None:
            draft.ricardo.start_price_chf = safe_price(payload.get("ricardo_start_chf"), draft.ricardo.start_price_chf)
        if payload.get("ricardo_buynow_chf") is not None:
            draft.ricardo.buynow_price_chf = safe_price(payload.get("ricardo_buynow_chf"), draft.ricardo.buynow_price_chf)

        if payload.get("tutti_title"):
            draft.tutti.title = payload["tutti_title"]
        if payload.get("tutti_category"):
            draft.tutti.category_suggestion = payload["tutti_category"]
        if payload.get("tutti_description"):
            draft.tutti.description = payload["tutti_description"]
        if payload.get("tutti_condition"):
            draft.tutti.condition = map_cond(payload.get("tutti_condition"))
        if payload.get("tutti_vhb_chf") is not None:
            draft.tutti.price_vhb_chf = safe_price(payload.get("tutti_vhb_chf"), draft.tutti.price_vhb_chf)

        if payload.get("ebay_de_title"):
            draft.ebay_de.title = payload["ebay_de_title"]
        if payload.get("ebay_de_category"):
            draft.ebay_de.category_suggestion = payload["ebay_de_category"]
        if payload.get("ebay_de_description"):
            draft.ebay_de.description = payload["ebay_de_description"]
        if payload.get("ebay_de_condition"):
            draft.ebay_de.condition = map_cond(payload.get("ebay_de_condition"))
        if payload.get("ebay_start_eur") is not None:
            draft.ebay_de.start_price_eur = safe_price(payload.get("ebay_start_eur"), draft.ebay_de.start_price_eur)
        elif payload.get("ebay_de_start_eur") is not None:
            draft.ebay_de.start_price_eur = safe_price(payload.get("ebay_de_start_eur"), draft.ebay_de.start_price_eur)
        if payload.get("ebay_buynow_eur") is not None:
            draft.ebay_de.buynow_price_eur = safe_price(payload.get("ebay_buynow_eur"), draft.ebay_de.buynow_price_eur)
        elif payload.get("ebay_de_buynow_eur") is not None:
            draft.ebay_de.buynow_price_eur = safe_price(payload.get("ebay_de_buynow_eur"), draft.ebay_de.buynow_price_eur)

        if payload.get("kleinanzeigen_title"):
            draft.kleinanzeigen.title = payload["kleinanzeigen_title"]
        if payload.get("kleinanzeigen_category"):
            draft.kleinanzeigen.category_suggestion = payload["kleinanzeigen_category"]
        if payload.get("kleinanzeigen_description"):
            draft.kleinanzeigen.description = payload["kleinanzeigen_description"]
        if payload.get("kleinanzeigen_condition"):
            draft.kleinanzeigen.condition = map_cond(payload.get("kleinanzeigen_condition"))
        if payload.get("kleinanzeigen_vb_eur") is not None:
            draft.kleinanzeigen.price_eur = safe_price(payload.get("kleinanzeigen_vb_eur"), draft.kleinanzeigen.price_eur)

        draft.status = DraftStatus.READY if is_draft_ready(draft) else DraftStatus.DRAFT
        return draft
