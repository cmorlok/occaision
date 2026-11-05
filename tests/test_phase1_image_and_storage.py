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
from backend.storage import StorageService


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
    d2.ebay_de.title = "C" * 95
    d2.kleinanzeigen.title = "D" * 80
    saved_d2 = storage.update_draft(d2)
    assert len(saved_d2.ricardo.title) <= 60
    assert len(saved_d2.tutti.title) <= 80
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
