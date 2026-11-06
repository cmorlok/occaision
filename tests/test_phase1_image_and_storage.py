from pathlib import Path

import pytest
from PIL import Image

from backend.models import (
    ConditionType,
    Draft,
    DraftStatus,
    ImageVariantMode,
    MarketSourceStats,
    OfferType,
    PresetSettings,
    ShippingPreset,
)
from backend.services.image_service import ImageService
from backend.storage import (
    BatchLimitExceededError,
    DraftNotFoundError,
    DraftStore,
    FileTooLargeError,
    StorageService,
)


def dummy_mask_extractor(img: Image.Image) -> Image.Image:
    """Mock mask extractor that generates an in-memory RGBA image for fast test execution."""
    rgba = img.convert("RGBA")
    # Make edges transparent to simulate cutout mask
    alpha = Image.new("L", img.size, 200)
    rgba.putalpha(alpha)
    return rgba


def test_exif_and_gps_completely_stripped(temp_data_dir: Path, synthetic_exif_jpeg: bytes):
    image_service = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    draft_id = "draft_test_1"

    draft_img = image_service.process_upload(
        draft_id=draft_id,
        raw_bytes=synthetic_exif_jpeg,
        original_filename="camera_gps.jpg"
    )

    assert draft_img.exif_stripped is True

    opt_path = temp_data_dir / "images" / draft_id / f"{draft_img.id}_optimized.jpg"
    ai_path = temp_data_dir / "images" / draft_id / f"{draft_img.id}_ai.jpg"

    assert opt_path.exists()
    assert ai_path.exists()

    with Image.open(opt_path) as opt_img:
        assert len(opt_img.getexif()) == 0
    with Image.open(ai_path) as ai_img:
        assert len(ai_img.getexif()) == 0


def test_ai_image_downscaled_to_max_1024px(temp_data_dir: Path, synthetic_exif_jpeg: bytes):
    # synthetic_exif_jpeg is 3000x2000
    image_service = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    draft_id = "draft_test_2"

    draft_img = image_service.process_upload(
        draft_id=draft_id,
        raw_bytes=synthetic_exif_jpeg,
        original_filename="large.jpg"
    )

    opt_path = temp_data_dir / "images" / draft_id / f"{draft_img.id}_optimized.jpg"
    ai_path = temp_data_dir / "images" / draft_id / f"{draft_img.id}_ai.jpg"

    with Image.open(opt_path) as opt_img:
        # Original 3000x2000 downscaled to fit max 2048px -> 2048x1365
        assert opt_img.width <= 2048 and opt_img.height <= 2048
        assert opt_img.size == (2048, 1365)

    with Image.open(ai_path) as ai_img:
        # AI thumbnail max 1024px -> 1024x683
        assert ai_img.width <= 1024 and ai_img.height <= 1024
        assert ai_img.size == (1024, 683)


def test_heic_upload_converted_to_jpg(temp_data_dir: Path, synthetic_heic_image: bytes):
    image_service = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    draft_id = "draft_test_3"

    draft_img = image_service.process_upload(
        draft_id=draft_id,
        raw_bytes=synthetic_heic_image,
        original_filename="photo.heic"
    )

    opt_path = temp_data_dir / "images" / draft_id / f"{draft_img.id}_optimized.jpg"
    assert opt_path.exists()
    with Image.open(opt_path) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"


def test_cutout_and_blur_generation(temp_data_dir: Path, synthetic_exif_jpeg: bytes):
    image_service = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    draft_id = "draft_test_4"

    draft_img = image_service.process_upload(
        draft_id=draft_id,
        raw_bytes=synthetic_exif_jpeg,
        original_filename="subject.jpg"
    )

    cutout_path = image_service.get_or_create_cutout(draft_id=draft_id, image_id=draft_img.id)
    blurred_path = image_service.get_or_create_blurred(draft_id=draft_id, image_id=draft_img.id)

    assert cutout_path.exists()
    assert blurred_path.exists()

    with Image.open(cutout_path) as cutout_img:
        assert cutout_img.mode == "RGB"
        assert cutout_img.size == (draft_img.width, draft_img.height)

    with Image.open(blurred_path) as blur_img:
        assert blur_img.mode == "RGB"
        assert blur_img.size == (draft_img.width, draft_img.height)


