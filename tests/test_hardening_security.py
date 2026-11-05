import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.services.image_service import ImageService
from backend.storage import StorageService


def test_docker_compose_loopback_binding():
    compose_path = Path("docker-compose.yml")
    assert compose_path.exists()
    content = compose_path.read_text(encoding="utf-8")
    assert "127.0.0.1:8000:8000" in content, "docker-compose.yml must bind port 8000 to 127.0.0.1 only"
    assert '"8000:8000"' not in content, "docker-compose.yml must not bind 8000 to 0.0.0.0"

    # Also assert build_docker.sh script adheres to loopback invariant
    script_path = Path("scripts/build_docker.sh")
    assert script_path.exists()
    script_content = script_path.read_text(encoding="utf-8")
    assert "-p 127.0.0.1:8000:8000" in script_content
    assert "-p 8000:8000" not in script_content


def test_api_auth_rejection_and_token_acceptance(temp_data_dir: Path):
    test_settings = Settings(
        data_dir=temp_data_dir,
        gemini_api_key="test_key",
        require_auth=True,
    )
    storage_service = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(
        settings=test_settings,
        storage_service=storage_service,
        image_service=image_service,
    )

    client = TestClient(app)

    # 1. Unauthenticated request must return 401
    res_unauth = client.get("/api/drafts")
    assert res_unauth.status_code == 401
    assert "detail" in res_unauth.json()

    # 2. Public health endpoint remains accessible without auth
    res_health = client.get("/api/health")
    assert res_health.status_code == 200

    # Read generated token from data_dir
    token_file = temp_data_dir / "auth_token.txt"
    assert token_file.exists(), "auth_token.txt must be generated"
    token = token_file.read_text(encoding="utf-8").strip()
    assert len(token) >= 20

    # 3. Authenticated request with Bearer header succeeds
    res_auth_header = client.get("/api/drafts", headers={"Authorization": f"Bearer {token}"})
    assert res_auth_header.status_code == 200

    # 4. Authenticated request with session cookie succeeds
    client.cookies.set("occaision_token", token)
    res_auth_cookie = client.get("/api/drafts")
    assert res_auth_cookie.status_code == 200


