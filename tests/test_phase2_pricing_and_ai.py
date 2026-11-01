import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.models import (
    ConditionType,
    Draft,
    DraftImage,
    EbaySoldStats,
    ImageVariantMode,
    OfferType,
    PriceAnalysis,
    RicardoListing,
    TuttiListing,
)
from backend.services.ai_service import AIService, extract_and_parse_json, post_process_ai_output
from backend.services.ebay_service import EbayService
from backend.storage import StorageService


MOCK_EBAY_HTML = """
<!DOCTYPE html>
<html>
<body>
<div class="s-item">
    <div class="s-item__title">Shop on eBay</div>
    <span class="s-item__price">EUR 19,99</span>
</div>
<div class="s-item">
    <div class="s-item__title">Sony WH-1000XM4 Kopfhörer Schwarz</div>
    <span class="s-item__price">EUR 1,00</span>
</div>
<div class="s-item">
    <div class="s-item__title">Sony WH-1000XM4 Wireless Kopfhörer Top Zustand</div>
    <span class="s-item__price">EUR 150,00</span>
</div>
<div class="s-item">
    <div class="s-item__title">Sony WH-1000XM4 Noise Cancelling</div>
    <span class="s-item__price">160,00 €</span>
</div>
<div class="s-item">
    <div class="s-item__title">Sony WH 1000 XM4 Over-Ear Headphone</div>
    <span class="s-item__price">EUR 170,00</span>
</div>
<div class="s-item">
    <div class="s-item__title">Sony WH-1000XM4 Verschiedene Farben</div>
    <span class="s-item__price">EUR 100,00 bis EUR 200,00</span>
</div>
</body>
</html>
"""

