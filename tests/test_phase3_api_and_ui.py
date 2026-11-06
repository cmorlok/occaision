import io
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

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
    analyzed["tutti"]["description"] = "Z" * 5000
    analyzed["ebay_de"]["title"] = "E" * 95
    analyzed["kleinanzeigen"]["title"] = "K" * 80
    res_put = client.put(f"/api/drafts/{draft_id}", json=analyzed)
    assert res_put.status_code == 200
    saved = res_put.json()
    assert len(saved["ricardo"]["title"]) <= 60
    assert len(saved["tutti"]["title"]) <= 60
    assert len(saved["tutti"]["description"]) <= 4000
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
        "product-name",
        "user-notes",
        "btn-scrape-extension",
        "btn-analyze",
        "price-ebay-median",
        "price-kleinanzeigen-median",
        "price-idealo-median",
        "price-ricardo-median",
        "price-toppreise-median",
        "price-digitec-median",
        "ricardo-title",
        "tutti-title",
        "verification-links",
        "ebay-de-title",
        "kleinanzeigen-title",
        "ebay-de-description",
        "kleinanzeigen-description",
        "de-shipping-preset",
        "source-box-ebay_de_sold",
        "source-box-kleinanzeigen",
        "source-box-idealo",
        "source-box-ricardo",
        "source-box-toppreise",
        "source-box-digitec",
        "source-box-tutti",
        "link-tutti",
        "cfg-src-ebay_de_sold",
        "cfg-src-kleinanzeigen",
        "cfg-src-idealo",
        "cfg-src-ricardo",
        "cfg-src-toppreise",
        "cfg-src-digitec",
        "cfg-src-tutti",
        "cfg-keep-tabs-open",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in html or f"id='{element_id}'" in html, f"Missing #{element_id} in HTML"


def test_system_config_and_invalid_api_key_defensive_handling(test_app):
    client = TestClient(test_app)

    # 1. GET /api/config & GET /api/models
    res_cfg = client.get("/api/config")
    assert res_cfg.status_code == 200
    cfg_data = res_cfg.json()
    assert "gemini_api_key_configured" in cfg_data
    assert "gemini_model" in cfg_data
    assert "enable_search_grounding" in cfg_data
    assert "available_models" in cfg_data
    assert len(cfg_data["available_models"]) > 0
    assert any("3.8-flash" in m["id"] for m in cfg_data["available_models"])

    res_models = client.get("/api/models")
    assert res_models.status_code == 200
    models_data = res_models.json()
    assert len(models_data) > 0

    # 2. POST /api/config with a new key and disable search grounding and custom exchange rate
    res_update = client.post(
        "/api/config",
        json={
            "gemini_api_key": "AIzaSyTestValidLengthKey12345",
            "enable_search_grounding": False,
            "eur_to_chf_rate": 0.96,
        },
    )
    assert res_update.status_code == 200
    updated_cfg = res_update.json()
    assert updated_cfg["gemini_api_key_configured"] is True
    assert updated_cfg["enable_search_grounding"] is False
    assert updated_cfg["eur_to_chf_rate"] == 0.96
    assert "AIza" in updated_cfg["masked_key"]

    # 3. Create a draft and test defensive handling when Gemini raises an invalid key error
    res_create = client.post("/api/drafts", json={"user_notes": "Test Article"})
    draft_id = res_create.json()["id"]

    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=Exception("API_KEY_INVALID: API key not valid")):
        res_analyze = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res_analyze.status_code == 400
        assert "API-Key" in res_analyze.json()["detail"]

    # 4. Test defensive handling when Gemini raises 429 RESOURCE_EXHAUSTED
    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=Exception("429 RESOURCE_EXHAUSTED: You exceeded your current quota")):
        res_429 = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res_429.status_code == 429
        assert "Quota-Limit" in res_429.json()["detail"]
        assert "Search Grounding" in res_429.json()["detail"]