def test_multi_draft_crud_persistence(temp_data_dir: Path):
    storage = StorageService(data_dir=temp_data_dir)

    # Verify default settings
    settings = storage.get_settings()
    assert settings.default_offer_type == OfferType.AUCTION
    assert settings.default_de_shipping_preset_id == "dhl_2kg"
    assert len(settings.shipping_presets) >= 9
    assert any(p.country.value == "CH" for p in settings.shipping_presets)
    assert any(p.country.value == "DE" for p in settings.shipping_presets)
    legacy_preset = ShippingPreset.model_validate({"id": "legacy_ch", "label": "Legacy", "cost_chf": 7.50, "currency": "CHF"})
    assert legacy_preset.cost == 7.50
    assert legacy_preset.cost_chf == 7.50
    assert settings.enabled_price_sources == [
        "ebay_de_sold",
        "kleinanzeigen",
        "idealo",
        "ricardo",
        "toppreise",
        "digitec",
        "tutti",
    ]

    # Test updating enabled price sources & debug setting
    assert settings.keep_tabs_open_after_search is False
    settings.enabled_price_sources = ["ebay_de_sold", "toppreise"]
    settings.keep_tabs_open_after_search = True
    storage.update_settings(settings)
    reloaded_settings = storage.get_settings()
    assert reloaded_settings.enabled_price_sources == ["ebay_de_sold", "toppreise"]
    assert reloaded_settings.keep_tabs_open_after_search is True

    # Create 3 drafts
    d1 = storage.create_draft(user_notes="Wenig gebraucht, OVP", identified_product="Sony WH-1000XM4")
    d2 = storage.create_draft(user_notes="Apple iPad")
    d3 = storage.create_draft(user_notes="Vintage Lamp")

    assert d1.id != d2.id
    assert d1.status == DraftStatus.DRAFT
    assert d1.identified_product == "Sony WH-1000XM4"
    assert d1.user_notes == "Wenig gebraucht, OVP"
    assert d1.ricardo.offer_type == settings.default_offer_type
    assert d1.ricardo.shipping_preset_id == settings.default_shipping_preset_id
    assert d1.ebay_de.offer_type == settings.default_offer_type
    assert d1.ebay_de.shipping_preset_id == settings.default_de_shipping_preset_id
    assert d1.kleinanzeigen.shipping_preset_id == settings.default_de_shipping_preset_id

    # Update d2 with extension-scraped market sources
    d2.status = DraftStatus.READY
    d2.price_analysis.prices_fetched_via_extension = True
    d2.price_analysis.market_sources["ebay_de_sold"] = MarketSourceStats(
        source_id="ebay_de_sold",
        label="eBay DE (Gebraucht & Beendet)",
        currency="EUR",
        sample_count=6,
        min_price=120.0,
        max_price=180.0,
        median_price=150.0,
        median_chf=141.0,
        url="https://www.ebay.de/sch/i.html?_nkw=Apple+iPad&LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000",
        method="fetch",
    )
    # Test title safeguard: longer than 60 chars must be truncated <= 60
    d2.ricardo.title = "A" * 75
    d2.tutti.title = "B" * 90
    d2.tutti.description = "T" * 4500
    d2.ebay_de.title = "C" * 95
    d2.kleinanzeigen.title = "D" * 80
    saved_d2 = storage.update_draft(d2)
    assert len(saved_d2.ricardo.title) <= 60
    assert len(saved_d2.tutti.title) <= 60
    assert len(saved_d2.tutti.description) <= 4000
    assert len(saved_d2.ebay_de.title) <= 80
    assert len(saved_d2.kleinanzeigen.title) <= 65
    assert saved_d2.price_analysis.prices_fetched_via_extension is True
    assert saved_d2.price_analysis.market_sources["ebay_de_sold"].median_price == 150.0

    # Create fake image folder for d1 to verify deletion cleanup
    img_dir_d1 = temp_data_dir / "images" / d1.id
    img_dir_d1.mkdir(parents=True, exist_ok=True)
    fake_img_file = img_dir_d1 / "test.jpg"
    fake_img_file.write_bytes(b"dummy")

    # Re-instantiate storage to verify persistence from disk
    storage_reloaded = StorageService(data_dir=temp_data_dir)
    drafts = storage_reloaded.list_drafts()
    assert len(drafts) == 3
    # Check that d2 is at the top or updated_at ordered
    d2_loaded = storage_reloaded.get_draft(d2.id)
    assert d2_loaded is not None
    assert d2_loaded.status == DraftStatus.READY
    assert len(d2_loaded.ricardo.title) <= 60

    # Delete d1
    delete_result = storage_reloaded.delete_draft(d1.id)
    assert delete_result is True
    assert storage_reloaded.get_draft(d1.id) is None
    assert not img_dir_d1.exists()
    assert len(storage_reloaded.list_drafts()) == 2


