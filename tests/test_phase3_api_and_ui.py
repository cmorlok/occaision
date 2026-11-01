import io
from pathlib import Path
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.config import Settings
from backend.main import create_app
from backend.models import (
    ConditionType,
    Draft,
    DraftStatus,
    EbaySoldStats,
    ImageVariantMode,
    OfferType,
    PresetSettings,
)
from backend.services.image_service import ImageService
from backend.storage import StorageService


def create_test_jpeg(width: int = 400, height: int = 300) -> bytes:
    img = Image.new("RGB", (width, height), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def test_app(temp_data_dir: Path):
    test_settings = Settings(
        gemini_api_key="test_api_key",
        data_dir=temp_data_dir,
    )
    # Fast mask extractor for cutout/blur
    def dummy_extractor(img: Image.Image) -> Image.Image:
        rgba = img.convert("RGBA")
        return rgba

    image_service = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_extractor)
    storage_service = StorageService(data_dir=temp_data_dir)
    app = create_app(
        settings=test_settings,
        storage_service=storage_service,
        image_service=image_service,
    )
    return app


def test_full_rest_lifecycle(test_app):
    client = TestClient(test_app)
    
    # 1. Health check
    res_health = client.get("/api/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"
    
    # 2. POST /api/drafts
    res_create = client.post("/api/drafts", json={"user_notes": "Logitech MX Master 3"})
    assert res_create.status_code == 200
    draft_data = res_create.json()
    draft_id = draft_data["id"]
    assert draft_data["user_notes"] == "Logitech MX Master 3"
    assert draft_data["status"] == DraftStatus.DRAFT
    
    # 3. POST /api/drafts/{id}/images (upload 2 test images)
    img1_bytes = create_test_jpeg(800, 600)
    img2_bytes = create_test_jpeg(1200, 900)
    
    files = [
        ("files", ("mouse1.jpg", img1_bytes, "image/jpeg")),
        ("files", ("mouse2.jpg", img2_bytes, "image/jpeg")),
    ]
    res_img = client.post(f"/api/drafts/{draft_id}/images", files=files)
    assert res_img.status_code == 200
    updated_draft = res_img.json()
    assert len(updated_draft["images"]) == 2
    img1_id = updated_draft["images"][0]["id"]
    
    # 4. PATCH image 1 to 'blurred'
    res_patch = client.patch(
        f"/api/drafts/{draft_id}/images/{img1_id}",
        json={"active_mode": "blurred"},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["images"][0]["active_mode"] == "blurred"
    
    # 5. GET /api/drafts/{id}/images/{img_id}/active -> should serve image/jpeg
    res_active_img = client.get(f"/api/drafts/{draft_id}/images/{img1_id}/active")
    assert res_active_img.status_code == 200
    assert "image/jpeg" in res_active_img.headers["content-type"]
    assert len(res_active_img.content) > 0
    
    # 6. POST /api/drafts/{id}/analyze (with mocked AI & eBay services)
    mock_ai_response = {
        "identified_product": "Logitech MX Master 3",
        "missing_photo_hints": [],
        "ch_new_price_chf": 109.0,
        "ricardo_start_chf": 40.0,
        "ricardo_buynow_chf": 65.0,
        "tutti_vhb_chf": 70.0,
        "reasoning": "Beliebte ergonomische Maus",
        "ricardo_title": "Logitech MX Master 3 Bluetooth Maus",
        "ricardo_description": "Top Zustand.\\n\\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.",
        "ricardo_condition": "gebraucht",
        "tutti_title": "Logitech MX Master 3 Maus schnurlos",
        "tutti_category": "Computer & Zubehör > Mäuse",
        "tutti_description": "Funktioniert einwandfrei.\\n\\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.",
        "tutti_condition": "gebraucht"
    }
    
    with patch("backend.services.ai_service.AIService._call_gemini", new_callable=AsyncMock) as mock_gemini:
        import json
        mock_gemini.return_value = json.dumps(mock_ai_response)
        
        with patch("backend.services.ebay_service.EbayService.fetch_sold_stats", new_callable=AsyncMock) as mock_ebay:
            mock_ebay.return_value = EbaySoldStats(
                query="Logitech MX Master 3",
                sample_count=5,
                median_eur=60.0,
                median_chf=56.4,
            )
            
            res_analyze = client.post(f"/api/drafts/{draft_id}/analyze")
            assert res_analyze.status_code == 200
            analyzed = res_analyze.json()
            assert analyzed["status"] == DraftStatus.READY
            assert analyzed["identified_product"] == "Logitech MX Master 3"
            assert analyzed["price_analysis"]["ricardo_start_chf"] == 40.0
            assert analyzed["price_analysis"]["verification_links"]["ebay_sold_url"] is not None
            
    # 7. PUT /api/drafts/{id} (manual edit with Ricardo title > 60 chars)
    analyzed["ricardo"]["title"] = "X" * 75
    analyzed["tutti"]["title"] = "Y" * 95
    analyzed["ebay_de"]["title"] = "E" * 95
    analyzed["kleinanzeigen"]["title"] = "K" * 80
    res_put = client.put(f"/api/drafts/{draft_id}", json=analyzed)
    assert res_put.status_code == 200
    saved = res_put.json()
    assert len(saved["ricardo"]["title"]) <= 60
    assert len(saved["tutti"]["title"]) <= 80
    assert len(saved["ebay_de"]["title"]) <= 80
    assert len(saved["kleinanzeigen"]["title"]) <= 65
    
    # 8. DELETE /api/drafts/{id}
    res_del = client.delete(f"/api/drafts/{draft_id}")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True
    
    # Verify 404 after deletion
    res_get_deleted = client.get(f"/api/drafts/{draft_id}")
    assert res_get_deleted.status_code == 404


def test_dashboard_static_html_served_and_contains_required_elements(test_app):
    client = TestClient(test_app)
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    
    required_ids = [
        "btn-new-draft",
        "dropzone",
        "btn-analyze",
        "ricardo-title",
        "tutti-title",
        "verification-links",
        "ebay-de-title",
        "kleinanzeigen-title",
        "ebay-de-description",
        "kleinanzeigen-description",
        "de-shipping-preset",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html or f"id='{element_id}'" in html, f"Missing #{element_id} in HTML"


def test_system_config_and_invalid_api_key_defensive_handling(test_app):
    client = TestClient(test_app)
    
    # 1. GET /api/config
    res_cfg = client.get("/api/config")
    assert res_cfg.status_code == 200
    cfg_data = res_cfg.json()
    assert "gemini_api_key_configured" in cfg_data
    assert "gemini_model" in cfg_data
    
    # 2. POST /api/config with a new key
    res_update = client.post("/api/config", json={"gemini_api_key": "AIzaSyTestValidLengthKey12345"})
    assert res_update.status_code == 200
    updated_cfg = res_update.json()
    assert updated_cfg["gemini_api_key_configured"] is True
    assert "AIza" in updated_cfg["masked_key"]
    
    # 3. Create a draft and test defensive handling when Gemini raises an invalid key error
    res_create = client.post("/api/drafts", json={"user_notes": "Test Article"})
    draft_id = res_create.json()["id"]
    
    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=Exception("API_KEY_INVALID: API key not valid")):
        res_analyze = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res_analyze.status_code == 400
        assert "API-Key" in res_analyze.json()["detail"]