def test_analyze_endpoint_skips_backend_ebay_when_extension_prices_present(test_app):
    client = TestClient(test_app)

    res_create = client.post(
        "/api/drafts",
        json={
            "identified_product": "HP Color LaserJet Pro MFP 4302fdw",
            "user_notes": "Fast wie neu, inkl. OVP",
        },
    )
    assert res_create.status_code == 200
    draft = res_create.json()
    draft_id = draft["id"]
    assert draft["identified_product"] == "HP Color LaserJet Pro MFP 4302fdw"
    assert draft["user_notes"] == "Fast wie neu, inkl. OVP"

    # Simulate Step 2: Extension saves scraped prices for all 6 sources
    draft["price_analysis"]["prices_fetched_via_extension"] = True
    draft["price_analysis"]["market_sources"] = {
        "ebay_de_sold": {
            "source_id": "ebay_de_sold",
            "label": "eBay DE (Gebraucht & Beendet)",
            "currency": "EUR",
            "sample_count": 4,
            "min_price": 240.0,
            "max_price": 310.0,
            "median_price": 275.0,
            "median_chf": 258.5,
            "url": "https://www.ebay.de/sch/i.html?_nkw=HP+4302fdw&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000",
            "method": "fetch",
        },
        "kleinanzeigen": {
            "source_id": "kleinanzeigen",
            "label": "Kleinanzeigen.de Suche",
            "currency": "EUR",
            "sample_count": 6,
            "min_price": 250.0,
            "max_price": 340.0,
            "median_price": 290.0,
            "median_chf": 272.6,
            "url": "https://www.kleinanzeigen.de/s-HP+4302fdw/k0",
            "method": "fetch",
        },
        "idealo": {
            "source_id": "idealo",
            "label": "Idealo.de Neupreis",
            "currency": "EUR",
            "sample_count": 3,
            "min_price": 439.0,
            "max_price": 479.0,
            "median_price": 449.0,
            "median_chf": 422.06,
            "url": "https://www.idealo.de",
            "method": "tab",
        },
    }
    res_put = client.put(f"/api/drafts/{draft_id}", json=draft)
    assert res_put.status_code == 200

    mock_ai_response = {
        "identified_product": "HP Color LaserJet Pro MFP 4302fdw",
        "missing_photo_hints": [],
        "ch_new_price_chf": 415.0,
        "de_new_price_eur": 449.0,
        "ricardo_start_chf": 210.0,
        "ricardo_buynow_chf": 270.0,
        "tutti_vhb_chf": 280.0,
        "ebay_start_eur": 200.0,
        "ebay_buynow_eur": 270.0,
        "kleinanzeigen_vb_eur": 285.0,
        "reasoning": "Preise aus Extension-Daten abgeleitet",
        "ricardo_title": "HP Color LaserJet Pro MFP 4302fdw Farblaser",
        "ricardo_description": "Top Zustand.",
        "ricardo_condition": "wie_neu",
        "tutti_title": "HP Color LaserJet Pro MFP 4302fdw Drucker",
        "tutti_category": "Büro",
        "tutti_description": "Sehr guter Zustand.",
        "tutti_condition": "wie_neu",
    }

    import json
    with patch("backend.services.ai_service.AIService._call_gemini", new_callable=AsyncMock) as mock_gemini:
        mock_gemini.return_value = json.dumps(mock_ai_response)
        res_analyze = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res_analyze.status_code == 200
        analyzed = res_analyze.json()
        assert analyzed["price_analysis"]["prices_fetched_via_extension"] is True
        assert "ebay_de_sold" in analyzed["price_analysis"]["market_sources"]
        assert analyzed["price_analysis"]["ebay_stats"]["median_eur"] == 275.0


