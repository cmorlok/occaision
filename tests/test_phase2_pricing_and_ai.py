import json
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import (
    ConditionType,
    Draft,
    DraftImage,
    EbaySoldStats,
    ImageVariantMode,
    MarketSourceStats,
    OfferType,
    PriceAnalysis,
    RicardoListing,
    TuttiListing,
)
from backend.services.ai_service import (
    AIService,
    build_verification_links,
    extract_and_parse_json,
    post_process_ai_output,
)
from backend.storage import StorageService


def test_verification_links_generation():
    links = build_verification_links("Sony WH-1000XM4")

    assert "https://www.ebay.de/sch/i.html" in links.ebay_sold_url
    assert "LH_Sold=1" in links.ebay_sold_url
    assert "LH_Complete=1" in links.ebay_sold_url
    assert "LH_ItemCondition=3000" in links.ebay_sold_url
    assert "Sony" in links.ebay_sold_url

    assert "kleinanzeigen.de" in links.kleinanzeigen_search_url
    assert "anbieter:privat" in links.kleinanzeigen_search_url
    assert "global.zustand:alright%2Clike_new%2Cok" in links.kleinanzeigen_search_url
    assert "Sony" in links.kleinanzeigen_search_url

    assert "idealo.de" in links.idealo_url
    assert "Sony" in links.idealo_url

    assert "https://www.ricardo.ch/de/s/" in links.ricardo_search_url
    assert "Sony" in links.ricardo_search_url
    assert "item_condition=used" in links.ricardo_search_url
    assert "seller_type=individual" in links.ricardo_search_url

    assert "https://www.toppreise.ch/produktsuche" in links.toppreise_url
    assert "Sony" in links.toppreise_url

    assert ("galaxus.ch/de/search" in links.digitec_url or "digitec.ch/de/search" in links.digitec_url)
    assert "Sony" in links.digitec_url

    assert "tutti.ch" in links.tutti_search_url


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
        "tutti_title": "Großartiger Lautsprecher in weiß mit fantastischem Sound und bestem Bass Top Zustand",
        "tutti_category": "Audio & TV",
        "tutti_description": "Schöner weißer Lautsprecher zu verkaufen. " + ("Sehr detailreich. " * 300),
        "tutti_condition": "gebraucht",
        "ebay_de_title": "Großartiger Lautsprecher mit fantastischem Sound in perfekter Größe und Zustand für Musikliebhaber",
        "ebay_de_description": "Hier verkaufe ich einen tollen Lautsprecher in Top Zustand.",
        "kleinanzeigen_title": "Großartiger Lautsprecher in weiß mit tollem Sound und extra Kabel",
        "kleinanzeigen_description": "Verkaufe schönen Lautsprecher in weiß.",
    }

    processed = post_process_ai_output(raw_payload)

    # 1. Ricardo and Tutti title length limits: <= 60 chars
    assert len(processed["ricardo_title"]) <= 60
    assert len(processed["tutti_title"]) <= 60
    assert len(processed["tutti_description"]) <= 4000
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

    with caplog.at_level(logging.DEBUG, logger="occaision.ai"):
        with patch.object(ai_service, "_call_gemini", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = json.dumps(mock_resp)
            await ai_service.analyze_draft(draft=draft, image_paths=[])

    assert any("GEMINI AI PROMPT DEBUG START" in rec.message for rec in caplog.records)
    assert any("SYSTEM INSTRUCTION" in rec.message for rec in caplog.records)
    assert any("USER PROMPT" in rec.message for rec in caplog.records)
    assert any("GEMINI AI RAW RESPONSE DEBUG START" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_extension_scraped_prices_injected_into_ai_and_grounding_disabled(temp_data_dir: Path):
    storage = StorageService(data_dir=temp_data_dir)
    draft = storage.create_draft(
        user_notes="Wenig gebraucht, inklusive OVP und Original-Toner",
        identified_product="HP Color LaserJet Pro MFP 4302fdw",
    )
    draft.price_analysis.prices_fetched_via_extension = True
    draft.price_analysis.market_sources = {
        "ebay_de_sold": MarketSourceStats(
            source_id="ebay_de_sold",
            label="eBay DE (Gebraucht & Beendet)",
            currency="EUR",
            sample_count=5,
            min_price=240.0,
            max_price=320.0,
            median_price=280.0,
            median_chf=263.2,
            method="fetch",
        ),
        "kleinanzeigen": MarketSourceStats(
            source_id="kleinanzeigen",
            label="Kleinanzeigen.de Suche",
            currency="EUR",
            sample_count=8,
            min_price=250.0,
            max_price=350.0,
            median_price=295.0,
            median_chf=277.3,
            method="fetch",
        ),
        "idealo": MarketSourceStats(
            source_id="idealo",
            label="Idealo.de Neupreis",
            currency="EUR",
            sample_count=4,
            min_price=429.0,
            max_price=489.0,
            median_price=449.0,
            median_chf=422.06,
            method="tab",
        ),
        "ricardo": MarketSourceStats(
            source_id="ricardo",
            label="Ricardo.ch Suche",
            currency="CHF",
            sample_count=3,
            min_price=260.0,
            max_price=330.0,
            median_price=290.0,
            median_chf=290.0,
            method="tab",
        ),
        "toppreise": MarketSourceStats(
            source_id="toppreise",
            label="Toppreise.ch Neupreis",
            currency="CHF",
            sample_count=5,
            min_price=399.0,
            max_price=450.0,
            median_price=415.0,
            median_chf=415.0,
            method="fetch",
        ),
        "digitec": MarketSourceStats(
            source_id="digitec",
            label="Digitec/Galaxus Suche",
            currency="CHF",
            sample_count=2,
            min_price=419.0,
            max_price=429.0,
            median_price=424.0,
            median_chf=424.0,
            method="tab",
        ),
    }

    ai_service = AIService(
        api_key="test_key",
        model_name="gemini-3.8-flash",
        enable_search_grounding=True,  # Enabled globally, but must be auto-disabled when Extension prices exist
    )

    mock_resp = {
        "identified_product": "HP Color LaserJet Pro MFP 4302fdw",
        "missing_photo_hints": [],
        "ch_new_price_chf": 415.0,
        "de_new_price_eur": 449.0,
        "ricardo_start_chf": 220.0,
        "ricardo_buynow_chf": 279.0,
        "tutti_vhb_chf": 290.0,
        "ebay_start_eur": 210.0,
        "ebay_buynow_eur": 275.0,
        "kleinanzeigen_vb_eur": 290.0,
        "reasoning": "Basierend auf den 6 übermittelten Extension-Preisquellen berechnet.",
        "ricardo_title": "HP Color LaserJet Pro MFP 4302fdw Farblaser Top",
        "ricardo_description": "Top Drucker.",
        "ricardo_condition": "gebraucht",
        "tutti_title": "HP Color LaserJet Pro MFP 4302fdw Multifunktionsdrucker",
        "tutti_category": "Büro & Gewerbe > Drucker",
        "tutti_description": "Verkaufe HP Farblaserdrucker.",
        "tutti_condition": "gebraucht",
        "ebay_de_title": "HP Color LaserJet Pro MFP 4302fdw Farblaserdrucker WLAN Duplex OVP",
        "ebay_de_category": "Computer, Tablets & Netzwerk > Drucker",
        "ebay_de_description": "Gebrauchter HP Farblaserdrucker in sehr gutem Zustand.",
        "ebay_de_condition": "gebraucht",
        "kleinanzeigen_title": "HP Color LaserJet Pro MFP 4302fdw Farblaser WLAN Top",
        "kleinanzeigen_category": "PC-Zubehör & Software > Drucker & Scanner",
        "kleinanzeigen_description": "Verkaufe unseren HP Color LaserJet Pro MFP 4302fdw.",
        "kleinanzeigen_condition": "gebraucht",
    }

    with patch.object(ai_service, "_call_gemini", new_callable=AsyncMock) as mock_call:
        mock_call.return_value = json.dumps(mock_resp)
        result_draft = await ai_service.analyze_draft(draft=draft, image_paths=[])

        assert mock_call.called
        call_kwargs = mock_call.call_args.kwargs
        passed_contents = call_kwargs["contents"]
        passed_config = call_kwargs["config"]

        # 1. Google Search Grounding must be disabled when extension prices are provided
        assert getattr(passed_config, "tools", None) is None
        assert getattr(passed_config, "response_mime_type", None) == "application/json"

        # 2. All 6 price sources and split inputs must be included in the prompt text
        prompt_str = passed_contents[0]
        assert "HP Color LaserJet Pro MFP 4302fdw" in prompt_str
        assert "Wenig gebraucht, inklusive OVP" in prompt_str
        assert "280.0" in prompt_str   # eBay DE sold median
        assert "295.0" in prompt_str   # Kleinanzeigen median
        assert "449.0" in prompt_str   # Idealo median
        assert "290.0" in prompt_str   # Ricardo median
        assert "415.0" in prompt_str   # Toppreise median
        assert "424.0" in prompt_str   # Digitec median

        # 3. Draft must preserve extension market_sources and flag
        assert result_draft.price_analysis.prices_fetched_via_extension is True
        assert len(result_draft.price_analysis.market_sources) == 6
        assert result_draft.price_analysis.market_sources["idealo"].median_price == 449.0


@pytest.mark.asyncio
async def test_ai_filters_out_disabled_price_sources(temp_data_dir: Path):
    storage = StorageService(data_dir=temp_data_dir)
    draft = storage.create_draft(
        user_notes="Wenig gebraucht",
        identified_product="Sony WH-1000XM4",
    )
    draft.price_analysis.prices_fetched_via_extension = True
    draft.price_analysis.market_sources = {
        "ebay_de_sold": MarketSourceStats(
            source_id="ebay_de_sold",
            label="eBay DE (Gebraucht & Beendet)",
            currency="EUR",
            sample_count=4,
            median_price=150.0,
            median_chf=141.0,
        ),
        "kleinanzeigen": MarketSourceStats(
            source_id="kleinanzeigen",
            label="Kleinanzeigen.de Suche",
            currency="EUR",
            sample_count=5,
            median_price=160.0,
            median_chf=150.4,
        ),
        "idealo": MarketSourceStats(
            source_id="idealo",
            label="Idealo.de Neupreis",
            currency="EUR",
            sample_count=3,
            median_price=279.0,
            median_chf=262.26,
        ),
    }

    ai_service = AIService(api_key="test_key", model_name="gemini-3.8-flash")
    mock_resp = {
        "identified_product": "Sony WH-1000XM4",
        "missing_photo_hints": [],
        "ricardo_start_chf": 70.0,
        "ricardo_buynow_chf": 120.0,
        "tutti_vhb_chf": 130.0,
        "ebay_start_eur": 65.0,
        "ebay_buynow_eur": 120.0,
        "kleinanzeigen_vb_eur": 130.0,
        "reasoning": "Nur Kleinanzeigen aktiviert.",
        "ricardo_title": "Sony WH-1000XM4",
        "ricardo_description": "Top Kopfhörer.",
        "tutti_title": "Sony WH-1000XM4",
        "tutti_category": "Audio",
        "tutti_description": "Top Kopfhörer.",
    }

    with patch.object(ai_service, "_call_gemini", new_callable=AsyncMock) as mock_call:
        import json
        mock_call.return_value = json.dumps(mock_resp)

        # Only 'kleinanzeigen' is enabled; 'ebay_de_sold' and 'idealo' are excluded
        await ai_service.analyze_draft(
            draft=draft,
            image_paths=[],
            ebay_stats=None,
            enabled_sources=["kleinanzeigen"],
        )

        assert mock_call.called
        call_kwargs = mock_call.call_args.kwargs
        passed_contents = call_kwargs["contents"]
        prompt_str = passed_contents[0]

        # Must include kleinanzeigen
        assert "Kleinanzeigen.de Suche" in prompt_str
        assert "160.0" in prompt_str

        # Must NOT include disabled sources in the prompt
        assert "eBay DE (Gebraucht & Beendet)" not in prompt_str
        assert "Idealo.de Neupreis" not in prompt_str
        assert "279.0" not in prompt_str


def test_ai_service_model_discovery_offline_and_cache(monkeypatch):
    svc = AIService(api_key="test_key")

    # In test environment with dummy key, should return fallback models without touching client
    models = svc.get_available_models()
    assert len(models) >= 5
    assert any(m["id"] == "gemini-3.8-flash" for m in models)

    # With live-looking key, mock the Gemini client models.list()
    svc.set_api_key("valid_live_api_key_12345")
    mock_model = MagicMock()
    mock_model.name = "models/gemini-3.8-flash"
    mock_model.display_name = "Gemini 3.8 Flash"
    mock_model.supported_actions = ["generateContent"]

    mock_client = MagicMock()
    mock_client.models.list.return_value = [mock_model]
    svc._client = mock_client

    # Force test env guard off temporarily to test remote success path & caching
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("OCCAISION_OFFLINE", "0")
    with patch("sys.modules", {k: v for k, v in sys.modules.items() if k != "pytest"}):
        res1 = svc.get_available_models()
        assert len(res1) == 1
        assert res1[0]["id"] == "gemini-3.8-flash"
        assert mock_client.models.list.call_count == 1

        # Second call must hit the TTL cache and NOT call models.list() again
        res2 = svc.get_available_models()
        assert res2 == res1
        assert mock_client.models.list.call_count == 1

        # Key change resets cache
        svc.set_api_key("valid_live_api_key_67890")
        assert svc._models_cache is None