MOCK_EBAY_CHALLENGE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Pardon Our Interruption</title></head>
<body>
<div id="splashui/challenge">Please solve the captcha</div>
</body>
</html>
"""


def test_ebay_sold_html_parser_and_currency_conversion():
    ebay_service = EbayService()
    
    stats = ebay_service.parse_sold_html(MOCK_EBAY_HTML, query="Sony WH-1000XM4", eur_to_chf=0.94)
    
    # 4 valid prices: 1.0, 150.0, 160.0, 170.0
    # Range price "EUR 100,00 bis EUR 200,00" and placeholder "Shop on eBay" must be skipped
    assert stats.sample_count == 4
    assert stats.min_eur == 1.0
    assert stats.max_eur == 170.0
    assert stats.median_eur is not None
    assert stats.median_chf is not None
    # Median of [1.0, 150.0, 160.0, 170.0] -> (150+160)/2 = 155.0
    # Or with 10% trim: [1.0, 150.0, 160.0, 170.0] trimmed -> 155.0
    assert stats.median_eur == pytest.approx(155.0, abs=1.0)
    assert stats.median_chf == round(stats.median_eur * 0.94, 2)
    
    # Verify challenge page handling
    challenge_stats = ebay_service.parse_sold_html(MOCK_EBAY_CHALLENGE_HTML, query="Sony WH-1000XM4")
    assert challenge_stats.sample_count == 0
    assert challenge_stats.median_eur is None
    assert challenge_stats.median_chf is None


def test_verification_links_generation():
    ebay_service = EbayService()
    links = ebay_service.build_verification_links("Sony WH-1000XM4")
    
    assert "https://www.ebay.de/sch/i.html" in links.ebay_sold_url
    assert "LH_Sold=1" in links.ebay_sold_url
    assert "LH_Complete=1" in links.ebay_sold_url
    assert "Sony" in links.ebay_sold_url
    
    assert "kleinanzeigen.de" in links.kleinanzeigen_search_url
    assert "Sony" in links.kleinanzeigen_search_url
    
    assert "idealo.de" in links.idealo_url
    assert "Sony" in links.idealo_url
    
    assert "https://www.ricardo.ch/de/s/" in links.ricardo_search_url
    assert "Sony" in links.ricardo_search_url
    
    assert "https://www.toppreise.ch/produktsuche" in links.toppreise_url
    assert "Sony" in links.toppreise_url
    
    assert "https://www.digitec.ch/de/search" in links.digitec_url
    assert "Sony" in links.digitec_url


def test_ai_json_extractor_and_grounding_config_compatibility():
    ai_service = AIService(
        api_key="test_key",
        model_name="gemini-2.5-flash",
        enable_search_grounding=True,
    )
    
    # Verify grounding config rules
    config = ai_service.get_generate_config()
    if ai_service.enable_search_grounding:
        # Crucial safeguard: response_mime_type must NOT be application/json when tools are active
        assert getattr(config, "response_mime_type", None) != "application/json"
        assert config.tools is not None
        assert len(config.tools) > 0
    
    # Test JSON extraction with markdown fences and preamble
    raw_ai_text = """
    Hier ist die strukturierte Analyse des Artikels:
    ```json
    {
        "identified_product": "Sony WH-1000XM4",
        "missing_photo_hints": ["Bitte Typenschild fotografieren"],
        "ch_new_price_chf": 269.0,
        "ricardo_start_chf": 89.0,
        "ricardo_buynow_chf": 149.0,
        "tutti_vhb_chf": 160.0,
        "reasoning": "Guter Zustand mit OVP.",
        "ricardo_title": "Sony WH-1000XM4 ANC Kopfhörer Top Zustand",
        "ricardo_description": "Top Kopfhörer mit super Sound.\\n\\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.",
        "ricardo_condition": "gebraucht",
        "tutti_title": "Sony WH-1000XM4 Kopfhörer Bluetooth ANC",
        "tutti_category": "Audio & TV > Kopfhörer",
        "tutti_description": "Verkaufe meine Sony Kopfhörer.\\n\\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.",
        "tutti_condition": "gebraucht"
    }
    ```
    Hoffe das hilft!
    """
    parsed = extract_and_parse_json(raw_ai_text)
    assert parsed["identified_product"] == "Sony WH-1000XM4"
    assert parsed["ricardo_start_chf"] == 89.0
    assert len(parsed["missing_photo_hints"]) == 1


def test_ai_post_processing_safeguards():
    # Ricardo title is 72 chars (> 60), contains 'ß', description missing disclaimer
    raw_payload = {
        "identified_product": "Großartiger Lautsprecher",
        "missing_photo_hints": ["Bitte großes Typenschild auf der Rückseite fotografieren"],
        "ch_new_price_chf": 199.0,
        "ricardo_start_chf": 50.0,
        "ricardo_buynow_chf": 90.0,
        "tutti_vhb_chf": 95.0,
        "reasoning": "Guter Marktpreis.",
        "ricardo_title": "Großartiger Lautsprecher mit fantastischem Sound und weißem Gehäuse Top!",
        "ricardo_description": "Zustand: Sehr gut, wenig genutzt.",
        "ricardo_condition": "gebraucht",
        "tutti_title": "Großartiger Lautsprecher weiß guter Zustand",
        "tutti_category": "Audio & TV",
        "tutti_description": "Schöner weißer Lautsprecher zu verkaufen.",
        "tutti_condition": "gebraucht",
        "ebay_de_title": "Großartiger Lautsprecher mit fantastischem Sound in perfekter Größe und Zustand für Musikliebhaber",
        "ebay_de_description": "Hier verkaufe ich einen tollen Lautsprecher in Top Zustand.",
        "kleinanzeigen_title": "Großartiger Lautsprecher in weiß mit tollem Sound und extra Kabel",
        "kleinanzeigen_description": "Verkaufe schönen Lautsprecher in weiß.",
    }
    
    processed = post_process_ai_output(raw_payload)
    
    # 1. Ricardo title length limit: <= 60 chars
    assert len(processed["ricardo_title"]) <= 60
    # 2. Swiss German orthography: no 'ß' in strings or list of strings
    assert "ß" not in processed["ricardo_title"]
    assert "ß" not in processed["tutti_title"]
    assert "ß" not in processed["ricardo_description"]
    assert "ß" not in processed["tutti_description"]
    assert "ß" not in processed["missing_photo_hints"][0]
    assert "grosses" in processed["missing_photo_hints"][0].lower()
    assert "gross" in processed["ricardo_title"].lower()
    
    # 3. Mandatory Swiss warranty disclaimer
    assert "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme." in processed["ricardo_description"]
    assert "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme." in processed["tutti_description"]

    # 4. DE platform safeguards
    assert len(processed["ebay_de_title"]) <= 80
    assert len(processed["kleinanzeigen_title"]) <= 65
    assert "ß" in processed["ebay_de_title"]  # "Größe" preserves 'ß'
    assert "ß" in processed["kleinanzeigen_title"]  # "weiß" preserves 'ß'
    assert "Ausschluss jeglicher Sachmängelhaftung" in processed["ebay_de_description"]
    assert "Ausschluss jeglicher Sachmängelhaftung" in processed["kleinanzeigen_description"]


@pytest.mark.asyncio
async def test_iterative_reanalysis_preserves_draft_id_and_updates_hints(temp_data_dir: Path):
    storage = StorageService(data_dir=temp_data_dir)
    draft = storage.create_draft(user_notes="Sony Kopfhörer")
    original_id = draft.id
    
    # Add dummy image
    draft.images.append(
        DraftImage(
            id="img_1",
            original_filename="front.jpg",
            active_mode=ImageVariantMode.OPTIMIZED,
            width=1000,
            height=800,
        )
    )
    storage.update_draft(draft)
    
    ai_service = AIService(
        api_key="mock_key",
        model_name="gemini-2.5-flash",
        enable_search_grounding=False,
    )
    
    # Mock LLM response 1: missing hints returned
    mock_response_1 = {
        "identified_product": "Sony WH-1000XM4",
        "missing_photo_hints": ["Bitte Typenschild fotografieren"],
        "ch_new_price_chf": 250.0,
        "ricardo_start_chf": 80.0,
        "ricardo_buynow_chf": 140.0,
        "tutti_vhb_chf": 150.0,
        "reasoning": "Gebraucht, Zubehör unvollständig",
        "ricardo_title": "Sony WH-1000XM4 Kopfhörer ANC",
        "ricardo_description": "Beschreibung 1",
        "ricardo_condition": "gebraucht",
        "tutti_title": "Sony WH-1000XM4 Kopfhörer",
        "tutti_category": "Audio",
        "tutti_description": "Beschreibung Tutti 1",
        "tutti_condition": "gebraucht"
    }
    
    with patch.object(ai_service, "_call_gemini", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(mock_response_1)
        
        updated_draft_1 = await ai_service.analyze_draft(
            draft=draft,
            image_paths=[],
            ebay_stats=EbaySoldStats(query="Sony WH-1000XM4", sample_count=3, median_eur=140.0, median_chf=131.6),
        )
        storage.update_draft(updated_draft_1)
        
        assert updated_draft_1.id == original_id
        assert updated_draft_1.missing_photo_hints == ["Bitte Typenschild fotografieren"]
        assert updated_draft_1.price_analysis.ebay_stats is not None
        assert updated_draft_1.price_analysis.ebay_stats.median_chf == 131.6
        
        # User uploads second photo: label/serial photo
        updated_draft_1.images.append(
            DraftImage(
                id="img_2",
                original_filename="serial_label.jpg",
                active_mode=ImageVariantMode.OPTIMIZED,
                width=1000,
                height=800,
            )
        )
        storage.update_draft(updated_draft_1)
        
        # Mock LLM response 2: missing hints resolved
        mock_response_2 = dict(mock_response_1)
        mock_response_2["missing_photo_hints"] = []
        mock_call.return_value = json.dumps(mock_response_2)
        
        updated_draft_2 = await ai_service.analyze_draft(
            draft=updated_draft_1,
            image_paths=[],
            ebay_stats=EbaySoldStats(query="Sony WH-1000XM4", sample_count=3, median_eur=140.0, median_chf=131.6),
        )
        storage.update_draft(updated_draft_2)
        
        assert updated_draft_2.id == original_id
        assert len(updated_draft_2.missing_photo_hints) == 0
        assert len(updated_draft_2.images) == 2


@pytest.mark.asyncio
async def test_ai_prompt_debug_logging(temp_data_dir: Path, caplog):
    storage = StorageService(data_dir=temp_data_dir)
    draft = storage.create_draft(user_notes="Apple iPad Pro 11 M2")
    ai_service = AIService(
        api_key="test_key",
        model_name="gemini-3.8-flash",
        enable_search_grounding=True,
    )

    mock_resp = {
        "identified_product": "Apple iPad Pro 11 M2",
        "missing_photo_hints": [],
        "ricardo_start_chf": 100.0,
        "ricardo_buynow_chf": 500.0,
        "tutti_vhb_chf": 500.0,
    }

    with caplog.at_level(logging.DEBUG, logger="seller.ai"):
        with patch.object(ai_service, "_call_gemini", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = json.dumps(mock_resp)
            await ai_service.analyze_draft(draft=draft, image_paths=[])

    assert any("GEMINI AI PROMPT DEBUG START" in rec.message for rec in caplog.records)
    assert any("SYSTEM INSTRUCTION" in rec.message for rec in caplog.records)
    assert any("USER PROMPT" in rec.message for rec in caplog.records)
    assert any("GEMINI AI RAW RESPONSE DEBUG START" in rec.message for rec in caplog.records)