def test_analyze_skips_ebay_and_filters_sources_when_disabled_in_settings(test_app):
    client = TestClient(test_app)

    # 1. Update settings to disable ebay_de_sold and idealo and enable keep_tabs_open_after_search
    res_settings = client.get("/api/settings")
    assert res_settings.status_code == 200
    settings_data = res_settings.json()
    assert settings_data["keep_tabs_open_after_search"] is False
    settings_data["enabled_price_sources"] = ["kleinanzeigen", "toppreise"]
    settings_data["keep_tabs_open_after_search"] = True
    res_update = client.put("/api/settings", json=settings_data)
    assert res_update.status_code == 200
    assert res_update.json()["enabled_price_sources"] == ["kleinanzeigen", "toppreise"]
    assert res_update.json()["keep_tabs_open_after_search"] is True

    # 2. Create draft with product name and 3 extension market sources
    res_create = client.post(
        "/api/drafts",
        json={"user_notes": "Test", "identified_product": "Bose QC45"}
    )
    assert res_create.status_code == 200
    draft = res_create.json()
    draft_id = draft["id"]

    draft["price_analysis"]["prices_fetched_via_extension"] = True
    draft["price_analysis"]["market_sources"] = {
        "ebay_de_sold": {
            "source_id": "ebay_de_sold",
            "label": "eBay DE (Gebraucht & Beendet)",
            "currency": "EUR",
            "sample_count": 4,
            "min_price": 100.0,
            "max_price": 150.0,
            "median_price": 120.0,
            "median_chf": 112.8,
            "url": "https://www.ebay.de",
            "method": "extension",
        },
        "kleinanzeigen": {
            "source_id": "kleinanzeigen",
            "label": "Kleinanzeigen.de Suche",
            "currency": "EUR",
            "sample_count": 6,
            "min_price": 110.0,
            "max_price": 160.0,
            "median_price": 130.0,
            "median_chf": 122.2,
            "url": "https://www.kleinanzeigen.de",
            "method": "extension",
        },
        "toppreise": {
            "source_id": "toppreise",
            "label": "Toppreise.ch Neupreis",
            "currency": "CHF",
            "sample_count": 2,
            "min_price": 240.0,
            "max_price": 260.0,
            "median_price": 250.0,
            "median_chf": 250.0,
            "url": "https://www.toppreise.ch",
            "method": "tab",
        },
    }
    client.put(f"/api/drafts/{draft_id}", json=draft)

    mock_ai_resp = {
        "identified_product": "Bose QC45",
        "missing_photo_hints": [],
        "ricardo_start_chf": 80.0,
        "ricardo_buynow_chf": 130.0,
        "tutti_vhb_chf": 140.0,
        "ebay_start_eur": 75.0,
        "ebay_buynow_eur": 125.0,
        "kleinanzeigen_vb_eur": 135.0,
        "reasoning": "Preise ohne eBay",
        "ricardo_title": "Bose QC45 Kopfhörer",
        "ricardo_description": "Top Zustand",
        "tutti_title": "Bose QC45",
        "tutti_category": "Audio",
        "tutti_description": "Top Zustand",
    }

    import json
    with patch("backend.services.ai_service.AIService._call_gemini", new_callable=AsyncMock) as mock_gemini:
        mock_gemini.return_value = json.dumps(mock_ai_resp)
        res_analyze = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res_analyze.status_code == 200
        analyzed = res_analyze.json()
        sources = analyzed["price_analysis"]["market_sources"]
        assert "kleinanzeigen" in sources
        assert "toppreise" in sources
        # Disabled sources must not be in analyzed market_sources
        assert "ebay_de_sold" not in sources
        assert analyzed["price_analysis"]["ebay_stats"] is None


def test_drafts_export_and_import_api(test_app):
    client = TestClient(test_app)

    # 1. Create a draft
    create_res = client.post("/api/drafts", json={"user_notes": "API Export Note"})
    assert create_res.status_code == 200
    draft_id = create_res.json()["id"]

    # 2. Export drafts
    export_res = client.get("/api/drafts/export")
    assert export_res.status_code == 200
    assert "attachment" in export_res.headers.get("content-disposition", "")
    backup_data = export_res.json()
    assert backup_data["version"] == 1
    assert any(d["id"] == draft_id for d in backup_data["drafts"])

    # 3. Import via JSON payload
    import_res = client.post("/api/drafts/import", json=backup_data)
    assert import_res.status_code == 200
    assert import_res.json()["imported_count"] >= 1

    # 4. Import via multipart file upload
    import json
    file_bytes = json.dumps(backup_data).encode("utf-8")
    files = {"file": ("backup.json", file_bytes, "application/json")}
    file_res = client.post("/api/drafts/import", files=files)
    assert file_res.status_code == 200
    assert file_res.json()["imported_count"] >= 1

    # 5. Invalid JSON import
    bad_res = client.post("/api/drafts/import", json={"drafts": "invalid_type"})
    assert bad_res.status_code == 400


