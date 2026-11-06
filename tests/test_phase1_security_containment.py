import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app
from backend.models import (
    Draft,
    DraftImage,
    ImageVariantMode,
    ShippingPreset,
    UpdateDraftRequest,
    validate_identifier,
)
from backend.path_utils import PathTraversalError, resolve_safe_path
from backend.services.image_service import ImageService
from backend.storage import DraftStore


def test_validate_identifier():
    # Valid identifiers
    assert validate_identifier("draft_123") == "draft_123"
    assert validate_identifier("img_abcdef123456") == "img_abcdef123456"
    assert validate_identifier("b_post_2kg") == "b_post_2kg"
    assert validate_identifier("A-Z_0-9") == "A-Z_0-9"

    # Invalid identifiers
    invalid_samples = [
        "../traversal",
        "../../etc/passwd",
        "/absolute/path",
        "",
        "   ",
        "has space",
        "draft/slash",
        "draft\\backslash",
        "has*wildcard",
        "has?question",
        "has[bracket]",
        "x" * 65,  # Exceeds max length
    ]
    for sample in invalid_samples:
        with pytest.raises(ValueError):
            validate_identifier(sample)


def test_model_identifier_validation():
    # Draft id validation
    with pytest.raises(ValueError):
        Draft(
            id="../../bad_draft",
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    # DraftImage id validation
    with pytest.raises(ValueError):
        DraftImage(
            id="../bad_image",
            original_filename="test.jpg",
            width=800,
            height=600,
        )

    # ShippingPreset id validation
    with pytest.raises(ValueError):
        ShippingPreset(
            id="../bad_preset",
            label="Bad Preset",
            cost=5.0,
        )


def test_resolve_safe_path_containment(tmp_path: Path):
    base = tmp_path / "storage"
    base.mkdir(parents=True, exist_ok=True)

    # Valid relative path resolution
    resolved = resolve_safe_path(base, "draft_1", "img_1_optimized.jpg")
    assert resolved == (base / "draft_1" / "img_1_optimized.jpg").resolve()
    assert resolved.is_relative_to(base.resolve())

    # Path traversal rejection
    with pytest.raises(PathTraversalError):
        resolve_safe_path(base, "..")

    with pytest.raises(PathTraversalError):
        resolve_safe_path(base, "draft_1", "../../escape.txt")

    with pytest.raises(PathTraversalError):
        resolve_safe_path(base, "/etc/passwd")

    with pytest.raises(PathTraversalError):
        resolve_safe_path(base, "draft_1/nested")

    # Symlink escape rejection
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    symlink_dir = base / "sym_link"
    os.symlink(outside, symlink_dir)

    with pytest.raises(PathTraversalError):
        resolve_safe_path(base, "sym_link", "target.txt")


def test_storage_delete_draft_containment(tmp_path: Path):
    store = DraftStore(data_dir=tmp_path)
    draft = store.create_draft(user_notes="Safe draft")
    draft_id = draft.id

    # Verify invalid IDs are rejected
    with pytest.raises(ValueError):
        store.delete_draft("../../escape")

    # Ensure legitimate deletion works
    assert store.delete_draft(draft_id) is True
    assert store.get_draft(draft_id) is None


def test_image_variant_validation_and_containment(tmp_path: Path):
    store = DraftStore(data_dir=tmp_path)
    draft = store.create_draft(user_notes="Variant test")
    img_id = "img_valid123"

    # Add mock image record
    draft.images.append(
        DraftImage(
            id=img_id,
            original_filename="test.jpg",
            width=800,
            height=600,
        )
    )
    store.update_draft(draft)

    # Invalid variant parameter must be rejected
    with pytest.raises(ValueError):
        store.get_image_file_path(draft.id, img_id, "../../etc/passwd")

    with pytest.raises(ValueError):
        store.get_image_file_path(draft.id, img_id, "unknown_variant")

    # Traversal in IDs must be rejected
    with pytest.raises(ValueError):
        store.get_image_file_path("../bad_draft", img_id, "optimized")

    with pytest.raises(ValueError):
        store.get_image_file_path(draft.id, "../bad_image", "optimized")


def test_import_validation_and_duplicate_rejection(tmp_path: Path):
    store = DraftStore(data_dir=tmp_path)

    # 1. Traversal ID in import
    payload_traversal = {
        "version": 1,
        "drafts": [
            {
                "id": "../../bad_id",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
    }
    with pytest.raises(ValueError, match="Invalid draft_id"):
        store.import_drafts_data(payload_traversal)

    # 2. Duplicate draft IDs in same import
    payload_dup_drafts = {
        "version": 1,
        "drafts": [
            {
                "id": "draft_duplicate1",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "draft_duplicate1",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
        ],
    }
    with pytest.raises(ValueError, match="Doppelte Draft-ID"):
        store.import_drafts_data(payload_dup_drafts)

    # 3. Duplicate image IDs within a draft
    payload_dup_images = {
        "version": 1,
        "drafts": [
            {
                "id": "draft_ok1",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "images": [
                    {
                        "id": "img_same",
                        "original_filename": "a.jpg",
                        "width": 100,
                        "height": 100,
                    },
                    {
                        "id": "img_same",
                        "original_filename": "b.jpg",
                        "width": 100,
                        "height": 100,
                    },
                ],
            }
        ],
    }
    with pytest.raises(ValueError, match="Doppelte Bild-ID"):
        store.import_drafts_data(payload_dup_images)


def test_update_draft_fields_dto_ignores_injected_images(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, require_auth=False)
    store = DraftStore(data_dir=tmp_path)
    img_svc = ImageService(data_dir=tmp_path)
    app = create_app(settings=settings, draft_store=store, image_service=img_svc)
    client = TestClient(app)

    draft = store.create_draft(user_notes="Original Note")
    draft_id = draft.id

    # Client attempts to inject malicious image records via PUT /api/drafts/{id}
    malicious_update = {
        "id": draft_id,
        "user_notes": "Legitimate updated note",
        "images": [
            {
                "id": "injected_img_999",
                "original_filename": "injected.jpg",
                "width": 100,
                "height": 100,
            }
        ],
        "revision": 1,
    }

    res = client.put(f"/api/drafts/{draft_id}", json=malicious_update)
    assert res.status_code == 200
    data = res.json()
    assert data["user_notes"] == "Legitimate updated note"
    assert len(data["images"]) == 0, "Images must NOT be accepted via draft update endpoint"

    # ID mismatch returns 400
    res_mismatch = client.put(f"/api/drafts/{draft_id}", json={"id": "draft_other123"})
    assert res_mismatch.status_code == 400


def test_api_variant_endpoint_security(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, require_auth=False)
    store = DraftStore(data_dir=tmp_path)
    img_svc = ImageService(data_dir=tmp_path)
    app = create_app(settings=settings, draft_store=store, image_service=img_svc)
    client = TestClient(app)

    draft = store.create_draft(user_notes="API Variant Test")
    draft_id = draft.id

    # Malicious variant path
    res = client.get(f"/api/drafts/{draft_id}/images/img_123/../../etc/passwd")
    # FastAPI path routing or handler rejects traversal with 400 or 404
    assert res.status_code in (400, 404)

    # Invalid variant enum value returns 400
    res_invalid_var = client.get(f"/api/drafts/{draft_id}/images/img_123/unsupported_mode")
    assert res_invalid_var.status_code == 400
