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


def post_process_ai_output(payload: Dict[str, Any]) -> Dict[str, Any]:
    res = dict(payload)

    # 1. Swiss German orthography: replace 'ß' with 'ss' in all string values
    for k, v in res.items():
        if isinstance(v, str):
            res[k] = v.replace("ß", "ss")

    # 2. Hard limit on Ricardo title (<= 60 chars)
    ricardo_title = res.get("ricardo_title", "")
    if len(ricardo_title) > 60:
        truncated = ricardo_title[:60]
        # Try to break at word boundary if possible
        last_space = truncated.rfind(" ")
        if last_space > 40:
            truncated = truncated[:last_space]
        res["ricardo_title"] = truncated.strip()

    # 3. Hard limit on Tutti title (<= 80 chars)
    tutti_title = res.get("tutti_title", "")
    if len(tutti_title) > 80:
        res["tutti_title"] = tutti_title[:80].strip()

    # 4. Mandatory Swiss warranty disclaimer in descriptions
    ricardo_desc = res.get("ricardo_description", "")
    if "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme" not in ricardo_desc:
        res["ricardo_description"] = f"{ricardo_desc.rstrip()}\n\n{SWISS_LEGAL_DISCLAIMER}".strip()

    tutti_desc = res.get("tutti_description", "")
    if "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme" not in tutti_desc:
        res["tutti_description"] = f"{tutti_desc.rstrip()}\n\n{SWISS_LEGAL_DISCLAIMER}".strip()

    return res


SYSTEM_INSTRUCTION = """
Du bist ein professioneller Verkaufs- und Preisfindungs-Assistent für Schweizer Kleinanzeigen (Ricardo.ch und Tutti.ch).
Deine Aufgabe:
1. Identifiziere den exakten Artikel (Marke, Modell, Spezifikationen) aus den Fotos und Benutzernotizen.
2. Führe einen visuellen Qualitätscheck durch: Falls für Käufer essenzielle Fotos fehlen (z.B. Typenschild/Modellnummer, Nahaufnahme sichtbarer Mängel, erwähntes Zubehör), gib diese als 'missing_photo_hints' auf Deutsch aus.
3. Marktrecherche & Preisfindung:
   - Nutze die Suchergebnisse für den aktuellen Schweizer Neupreis (Digitec/Galaxus/Toppreise.ch) und die übergebenen eBay-DE Sold Statistiken.
   - Beachte: In der Schweiz ist Elektronik neu wegen 8.1% MwSt. oft günstiger als in DE. Gib einen realistischen Neupreis 'ch_new_price_chf' an.
   - Empfehle einen attraktiven Ricardo Startpreis 'ricardo_start_chf' (ca. 65-75% des realistischen Gebrauchtmarktwerts).
   - Empfehle einen realistischen Sofortkaufen-Preis 'ricardo_buynow_chf' (beachte ca. 10-12% Ricardo-Provision; nie über 80% des Schweizer Neupreises bei Gebrauchtware).
   - Empfehle eine Tutti Verhandlungsbasis 'tutti_vhb_chf' (mit ca. 5-10% Verhandlungsspielraum).
4. Erstelle suchbegriffsoptimierte Inserate:
   - Ricardo: Titel STRIKT maximal 60 Zeichen (Marke Modell Kern-Specs Zustand). Strukturierte Beschreibung (Zustand, Lieferumfang, Technische Daten, Versand/Abholung).
   - Tutti: Titel bis 80 Zeichen. Passende Tutti-Kategorie. Freundlicher Kleinanzeigentext inkl. Abholung/Versand und TWINT-Hinweis.
   - WICHTIG: Schweizer Hochdeutsch verwenden (IMMER 'ss', NIEMALS 'ß'!).
   - Pflichtklausel in beiden Beschreibungen: "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."

Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt mit folgender Struktur:
{
  "identified_product": "string",
  "missing_photo_hints": ["string"],
  "ch_new_price_chf": float,
  "ricardo_start_chf": float,
  "ricardo_buynow_chf": float,
  "tutti_vhb_chf": float,
  "reasoning": "string",
  "ricardo_title": "string (max 60 Zeichen)",
  "ricardo_description": "string",
  "ricardo_condition": "neu" | "wie_neu" | "gebraucht" | "defekt",
  "tutti_title": "string (max 80 Zeichen)",
  "tutti_category": "string",
  "tutti_description": "string",
  "tutti_condition": "neu" | "wie_neu" | "gebraucht" | "defekt"
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
            ricardo_start_chf=float(payload.get("ricardo_start_chf", 1.0)),
            ricardo_buynow_chf=float(payload.get("ricardo_buynow_chf", 10.0)),
            tutti_vhb_chf=float(payload.get("tutti_vhb_chf", 10.0)),
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

        draft.status = DraftStatus.READY
        return draft