def test_frontend_api_client_contract():
    node_script = """
    const api = require('./frontend/api.js');
    const recordedCalls = [];

    global.fetch = async (url, options = {}) => {
      recordedCalls.push({ url, options });

      if (url === '/api/error-test') {
        return { ok: false, status: 500 };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, data: 'mock-response' })
      };
    };

    (async () => {
      // 1. Auth pairing
      await api.pairAuth();
      const call1 = recordedCalls[recordedCalls.length - 1];
      if (call1.url !== '/api/auth/pair' || call1.options.method !== 'POST') {
        throw new Error('pairAuth contract failed');
      }

      // 2. Config & Settings
      await api.getConfig();
      if (recordedCalls[recordedCalls.length - 1].url !== '/api/config') throw new Error('getConfig failed');

      await api.updateConfig({ key: 'val' });
      const call3 = recordedCalls[recordedCalls.length - 1];
      if (call3.url !== '/api/config' || call3.options.method !== 'POST' || call3.options.body !== '{"key":"val"}') {
        throw new Error('updateConfig contract failed');
      }

      await api.getSettings();
      if (recordedCalls[recordedCalls.length - 1].url !== '/api/settings') throw new Error('getSettings failed');

      await api.updateSettings({ preset: 1 });
      const call5 = recordedCalls[recordedCalls.length - 1];
      if (call5.url !== '/api/settings' || call5.options.method !== 'PUT') throw new Error('updateSettings failed');

      // 3. Draft operations
      await api.listDrafts();
      if (recordedCalls[recordedCalls.length - 1].url !== '/api/drafts') throw new Error('listDrafts failed');

      await api.getDraft('draft 1');
      if (recordedCalls[recordedCalls.length - 1].url !== '/api/drafts/draft%201') throw new Error('getDraft encoding failed');

      await api.createDraft({ user_notes: 'note' });
      const call8 = recordedCalls[recordedCalls.length - 1];
      if (call8.url !== '/api/drafts' || call8.options.method !== 'POST') throw new Error('createDraft failed');

      await api.updateDraft({ id: 'd-1', notes: 'updated' });
      const call9 = recordedCalls[recordedCalls.length - 1];
      if (call9.url !== '/api/drafts/d-1' || call9.options.method !== 'PUT') throw new Error('updateDraft failed');

      await api.deleteDraft('d-1');
      const call10 = recordedCalls[recordedCalls.length - 1];
      if (call10.url !== '/api/drafts/d-1' || call10.options.method !== 'DELETE') throw new Error('deleteDraft failed');

      await api.analyzeDraft('d-1');
      const call11 = recordedCalls[recordedCalls.length - 1];
      if (call11.url !== '/api/drafts/d-1/analyze' || call11.options.method !== 'POST') throw new Error('analyzeDraft failed');

      // 4. Image operations
      const mockForm = { dummy: true };
      await api.uploadImages('d-1', mockForm);
      const call12 = recordedCalls[recordedCalls.length - 1];
      if (call12.url !== '/api/drafts/d-1/images' || call12.options.method !== 'POST' || call12.options.body !== mockForm) {
        throw new Error('uploadImages failed');
      }

      await api.deleteImage('d-1', 'img 1');
      const call13 = recordedCalls[recordedCalls.length - 1];
      if (call13.url !== '/api/drafts/d-1/images/img%201' || call13.options.method !== 'DELETE') throw new Error('deleteImage failed');

      await api.setVariant('d-1', 'img-1', 'white_bg');
      const call14 = recordedCalls[recordedCalls.length - 1];
      if (call14.url !== '/api/drafts/d-1/images/img-1' || call14.options.method !== 'PATCH' || call14.options.body !== '{"active_mode":"white_bg"}') {
        throw new Error('setVariant failed');
      }

      // 5. Backup operations
      await api.exportDrafts();
      const call15 = recordedCalls[recordedCalls.length - 1];
      if (call15.url !== '/api/drafts/export') throw new Error('exportDrafts failed');

      await api.importDrafts(mockForm);
      const call16 = recordedCalls[recordedCalls.length - 1];
      if (call16.url !== '/api/drafts/import' || call16.options.method !== 'POST' || call16.options.body !== mockForm) {
        throw new Error('importDrafts failed');
      }

      // 6. Error handling rejection verification
      global.fetch = async () => ({ ok: false, status: 404 });
      let threw = false;
      try {
        await api.getDraft('missing');
      } catch (err) {
        threw = true;
        if (!err.message.includes('404')) throw new Error('Expected 404 in error message, got: ' + err.message);
      }
      if (!threw) throw new Error('Expected getDraft to throw on 404');
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Frontend API client test failed: {res.stderr}"


def test_analyze_draft_concurrency_guard(test_app):
    client = TestClient(test_app)
    res_create = client.post("/api/drafts", json={"user_notes": "Concurrency Test"})
    assert res_create.status_code == 200
    draft_id = res_create.json()["id"]

    import asyncio
    import time
    from concurrent.futures import ThreadPoolExecutor

    real_draft = Draft.model_validate(res_create.json())
    real_draft.status = DraftStatus.READY

    async def slow_analyze(*args, **kwargs):
        await asyncio.sleep(0.3)
        return real_draft

    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=slow_analyze):
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut1 = executor.submit(lambda: client.post(f"/api/drafts/{draft_id}/analyze"))
            time.sleep(0.05)
            fut2 = executor.submit(lambda: client.post(f"/api/drafts/{draft_id}/analyze"))

            res1 = fut1.result()
            res2 = fut2.result()

        statuses = {res1.status_code, res2.status_code}
        assert 200 in statuses
        assert 409 in statuses

        conflict_res = res1 if res1.status_code == 409 else res2
        assert "Analyse für diesen Entwurf läuft bereits" in conflict_res.json()["detail"]

    # After completion, subsequent request can acquire lock and succeed
    with patch("backend.services.ai_service.AIService.analyze_draft", return_value=real_draft):
        res3 = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res3.status_code == 200


def test_frontend_upload_validation():
    node_script = """
    const { validateUploadFiles, MAX_UPLOAD_FILES, MAX_FILE_BYTES } = require('./frontend/app.js');

    // 1. Empty files
    const resEmpty = validateUploadFiles([]);
    if (resEmpty.valid !== false || !resEmpty.error.includes('Keine Dateien')) {
      throw new Error('Empty files validation failed: ' + JSON.stringify(resEmpty));
    }

    // 2. Excess files (>15)
    const excessFiles = Array(16).fill({ name: 'photo.jpg', size: 1000, type: 'image/jpeg' });
    const resExcess = validateUploadFiles(excessFiles);
    if (resExcess.valid !== false || !resExcess.error.includes('Maximal 15 Bilder')) {
      throw new Error('Excess files validation failed: ' + JSON.stringify(resExcess));
    }

    // 3. Unsupported extension
    const invalidExtFiles = [{ name: 'payload.exe', size: 1000, type: 'application/octet-stream' }];
    const resInvalidExt = validateUploadFiles(invalidExtFiles);
    if (resInvalidExt.valid !== false || !resInvalidExt.error.includes('Ungültiges Dateiformat')) {
      throw new Error('Invalid extension validation failed: ' + JSON.stringify(resInvalidExt));
    }

    // 4. File exceeding 25MB
    const oversizedFiles = [{ name: 'giant.png', size: 26 * 1024 * 1024, type: 'image/png' }];
    const resOversized = validateUploadFiles(oversizedFiles);
    if (resOversized.valid !== false || !resOversized.error.includes('25 MB')) {
      throw new Error('Oversized validation failed: ' + JSON.stringify(resOversized));
    }

    // 5. Valid files batch
    const validBatch = [
      { name: 'photo1.JPG', size: 2 * 1024 * 1024, type: 'image/jpeg' },
      { name: 'photo2.webp', size: 500 * 1024, type: 'image/webp' },
      { name: 'photo3.heic', size: 10 * 1024 * 1024, type: 'image/heic' }
    ];
    const resValid = validateUploadFiles(validBatch);
    if (resValid.valid !== true) {
      throw new Error('Valid batch unexpectedly failed: ' + JSON.stringify(resValid));
    }
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Frontend upload validation failed: {res.stderr}"


