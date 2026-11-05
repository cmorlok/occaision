import json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import pytest

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
