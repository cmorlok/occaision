import io
import json
import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from PIL import Image
from google import genai
from google.genai import types

from backend.models import (
    ConditionType,
    Draft,
    DraftStatus,
    EbaySoldStats,
    PriceAnalysis,
    RicardoListing,
    TuttiListing,
)
from backend.services.ebay_service import EbayService

logger = logging.getLogger(__name__)

SWISS_LEGAL_DISCLAIMER = "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
GERMAN_LEGAL_DISCLAIMER = (
    "Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. "
    "Keine Garantie oder Rücknahme, da Privatverkauf."
)


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

    return json.loads(text)


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
        if len(res["tutti_title"]) > 80:
            res["tutti_title"] = res["tutti_title"][:80].strip()

    if "ebay_de_title" in res and isinstance(res["ebay_de_title"], str):
        res["ebay_de_title"] = _truncate_title(res["ebay_de_title"], 80)

    if "kleinanzeigen_title" in res and isinstance(res["kleinanzeigen_title"], str):
        res["kleinanzeigen_title"] = _truncate_title(res["kleinanzeigen_title"], 65)

    # 3. Mandatory Swiss warranty disclaimer in descriptions
    ricardo_desc = res.get("ricardo_description", "")
    if "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme" not in ricardo_desc:
        res["ricardo_description"] = f"{ricardo_desc.rstrip()}\n\n{SWISS_LEGAL_DISCLAIMER}".strip()

    tutti_desc = res.get("tutti_description", "")
    if "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme" not in tutti_desc:
        res["tutti_description"] = f"{tutti_desc.rstrip()}\n\n{SWISS_LEGAL_DISCLAIMER}".strip()

    # 4. Mandatory German warranty disclaimer in descriptions
    if "ebay_de_description" in res:
        ebay_desc = res.get("ebay_de_description", "")
        if "Ausschluss jeglicher Sachmängelhaftung" not in ebay_desc:
            res["ebay_de_description"] = f"{ebay_desc.rstrip()}\n\n{GERMAN_LEGAL_DISCLAIMER}".strip()
    elif "ebay_de_title" in res:
        res["ebay_de_description"] = GERMAN_LEGAL_DISCLAIMER

    if "kleinanzeigen_description" in res:
        klein_desc = res.get("kleinanzeigen_description", "")
        if "Ausschluss jeglicher Sachmängelhaftung" not in klein_desc:
            res["kleinanzeigen_description"] = f"{klein_desc.rstrip()}\n\n{GERMAN_LEGAL_DISCLAIMER}".strip()
    elif "kleinanzeigen_title" in res:
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
   - Tutti: Titel bis 80 Zeichen. Passende Tutti-Kategorie. Freundlicher Kleinanzeigentext inkl. Abholung/Versand und TWINT. Schweizer Hochdeutsch (IMMER 'ss', NIEMALS 'ß'!). Pflichtklausel: "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
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
  "tutti_title": "string (max 80 Zeichen)",
  "tutti_category": "string",
  "tutti_description": "string",
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


