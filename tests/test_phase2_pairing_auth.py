import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.services.image_service import ImageService
from backend.storage import StorageService


def test_health_endpoints_do_not_issue_auth_cookies(temp_data_dir: Path):
    test_settings = Settings(
        data_dir=temp_data_dir,
        gemini_api_key="test_key",
        require_auth=True,
    )
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    # 1. Access /api/health - must be accessible without auth and set NO auth cookie
    res_api_health = client.get("/api/health")
    assert res_api_health.status_code == 200
    assert "occaision_token" not in res_api_health.cookies
    assert "set-cookie" not in [k.lower() for k in res_api_health.headers.keys()]

    # 2. Access /health alias - must also set NO auth cookie
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert "occaision_token" not in res_health.cookies
    assert "set-cookie" not in [k.lower() for k in res_health.headers.keys()]

    # 3. Subsequent request to protected endpoint must still fail with 401
    res_drafts = client.get("/api/drafts")
    assert res_drafts.status_code == 401


def test_pairing_origin_validation(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=True)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    # 1. Missing Origin header must be rejected
    res_no_origin = client.post("/api/auth/pair", json={"pairing_code": "123456"})
    assert res_no_origin.status_code == 403
    assert "Untrusted origin" in res_no_origin.json()["detail"]

    # 2. Untrusted domains rejected
    res_untrusted = client.post(
        "/api/auth/pair",
        headers={"Origin": "https://malicious-site.com"},
        json={"pairing_code": "123456"},
    )
    assert res_untrusted.status_code == 403

    # 3. Substring / prefix-matching attacks on localhost / 127.0.0.1 must be rejected
    res_prefix_127 = client.post(
        "/api/auth/pair",
        headers={"Origin": "http://127.0.0.1.attacker.com:8000"},
        json={"pairing_code": "123456"},
    )
    assert res_prefix_127.status_code == 403

    res_prefix_local = client.post(
        "/api/auth/pair",
        headers={"Origin": "http://localhost.attacker.com"},
        json={"pairing_code": "123456"},
    )
    assert res_prefix_local.status_code == 403


def test_pairing_code_handshake_lifecycle(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=True)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    auth_token = (temp_data_dir / "auth_token.txt").read_text(encoding="utf-8").strip()

    # Client A: Authenticated user dashboard
    dashboard_client = TestClient(app)
    dashboard_client.cookies.set("occaision_token", auth_token)

    # Client B: Unauthenticated extension background script
    extension_client = TestClient(app)

    # 1. Unauthenticated request for pairing code must fail with 401
    res_unauth_code = extension_client.post("/api/auth/pairing-code")
    assert res_unauth_code.status_code == 401

    # 2. Authenticated user requests a pairing code
    res_code = dashboard_client.post("/api/auth/pairing-code")
    assert res_code.status_code == 200
    code_data = res_code.json()
    assert code_data["ok"] is True
    assert "pairing_code" in code_data
    pin = code_data["pairing_code"]
    assert len(pin) == 6
    assert pin.isdigit()

    # 3. Extension attempts pairing with invalid code
    trusted_origin = {"Origin": "moz-extension://a8e747b9-b82b-4781-a9e9-e39542a2ca4c"}
    res_wrong_code = extension_client.post(
        "/api/auth/pair",
        headers=trusted_origin,
        json={"pairing_code": "000000"},
    )
    assert res_wrong_code.status_code == 401
    assert "Invalid or expired" in res_wrong_code.json()["detail"]

    # 4. Extension pairs successfully with valid code
    res_pair = extension_client.post(
        "/api/auth/pair",
        headers=trusted_origin,
        json={"pairing_code": pin},
    )
    assert res_pair.status_code == 200
    pair_data = res_pair.json()
    assert pair_data["ok"] is True
    assert pair_data["token"] == auth_token

    # 5. Single-use enforcement: Replay of same pairing code must fail with 401
    res_replay = extension_client.post(
        "/api/auth/pair",
        headers=trusted_origin,
        json={"pairing_code": pin},
    )
    assert res_replay.status_code == 401


def test_pairing_code_expiration(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=True)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    auth_token = (temp_data_dir / "auth_token.txt").read_text(encoding="utf-8").strip()

    dashboard_client = TestClient(app)
    dashboard_client.cookies.set("occaision_token", auth_token)
    extension_client = TestClient(app)

    res_code = dashboard_client.post("/api/auth/pairing-code")
    pin = res_code.json()["pairing_code"]

    # Advance time by 61 seconds (TTL is 60s)
    future_time = time.time() + 65.0
    with patch("time.time", return_value=future_time):
        res_expired = extension_client.post(
            "/api/auth/pair",
            headers={"Origin": "http://127.0.0.1:8000"},
            json={"pairing_code": pin},
        )
        assert res_expired.status_code == 401
        assert "Invalid or expired" in res_expired.json()["detail"]