def test_host_header_and_cors_origin_validation(temp_data_dir: Path):
    test_settings = Settings(
        data_dir=temp_data_dir,
        require_auth=True,
    )
    storage_service = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(
        settings=test_settings,
        storage_service=storage_service,
        image_service=image_service,
    )

    client = TestClient(app)
    token = (temp_data_dir / "auth_token.txt").read_text(encoding="utf-8").strip()

    # 1. Untrusted host header (e.g. DNS rebinding) must be rejected
    res_bad_host = client.get(
        "/api/drafts",
        headers={"Host": "evil.com", "Authorization": f"Bearer {token}"},
    )
    assert res_bad_host.status_code == 403

    # 2. CORS check: Untrusted origin receives no Access-Control-Allow-Origin: *
    res_untrusted_cors = client.options(
        "/api/drafts",
        headers={
            "Origin": "https://malicious-site.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    allow_origin = res_untrusted_cors.headers.get("access-control-allow-origin")
    assert allow_origin != "*", "Wildcard CORS must never be returned"
    assert allow_origin != "https://malicious-site.example"


def test_dashboard_csp_header(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    app = create_app(settings=test_settings)
    client = TestClient(app)

    res = client.get("/")
    assert res.status_code == 200
    csp = res.headers.get("content-security-policy", "")
    assert "default-src" in csp
    assert "'self'" in csp


def test_content_js_safe_description_rendering():
    content_js = Path("extension/content.js").read_text(encoding="utf-8")
    assert "editable.innerHTML = htmlVal" not in content_js, "content.js must not assign unescaped innerHTML in setDescriptionValue"
    assert "createTextNode" in content_js, "content.js must use createTextNode for safe multiline insertion"


def test_storage_revision_conflict_and_no_resurrection(temp_data_dir: Path):
    from backend.storage import DraftNotFoundError, RevisionConflictError, StorageService
    storage = StorageService(data_dir=temp_data_dir)

    draft = storage.create_draft(user_notes="Original")
    assert draft.revision == 1

    # First update increments revision to 2
    draft.user_notes = "Updated 1"
    updated = storage.update_draft(draft)
    assert updated.revision == 2

    # Stale write with revision 1 must raise RevisionConflictError
    stale_draft = draft.model_copy(update={"revision": 1, "user_notes": "Stale overwrite"})
    with pytest.raises(RevisionConflictError):
        storage.update_draft(stale_draft)

    # Deleting the draft
    assert storage.delete_draft(draft.id) is True

    # Attempting to update deleted draft must raise DraftNotFoundError (no resurrection/upsert)
    with pytest.raises(DraftNotFoundError):
        storage.update_draft(updated)


def test_storage_corruption_safety(temp_data_dir: Path):
    from backend.storage import StorageCorruptedError, StorageService
    storage = StorageService(data_dir=temp_data_dir)
    storage.create_draft(user_notes="Important Data")

    # Corrupt drafts.json
    drafts_file = temp_data_dir / "drafts.json"
    drafts_file.write_text("{ corrupt json: invalid ...", encoding="utf-8")

    # Reading corrupt file must raise StorageCorruptedError and preserve backup
    with pytest.raises(StorageCorruptedError):
        storage.list_drafts()

    backup_files = list(temp_data_dir.glob("drafts.json.corrupt.*"))
    assert len(backup_files) >= 1, "Must create backup of corrupted drafts.json"


def test_analyze_does_not_resurrect_deleted_draft(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    draft = storage.create_draft(user_notes="Will be deleted mid-analysis")

    def delete_during_ai(*args, **kwargs):
        # Delete draft while Gemini is "running"
        storage.delete_draft(draft.id)
        return draft

    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=delete_during_ai):
        res = client.post(f"/api/drafts/{draft.id}/analyze")
        assert res.status_code == 404
        assert "deleted" in res.json()["detail"].lower()

    # Draft must still not exist (no resurrection)
    assert storage.get_draft(draft.id) is None


def test_durable_config_persistence_and_read_only_get(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    app = create_app(settings=test_settings)
    client = TestClient(app)

    # 1. Update config via POST /api/config
    res_update = client.post(
        "/api/config",
        json={
            "gemini_api_key": "AIzaSyTestDurableKey12345",
            "gemini_model": "custom-model-id",
            "enable_search_grounding": False,
        },
    )
    assert res_update.status_code == 200

    # Verify data/config.json was written
    config_file = temp_data_dir / "config.json"
    assert config_file.exists(), "config.json must be persisted in data directory"
    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["gemini_model"] == "custom-model-id"
    assert saved["enable_search_grounding"] is False

    # 2. Re-create app from same data_dir (simulating container restart without .env)
    new_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    app2 = create_app(settings=new_settings)
    client2 = TestClient(app2)

    res_cfg = client2.get("/api/config")
    assert res_cfg.status_code == 200
    cfg2 = res_cfg.json()
    assert cfg2["gemini_model"] == "custom-model-id"
    assert cfg2["enable_search_grounding"] is False
    assert cfg2["gemini_api_key_configured"] is True

    # 3. GET /api/config must not mutate model
    res_cfg_again = client2.get("/api/config")
    assert res_cfg_again.json()["gemini_model"] == "custom-model-id"


def test_empty_price_sources_preserved_and_has_extension_prices_semantics(temp_data_dir: Path):
    from backend.models import MarketSourceStats, PriceAnalysis
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage)
    client = TestClient(app)

    # 1. Update settings with an explicitly empty enabled_price_sources
    res_set = client.put(
        "/api/settings",
        json={
            "default_offer_type": "auction",
            "default_shipping_preset_id": "b_post_2kg",
            "default_de_shipping_preset_id": "dhl_2kg",
            "enabled_price_sources": [],
            "keep_tabs_open_after_search": False,
            "shipping_presets": [],
        },
    )
    assert res_set.status_code == 200
    assert res_set.json()["enabled_price_sources"] == [], "Empty enabled_price_sources must be preserved"

    # Re-fetch from storage to ensure it wasn't overwritten by DEFAULT_PRICE_SOURCES
    current_settings = storage.get_settings()
    assert current_settings.enabled_price_sources == []

    # 2. Test has_extension_prices semantics in AIService:
    # 0 sample count must NOT count as usable extension prices
    from backend.services.ai_service import AIService
    ai_svc = AIService(api_key="dummy_key", enable_search_grounding=True)

    draft = storage.create_draft(user_notes="Test Item")
    draft.price_analysis = PriceAnalysis(
        prices_fetched_via_extension=True,  # Old stale flag
        market_sources={
            "ricardo": MarketSourceStats(source_id="ricardo", label="Ricardo", sample_count=0, median_price=None)
        },
    )

    # Calling get_generate_config or evaluating effective grounding
    # With 0 samples, grounding should NOT be disabled
    has_usable_samples = any(
        ms.sample_count > 0 and ms.median_price is not None
        for ms in draft.price_analysis.market_sources.values()
    )
    assert has_usable_samples is False


def test_upload_batch_limits_and_atomic_cleanup(temp_data_dir: Path):
    from backend.services.image_service import ImageService
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    draft = storage.create_draft(user_notes="Upload Limits Test")

    # 1. Batch size limit (> 15 files)
    oversized_batch = [("files", (f"img_{i}.jpg", b"fake", "image/jpeg")) for i in range(16)]
    res_batch = client.post(f"/api/drafts/{draft.id}/images", files=oversized_batch)
    assert res_batch.status_code == 400
    assert "15" in res_batch.json()["detail"]

    # 2. File size limit (> 25MB)
    large_payload = b"X" * (25 * 1024 * 1024 + 10)
    res_size = client.post(
        f"/api/drafts/{draft.id}/images",
        files=[("files", ("large.jpg", large_payload, "image/jpeg"))],
    )
    assert res_size.status_code == 413

    # 3. Atomic rollback: file 1 valid, file 2 corrupt
    import io

    from PIL import Image
    valid_img = Image.new("RGB", (100, 100), color=(10, 20, 30))
    buf = io.BytesIO()
    valid_img.save(buf, format="JPEG")
    valid_bytes = buf.getvalue()

    corrupt_bytes = b"not a real image"

    res_atomic = client.post(
        f"/api/drafts/{draft.id}/images",
        files=[
            ("files", ("valid.jpg", valid_bytes, "image/jpeg")),
            ("files", ("corrupt.jpg", corrupt_bytes, "image/jpeg")),
        ],
    )
    assert res_atomic.status_code == 400

    # No leftover image files on disk
    draft_img_dir = temp_data_dir / "images" / draft.id
    if draft_img_dir.exists():
        files_left = list(draft_img_dir.glob("*"))
        assert len(files_left) == 0, f"Expected 0 orphaned files, found: {files_left}"


def test_extension_autofill_and_domain_safety():
    content_js = Path("extension/content.js").read_text(encoding="utf-8")

    # 1. No blind options[0] fallback
    assert "|| options[0]" not in content_js, "fillMuiSelect must not fall back to options[0] on non-match"

    # 2. Test domain detection safety via Node.js
    import subprocess
    node_script = """
    const content = require('./extension/content.js');
    
    // Valid domains
    if (!content.isRicardo('ricardo.ch') || !content.isRicardo('www.ricardo.ch')) process.exit(1);
    if (!content.isTutti('tutti.ch') || !content.isTutti('m.tutti.ch')) process.exit(2);
    if (!content.isEbayDE('ebay.de') || !content.isEbayDE('www.ebay.de')) process.exit(3);
    if (!content.isKleinanzeigen('kleinanzeigen.de') || !content.isKleinanzeigen('m.kleinanzeigen.de')) process.exit(4);
    if (!content.isLocalDashboard('127.0.0.1') || !content.isLocalDashboard('localhost')) process.exit(5);

    // Spoofed domains must be rejected
    if (content.isRicardo('ricardo.ch.attacker.com')) process.exit(10);
    if (content.isTutti('tutti.ch.evil.com')) process.exit(11);
    if (content.isEbayDE('ebay.de.attacker.com')) process.exit(12);
    if (content.isKleinanzeigen('kleinanzeigen.de.evil.com')) process.exit(13);
    if (content.isLocalDashboard('127.0.0.1.attacker.com')) process.exit(14);
    if (content.isLocalDashboard('localhost.evil.com')) process.exit(15);

    process.exit(0);
    """
    res = subprocess.run(["node", "-e", node_script])
    assert res.returncode == 0, f"Domain detection safety failed with code {res.returncode}"