class AIService:
    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        enable_search_grounding: bool = True,
        eur_to_chf: float = 0.94,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.enable_search_grounding = enable_search_grounding
        self.eur_to_chf = eur_to_chf
        self._client: Optional[genai.Client] = None
        self.ebay_service = EbayService(default_eur_to_chf=eur_to_chf)

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def set_api_key(self, api_key: str, model_name: Optional[str] = None):
        """Update API key and optionally model name, resetting the client."""
        self.api_key = api_key
        if model_name:
            self.model_name = model_name
        self._client = genai.Client(api_key=self.api_key)

    def get_generate_config(self) -> types.GenerateContentConfig:
        if self.enable_search_grounding:
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
    ) -> Draft:
        user_prompt_parts = [
            f"Benutzernotizen zum Artikel: {draft.user_notes or 'Keine Notizen'}\n"
        ]

        if ebay_stats and ebay_stats.sample_count > 0:
            user_prompt_parts.append(
                f"eBay DE verkaufte Artikel (Transaktionspreise): "
                f"Stichprobe={ebay_stats.sample_count}, "
                f"Median EUR={ebay_stats.median_eur} €, "
                f"Median CHF={ebay_stats.median_chf} CHF (Wechselkurs {ebay_stats.exchange_rate}), "
                f"Spanne EUR={ebay_stats.min_eur} € - {ebay_stats.max_eur} €.\n"
            )

        user_prompt_parts.append(
            "Bitte analysiere die bereitgestellten Fotos und Informationen und liefere das JSON-Objekt."
        )

        contents: list = ["\n".join(user_prompt_parts)]

        # Attach image files
        for p in image_paths:
            if p.exists():
                try:
                    img_bytes = p.read_bytes()
                    part = types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                    contents.append(part)
                except Exception as e:
                    logger.warning(f"Failed to read image {p}: {e}")

        config = self.get_generate_config()
        raw_text = await self._call_gemini(contents=contents, config=config)
        raw_payload = extract_and_parse_json(raw_text)
        payload = post_process_ai_output(raw_payload)

        # Update draft
        product_name = payload.get("identified_product", draft.user_notes or "Artikel")
        draft.identified_product = product_name
        draft.missing_photo_hints = payload.get("missing_photo_hints", [])

        # Build verification links
        v_links = self.ebay_service.build_verification_links(product_name)

        draft.price_analysis = PriceAnalysis(
            ebay_stats=ebay_stats,
            ch_new_price_chf=payload.get("ch_new_price_chf"),
            de_new_price_eur=payload.get("de_new_price_eur"),
            ricardo_start_chf=float(payload.get("ricardo_start_chf", 1.0)),
            ricardo_buynow_chf=float(payload.get("ricardo_buynow_chf", 10.0)),
            tutti_vhb_chf=float(payload.get("tutti_vhb_chf", 10.0)),
            ebay_start_eur=float(payload.get("ebay_start_eur", 1.0)),
            ebay_buynow_eur=float(payload.get("ebay_buynow_eur", 10.0)),
            kleinanzeigen_vb_eur=float(payload.get("kleinanzeigen_vb_eur", 10.0)),
            reasoning=payload.get("reasoning", ""),
            verification_links=v_links,
        )

        # Map condition safely
        def map_cond(val: Optional[str]) -> ConditionType:
            try:
                return ConditionType(str(val).lower())
            except (ValueError, TypeError):
                return ConditionType.GEBRAUCHT

        draft.ricardo.title = payload.get("ricardo_title", draft.ricardo.title)
        draft.ricardo.description = payload.get("ricardo_description", draft.ricardo.description)
        draft.ricardo.condition = map_cond(payload.get("ricardo_condition"))
        draft.ricardo.start_price_chf = float(payload.get("ricardo_start_chf", draft.ricardo.start_price_chf))
        draft.ricardo.buynow_price_chf = float(payload.get("ricardo_buynow_chf", draft.ricardo.buynow_price_chf))

        draft.tutti.title = payload.get("tutti_title", draft.tutti.title)
        draft.tutti.category_suggestion = payload.get("tutti_category", draft.tutti.category_suggestion)
        draft.tutti.description = payload.get("tutti_description", draft.tutti.description)
        draft.tutti.condition = map_cond(payload.get("tutti_condition"))
        draft.tutti.price_vhb_chf = float(payload.get("tutti_vhb_chf", draft.tutti.price_vhb_chf))

        draft.ebay_de.title = payload.get("ebay_de_title", draft.ebay_de.title)
        draft.ebay_de.category_suggestion = payload.get("ebay_de_category", draft.ebay_de.category_suggestion)
        draft.ebay_de.description = payload.get("ebay_de_description", draft.ebay_de.description)
        draft.ebay_de.condition = map_cond(payload.get("ebay_de_condition"))
        draft.ebay_de.start_price_eur = float(payload.get("ebay_start_eur", draft.ebay_de.start_price_eur))
        draft.ebay_de.buynow_price_eur = float(payload.get("ebay_buynow_eur", draft.ebay_de.buynow_price_eur))

        draft.kleinanzeigen.title = payload.get("kleinanzeigen_title", draft.kleinanzeigen.title)
        draft.kleinanzeigen.category_suggestion = payload.get("kleinanzeigen_category", draft.kleinanzeigen.category_suggestion)
        draft.kleinanzeigen.description = payload.get("kleinanzeigen_description", draft.kleinanzeigen.description)
        draft.kleinanzeigen.condition = map_cond(payload.get("kleinanzeigen_condition"))
        draft.kleinanzeigen.price_eur = float(payload.get("kleinanzeigen_vb_eur", draft.kleinanzeigen.price_eur))

        draft.status = DraftStatus.READY
        return draft