def test_storage_export_and_import(temp_data_dir: Path):
    storage = StorageService(data_dir=temp_data_dir)

    # 1. Create drafts with distinct content
    d1 = storage.create_draft(user_notes="Export Test Note 1", identified_product="Product A")
    d2 = storage.create_draft(user_notes="Export Test Note 2", identified_product="Product B")

    # Export data
    backup = storage.export_drafts_data()
    assert backup.get("version") == 1
    assert "exported_at" in backup
    assert len(backup.get("drafts", [])) == 2
    assert "settings" in backup

    # 2. Test importing into fresh storage instance
    new_dir = temp_data_dir / "restored_store"
    storage_new = StorageService(data_dir=new_dir)
    assert len(storage_new.list_drafts()) == 0

    res = storage_new.import_drafts_data(backup)
    assert res["imported_count"] == 2
    assert res["total_count"] == 2
    assert len(storage_new.list_drafts()) == 2
    assert storage_new.get_draft(d1.id).user_notes == "Export Test Note 1"

    # 3. Test merge vs overwrite
    d3 = storage_new.create_draft(user_notes="Unique Local Note")
    assert len(storage_new.list_drafts()) == 3

    # Merge import: d1 and d2 re-imported, d3 preserved
    res_merge = storage_new.import_drafts_data(backup, overwrite=False)
    assert res_merge["total_count"] == 3

    # Overwrite import: d3 removed, only backup items remain
    res_overwrite = storage_new.import_drafts_data(backup, overwrite=True)
    assert res_overwrite["total_count"] == 2
    assert storage_new.get_draft(d3.id) is None

    # 4. Invalid payload validation
    with pytest.raises(ValueError, match="JSON-Objekt erwartet"):
        storage_new.import_drafts_data(["not", "a", "dict"])

    with pytest.raises(ValueError, match="drafts.*muss eine Liste sein"):
        storage_new.import_drafts_data({"drafts": "invalid"})

    with pytest.raises(ValueError, match="Ungültiger Entwurf im Import"):
        storage_new.import_drafts_data({"drafts": [{"id": 12345, "invalid": True}]})


def test_storage_orphan_image_cleanup(temp_data_dir: Path):
    storage = StorageService(data_dir=temp_data_dir)
    d1 = storage.create_draft(user_notes="Active Draft")

    # Create image dir for active draft
    active_img_dir = temp_data_dir / "images" / d1.id
    active_img_dir.mkdir(parents=True, exist_ok=True)
    (active_img_dir / "img1.jpg").write_text("data", encoding="utf-8")

    # Create orphaned image dir
    orphan_img_dir = temp_data_dir / "images" / "orphan_12345"
    orphan_img_dir.mkdir(parents=True, exist_ok=True)
    (orphan_img_dir / "stale.jpg").write_text("stale", encoding="utf-8")

    cleaned = storage.cleanup_orphaned_images()
    assert cleaned == 1
    assert active_img_dir.exists()
    assert (active_img_dir / "img1.jpg").exists()
    assert not orphan_img_dir.exists()


def test_draft_store_add_images_and_atomic_rollback(temp_data_dir: Path, synthetic_exif_jpeg: bytes):
    img_svc = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    store = DraftStore(data_dir=temp_data_dir, image_service=img_svc)
    draft = store.create_draft(user_notes="Store Rollback Test")

    # 1. Valid upload
    updated = store.add_images(draft.id, [("test1.jpg", synthetic_exif_jpeg)])
    assert len(updated.images) == 1
    img1_id = updated.images[0].id
    assert (temp_data_dir / "images" / draft.id / f"{img1_id}_optimized.jpg").exists()

    # 2. Batch limit exceeded (> 15 files)
    oversized = [(f"f_{i}.jpg", synthetic_exif_jpeg) for i in range(16)]
    with pytest.raises(BatchLimitExceededError):
        store.add_images(draft.id, oversized)

    # 3. File size limit exceeded (> 25MB)
    too_large = [("huge.jpg", b"0" * (25 * 1024 * 1024 + 10))]
    with pytest.raises(FileTooLargeError):
        store.add_images(draft.id, too_large)

    # 4. Atomic rollback: file 1 valid, file 2 corrupt
    draft_before_err = store.get_draft(draft.id)
    initial_img_count = len(draft_before_err.images)
    initial_files = set((temp_data_dir / "images" / draft.id).iterdir())

    with pytest.raises(Exception):
        store.add_images(
            draft.id,
            [("good.jpg", synthetic_exif_jpeg), ("bad.jpg", b"not_an_image")],
        )

    # Verify no new images added to draft and no orphaned files remain on disk
    draft_after_err = store.get_draft(draft.id)
    assert len(draft_after_err.images) == initial_img_count
    current_files = set((temp_data_dir / "images" / draft.id).iterdir())
    assert current_files == initial_files


