import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from backend.config import Settings
from backend.main import create_app
from backend.services.image_service import ImageService
from backend.storage import DraftStore


def _create_sample_jpeg() -> bytes:
    img = Image.new("RGB", (150, 150), color=(25, 50, 75))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_complete_backup_and_restore_clean_instance(tmp_path: Path):
    data_dir_a = tmp_path / "data_a"
    data_dir_b = tmp_path / "data_b"

    img_svc_a = ImageService(data_dir=data_dir_a)
    store_a = DraftStore(data_dir=data_dir_a, image_service=img_svc_a)

    draft = store_a.create_draft(user_notes="Backup Test Note", identified_product="Test Product")
    img_bytes = _create_sample_jpeg()
    draft = store_a.add_images(draft.id, [("test_photo.jpg", img_bytes)])
    assert len(draft.images) == 1
    img_id = draft.images[0].id

    # Export complete ZIP backup
    zip_path = store_a.create_backup_archive()
    assert zip_path.exists()
    assert zipfile.is_zipfile(zip_path)

    # Inspect zip contents
    with zipfile.ZipFile(zip_path, "r") as zf:
        namelist = zf.namelist()
        assert "manifest.json" in namelist
        assert "drafts.json" in namelist
        assert "settings.json" in namelist
        assert f"images/{draft.id}/{img_id}_optimized.jpg" in namelist
        assert f"images/{draft.id}/{img_id}_ai.jpg" in namelist

        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["format"] == "occaision_backup_v1"
        assert f"images/{draft.id}/{img_id}_optimized.jpg" in manifest["files"]

    # Restore into fresh instance B
    img_svc_b = ImageService(data_dir=data_dir_b)
    store_b = DraftStore(data_dir=data_dir_b, image_service=img_svc_b)
    assert len(store_b.list_drafts()) == 0

    res = store_b.restore_backup_archive(zip_path)
    assert res["ok"] is True
    assert res["restored_drafts"] == 1
    assert res["restored_images"] == 1

    # Verify restored data on instance B
    restored_drafts = store_b.list_drafts()
    assert len(restored_drafts) == 1
    rd = restored_drafts[0]
    assert rd.id == draft.id
    assert rd.user_notes == "Backup Test Note"
    assert len(rd.images) == 1
    assert rd.images[0].id == img_id

    # Verify restored photo file exists and can be resolved
    opt_file = store_b.get_image_file_path(rd.id, img_id, "optimized")
    assert opt_file.exists()
    assert opt_file.is_file()


def test_restore_detects_checksum_tampering(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = DraftStore(data_dir=data_dir)
    store.create_draft(user_notes="Original")
    zip_path = store.create_backup_archive()

    # Tamper with drafts.json in the zip without updating manifest
    tampered_zip = tmp_path / "tampered.zip"
    with zipfile.ZipFile(zip_path, "r") as zin:
        with zipfile.ZipFile(tampered_zip, "w") as zout:
            for item in zin.infolist():
                buffer = zin.read(item.filename)
                if item.filename == "drafts.json":
                    buffer = b'[{"id": "tampered", "created_at": "now", "updated_at": "now"}]'
                zout.writestr(item, buffer)

    fresh_dir = tmp_path / "fresh"
    store_fresh = DraftStore(data_dir=fresh_dir)
    import pytest
    with pytest.raises(ValueError, match="Prüfsummenfehler"):
        store_fresh.restore_backup_archive(tampered_zip)


def test_orphaned_image_quarantine(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = DraftStore(data_dir=data_dir)

    # Create orphaned folder in images
    orphan_dir = data_dir / "images" / "draft_orphan123"
    orphan_dir.mkdir(parents=True, exist_ok=True)
    (orphan_dir / "test.jpg").write_bytes(b"data")

    cleaned = store.cleanup_orphaned_images(quarantine=True)
    assert cleaned == 1

    # Orphan must be moved to quarantine folder, not deleted
    assert not orphan_dir.exists()
    quarantine_entry = data_dir / "quarantine" / "draft_orphan123"
    assert quarantine_entry.exists()
    assert (quarantine_entry / "test.jpg").exists()


def test_backup_restore_api_endpoints(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, require_auth=False)
    store = DraftStore(data_dir=tmp_path)
    store.create_draft(user_notes="API Backup Test")

    app = create_app(settings=settings, draft_store=store)
    client = TestClient(app)

    # 1. Export complete backup
    res_export = client.get("/api/backup/export")
    assert res_export.status_code == 200
    assert "application/zip" in res_export.headers.get("content-type", "")
    zip_bytes = res_export.content
    assert zipfile.is_zipfile(io.BytesIO(zip_bytes))

    # 2. Restore complete backup
    res_restore = client.post(
        "/api/backup/restore",
        files={"file": ("backup.zip", zip_bytes, "application/zip")},
    )
    assert res_restore.status_code == 200
    data = res_restore.json()
    assert data["ok"] is True
    assert data["restored_drafts"] == 1


def test_backup_restore_oversize_rejected(tmp_path: Path, monkeypatch):
    import backend.main as b_main
    monkeypatch.setattr(b_main, "MAX_BACKUP_SIZE", 500)  # 500 bytes limit

    settings = Settings(data_dir=tmp_path, require_auth=False)
    store = DraftStore(data_dir=tmp_path)
    app = create_app(settings=settings, draft_store=store)
    client = TestClient(app)

    oversize_payload = b"A" * 1024  # 1 KB > 500 bytes
    res = client.post(
        "/api/backup/restore",
        files={"file": ("huge_backup.zip", oversize_payload, "application/zip")},
    )
    assert res.status_code == 413
    assert "überschreitet maximal zulässige Grösse" in res.json()["detail"]

