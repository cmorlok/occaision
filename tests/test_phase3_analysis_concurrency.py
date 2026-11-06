import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.models import Draft, DraftStatus
from backend.services.image_service import ImageService
from backend.storage import StorageService


def test_user_edits_preserved_during_analysis(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    draft = storage.create_draft(user_notes="Vintage Lamp")
    draft_id = draft.id

    async def mock_gemini_analysis(*args, **kwargs):
        # Simulate user saving custom Ricardo description while Gemini is analyzing in background
        current = storage.get_draft(draft_id)
        current.ricardo.description = "User edited this custom description mid-analysis."
        current.ricardo.title = "User Custom Ricardo Title"
        storage.update_draft(current)

        # AI returns generated listings
        analyzed = current.model_copy(deep=True)
        analyzed.identified_product = "Artemide Tolomeo Lamp"
        analyzed.ricardo.description = "AI Generated Ricardo Description (should be discarded)"
        analyzed.ricardo.title = "AI Generated Ricardo Title (should be discarded)"
        analyzed.tutti.title = "AI Generated Tutti Title (should be preserved)"
        analyzed.tutti.description = "AI Generated Tutti Description (should be preserved)"
        analyzed.ebay_de.title = "AI Generated eBay Title (should be preserved)"
        analyzed.status = DraftStatus.READY
        return analyzed

    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=mock_gemini_analysis):
        res = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res.status_code == 200
        saved = res.json()

        # User modifications must be preserved
        assert saved["ricardo"]["description"] == "User edited this custom description mid-analysis."
        assert saved["ricardo"]["title"] == "User Custom Ricardo Title"

        # AI modifications to untouched fields must be merged
        assert saved["tutti"]["title"] == "AI Generated Tutti Title (should be preserved)"
        assert saved["tutti"]["description"] == "AI Generated Tutti Description (should be preserved)"
        assert saved["ebay_de"]["title"] == "AI Generated eBay Title (should be preserved)"
        assert saved["identified_product"] == "Artemide Tolomeo Lamp"


def test_concurrent_duplicate_analysis_rejected(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    draft = storage.create_draft(user_notes="Concurrent Test Item")
    draft_id = draft.id

    async def blocking_gemini(*args, **kwargs):
        # Try triggering second analysis while first is active
        res_dup = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res_dup.status_code == 409
        assert "läuft bereits" in res_dup.json()["detail"]
        return draft

    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=blocking_gemini):
        res = client.post(f"/api/drafts/{draft_id}/analyze")
        assert res.status_code == 200


def test_analysis_timeout_returns_504(temp_data_dir: Path):
    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)
    client = TestClient(app)

    draft = storage.create_draft(user_notes="Slow analysis test")

    async def slow_analysis(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=slow_analysis):
        res = client.post(f"/api/drafts/{draft.id}/analyze")
        assert res.status_code == 504
        assert "Timeout" in res.json()["detail"]


@pytest.mark.asyncio
async def test_global_analysis_semaphore_throttles_concurrency(temp_data_dir: Path):
    from httpx import ASGITransport, AsyncClient

    test_settings = Settings(data_dir=temp_data_dir, require_auth=False)
    storage = StorageService(data_dir=temp_data_dir)
    image_service = ImageService(data_dir=temp_data_dir)
    app = create_app(settings=test_settings, storage_service=storage, image_service=image_service)

    d1 = storage.create_draft(user_notes="Draft 1")
    d2 = storage.create_draft(user_notes="Draft 2")
    d3 = storage.create_draft(user_notes="Draft 3")

    concurrent_active = 0
    max_observed_concurrent = 0

    async def mock_analyzing(draft, *args, **kwargs):
        nonlocal concurrent_active, max_observed_concurrent
        concurrent_active += 1
        max_observed_concurrent = max(max_observed_concurrent, concurrent_active)
        await asyncio.sleep(0.05)
        concurrent_active -= 1
        return draft

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        with patch("backend.services.ai_service.AIService.analyze_draft", side_effect=mock_analyzing):
            r1, r2, r3 = await asyncio.gather(
                client.post(f"/api/drafts/{d1.id}/analyze"),
                client.post(f"/api/drafts/{d2.id}/analyze"),
                client.post(f"/api/drafts/{d3.id}/analyze"),
            )
            assert r1.status_code == 200
            assert r2.status_code == 200
            assert r3.status_code == 200

    assert max_observed_concurrent <= 2