def test_draft_store_mode_switching_and_file_resolution(temp_data_dir: Path, synthetic_exif_jpeg: bytes):
    img_svc = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    store = DraftStore(data_dir=temp_data_dir, image_service=img_svc)
    draft = store.create_draft(user_notes="Store Mode Test")
    draft = store.add_images(draft.id, [("mode_img.jpg", synthetic_exif_jpeg)])
    img_id = draft.images[0].id

    # Switch to cutout
    draft = store.set_image_mode(draft.id, img_id, ImageVariantMode.CUTOUT)
    assert draft.images[0].active_mode == ImageVariantMode.CUTOUT
    assert ImageVariantMode.CUTOUT in draft.images[0].variants

    # Switch to blurred
    draft = store.set_image_mode(draft.id, img_id, ImageVariantMode.BLURRED)
    assert draft.images[0].active_mode == ImageVariantMode.BLURRED
    assert ImageVariantMode.BLURRED in draft.images[0].variants

    # File path resolution
    cutout_path = store.get_image_file_path(draft.id, img_id, "cutout")
    blurred_path = store.get_image_file_path(draft.id, img_id, "blurred")
    active_path = store.get_image_file_path(draft.id, img_id, "active")

    assert cutout_path.exists()
    assert blurred_path.exists()
    assert active_path == blurred_path

    # AI paths
    ai_paths = store.get_ai_image_paths(draft.id)
    assert len(ai_paths) == 1
    assert ai_paths[0].exists()
    assert "_ai.jpg" in ai_paths[0].name


def test_draft_store_delete_image_and_draft(temp_data_dir: Path, synthetic_exif_jpeg: bytes):
    img_svc = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    store = DraftStore(data_dir=temp_data_dir, image_service=img_svc)
    draft = store.create_draft(user_notes="Store Delete Test")
    draft = store.add_images(
        draft.id,
        [("del1.jpg", synthetic_exif_jpeg), ("del2.jpg", synthetic_exif_jpeg)],
    )
    assert len(draft.images) == 2
    img1_id = draft.images[0].id
    img2_id = draft.images[1].id

    # Delete first image
    draft = store.delete_image(draft.id, img1_id)
    assert len(draft.images) == 1
    assert draft.images[0].id == img2_id
    assert not (temp_data_dir / "images" / draft.id / f"{img1_id}_optimized.jpg").exists()
    assert (temp_data_dir / "images" / draft.id / f"{img2_id}_optimized.jpg").exists()

    # Delete draft entirely
    draft_dir = temp_data_dir / "images" / draft.id
    assert draft_dir.exists()
    store.delete_draft(draft.id)
    assert not draft_dir.exists()


def test_import_oversized_payload_rejected(temp_data_dir: Path):
    from fastapi.testclient import TestClient

    from backend.config import Settings
    from backend.main import create_app

    app = create_app(settings=Settings(data_dir=temp_data_dir, require_auth=False))
    client = TestClient(app)

    # 1. Content-Length header exceeding 10 MB rejected early
    res = client.post("/api/drafts/import", headers={"Content-Length": str(11 * 1024 * 1024)}, json={})
    assert res.status_code == 413

    # 2. Large body payload exceeding 10 MB rejected
    large_body = b'{"drafts": [' + (b'"x"' * (10 * 1024 * 1024 + 20)) + b"]}"
    res2 = client.post("/api/drafts/import", content=large_body, headers={"Content-Type": "application/json"})
    assert res2.status_code == 413


def test_upload_failure_orphan_cleanup(temp_data_dir: Path, synthetic_exif_jpeg: bytes, monkeypatch):
    image_service = ImageService(data_dir=temp_data_dir, mask_extractor=dummy_mask_extractor)
    draft_id = "draft_orphan_test"

    # Make ai_img.save fail to simulate disk full or serialization failure
    orig_save = Image.Image.save
    call_count = 0

    def faulty_save(self, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:  # First save (optimized) succeeds, second save (ai) fails
            raise IOError("Simulated disk error during secondary variant write")
        return orig_save(self, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", faulty_save)

    with pytest.raises(IOError, match="Simulated disk error"):
        image_service.process_upload(
            draft_id=draft_id,
            raw_bytes=synthetic_exif_jpeg,
            original_filename="fail_test.jpg",
        )

    # Ensure no residual image files were left behind in the draft images folder
    draft_img_dir = temp_data_dir / "images" / draft_id
    leftover_files = list(draft_img_dir.glob("*"))
    assert leftover_files == [], f"Expected 0 leftover files, found: {leftover_files}"




