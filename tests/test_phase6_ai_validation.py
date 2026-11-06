from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from backend.models import Draft, DraftStatus
from backend.services.ai_service import (
    GERMAN_LEGAL_DISCLAIMER,
    SWISS_LEGAL_DISCLAIMER,
    AIAnalysisResponse,
    AIService,
    extract_and_parse_json,
    is_draft_ready,
    post_process_ai_output,
    safe_price,
)


def test_extract_and_parse_json_trailing_commas_and_fences():
    # Code fence with trailing commas
    raw = """
    ```json
    {
        "identified_product": "Sony WH-1000XM4",
        "missing_photo_hints": ["Seriennummer",],
        "ricardo_start_chf": 150.0,
    }
    ```
    """
    parsed = extract_and_parse_json(raw)
    assert parsed["identified_product"] == "Sony WH-1000XM4"
    assert parsed["missing_photo_hints"] == ["Seriennummer"]
    assert parsed["ricardo_start_chf"] == 150.0


def test_extract_and_parse_json_rejects_non_dict():
    with pytest.raises(ValueError, match="JSON object"):
        extract_and_parse_json('["item1", "item2"]')


def test_ai_analysis_response_price_sanitization():
    raw = {
        "identified_product": "Test Item",
        "ricardo_start_chf": -10.5,
        "ricardo_buynow_chf": "float('nan')",
        "tutti_vhb_chf": "25.50",
        "ebay_start_eur": -5,
        "ebay_buynow_eur": 50.1234,
        "extra_unknown_field": "should be ignored",
    }
    validated = AIAnalysisResponse.model_validate(raw)
    assert validated.identified_product == "Test Item"
    assert validated.ricardo_start_chf is None
    assert validated.ricardo_buynow_chf is None
    assert validated.tutti_vhb_chf == 25.50
    assert validated.ebay_start_eur is None
    assert validated.ebay_buynow_eur == 50.12
    assert not hasattr(validated, "extra_unknown_field") or "extra_unknown_field" not in validated.model_dump()


def test_post_process_ai_output_null_descriptions():
    payload = {
        "ricardo_title": "A" * 80,  # Should be truncated to 60
        "ricardo_description": None,
        "tutti_title": "B" * 90,  # Should be truncated to 80
        "tutti_description": None,
        "ebay_de_title": "C" * 100,  # Should be truncated to 80
        "ebay_de_description": None,
        "kleinanzeigen_title": "D" * 80,  # Should be truncated to 65
        "kleinanzeigen_description": None,
    }

    processed = post_process_ai_output(payload)
    assert len(processed["ricardo_title"]) <= 60
    assert len(processed["tutti_title"]) <= 80
    assert len(processed["ebay_de_title"]) <= 80
    assert len(processed["kleinanzeigen_title"]) <= 65

    # Should safely append disclaimers without throwing TypeError
    assert SWISS_LEGAL_DISCLAIMER in processed["ricardo_description"]
    assert "ß" not in processed["ricardo_description"]
    assert SWISS_LEGAL_DISCLAIMER in processed["tutti_description"]
    assert "ß" not in processed["tutti_description"]
    assert GERMAN_LEGAL_DISCLAIMER in processed["ebay_de_description"]
    assert GERMAN_LEGAL_DISCLAIMER in processed["kleinanzeigen_description"]


def _make_draft(draft_id: str = "draft-1") -> Draft:
    now_str = datetime.now(timezone.utc).isoformat()
    return Draft(id=draft_id, created_at=now_str, updated_at=now_str)


def test_is_draft_ready():
    draft = _make_draft("draft-1")
    assert not is_draft_ready(draft)

    draft.identified_product = "Logitech MX Master 3S"
    assert not is_draft_ready(draft)

    draft.ricardo.title = "Logitech MX Master 3S Maus"
    assert not is_draft_ready(draft)

    draft.ricardo.description = "Funktioniert einwandfrei."
    assert is_draft_ready(draft)


def test_safe_price():
    assert safe_price(-5.0, default=10.0) == 10.0
    assert safe_price("invalid", default=5.0) == 5.0
    assert safe_price(15.999, default=0.0) == 16.0
    assert safe_price(None, default=1.0) == 1.0


@pytest.mark.asyncio
async def test_analyze_draft_sets_readiness_and_sanitizes(tmp_path):
    service = AIService(api_key="test-key", model_name="gemini-3.8-flash")

    # Mock Gemini call
    service._call_gemini = AsyncMock(
        return_value="""{
            "identified_product": "Bose QuietComfort 45",
            "missing_photo_hints": [],
            "ricardo_title": "Bose QuietComfort 45 Kopfhörer",
            "ricardo_description": "Top Zustand inkl. Case.",
            "ricardo_condition": "gebraucht",
            "ricardo_start_chf": -50.0,
            "ricardo_buynow_chf": 180.0
        }"""
    )

    draft = _make_draft("draft-ready-test")
    res = await service.analyze_draft(draft, image_paths=[])

    assert res.status == DraftStatus.READY
    assert res.identified_product == "Bose QuietComfort 45"
    assert res.ricardo.title == "Bose QuietComfort 45 Kopfhörer"
    # -50 was sanitized to fallback (1.0 in analyze_draft safe_price for start_chf)
    assert res.ricardo.start_price_chf == 1.0
    assert res.ricardo.buynow_price_chf == 180.0


@pytest.mark.asyncio
async def test_analyze_draft_leaves_incomplete_as_draft():
    service = AIService(api_key="test-key", model_name="gemini-3.8-flash")
    # Response without product identification or listings
    service._call_gemini = AsyncMock(
        return_value="""{
            "identified_product": "",
            "missing_photo_hints": ["Bitte Vorderseite fotografieren"]
        }"""
    )

    draft = _make_draft("draft-incomplete-test")
    res = await service.analyze_draft(draft, image_paths=[])

    assert res.status == DraftStatus.DRAFT
    assert "Bitte Vorderseite fotografieren" in res.missing_photo_hints