def test_frontend_scripts_browser_coexistence():
    """Verify that api.js, toast.js, and app.js evaluate cleanly in a shared browser-like global context
    without identifier redeclaration SyntaxErrors (e.g. redeclaration of const api) or recursive stack overflows."""
    node_script = """
    const vm = require('vm');
    const fs = require('fs');

    const createdElements = [];
    const ctx = vm.createContext({
      console: console,
      setTimeout: setTimeout,
      clearTimeout: clearTimeout,
      document: {
        getElementById: (id) => ({
          id,
          appendChild: (child) => { createdElements.push(child); },
          addEventListener: () => {},
          classList: { add: () => {}, remove: () => {} },
          style: {},
        }),
        createElement: (tag) => ({
          tag,
          className: '',
          textContent: '',
          setAttribute: () => {},
          appendChild: (c) => {},
          classList: { add: () => {}, remove: () => {} },
          style: {},
          isConnected: true,
          remove: () => {},
        }),
        addEventListener: () => {},
      },
    });
    ctx.window = ctx;
    ctx.addEventListener = () => {};

    // 1. Load api.js
    const apiCode = fs.readFileSync('./frontend/api.js', 'utf8');
    vm.runInContext(apiCode, ctx);
    if (!ctx.window.api || typeof ctx.window.api.listDrafts !== 'function') {
      throw new Error('window.api not initialized properly by api.js');
    }

    // 2. Load toast.js
    const toastCode = fs.readFileSync('./frontend/toast.js', 'utf8');
    vm.runInContext(toastCode, ctx);
    if (typeof ctx.window.showToast !== 'function') {
      throw new Error('window.showToast not initialized properly by toast.js');
    }

    // 3. Load app.js in the exact same shared global context
    const appCode = fs.readFileSync('./frontend/app.js', 'utf8');
    vm.runInContext(appCode, ctx);

    // 4. Verify toast execution inside app.js does not trigger recursion or call stack overflow
    const toastResult = ctx.showToast('Test Toast Notification', 'success');
    if (!toastResult || createdElements.length === 0) {
      throw new Error('showToast did not create or return a toast element');
    }
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Frontend scripts browser coexistence failed: {res.stderr}"








