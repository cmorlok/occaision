from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class DraftStatus(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"


class ImageVariantMode(str, Enum):
    OPTIMIZED = "optimized"   # Default: Original background, EXIF stripped, auto-enhanced
    BLURRED = "blurred"       # Softly blurred background, sharp subject
    CUTOUT = "cutout"         # Neutral solid background (#F8F9FA) via rembg


class ConditionType(str, Enum):
    NEU = "neu"
    WIE_NEU = "wie_neu"
    GEBRAUCHT = "gebraucht"
    DEFEKT = "defekt"


class OfferType(str, Enum):
    AUCTION = "auction"
    FIXED_PRICE = "fixed_price"


class ShippingPreset(BaseModel):
    id: str
    label: str                # e.g., "B-Post Paket bis 2 kg (8.50 CHF)"
    cost_chf: float           # e.g., 8.50
    pickup_allowed: bool = True


class PresetSettings(BaseModel):
    default_offer_type: OfferType = OfferType.AUCTION
    default_shipping_preset_id: str = "b_post_2kg"
    shipping_presets: List[ShippingPreset] = Field(default_factory=lambda: [
        ShippingPreset(id="b_post_2kg", label="Paket B-Post bis 2 kg (8.50 CHF)", cost_chf=8.50, pickup_allowed=True),
        ShippingPreset(id="b_post_10kg", label="Paket B-Post bis 10 kg (11.50 CHF)", cost_chf=11.50, pickup_allowed=True),
        ShippingPreset(id="grossbrief", label="Grossbrief B-Post (2.00 CHF)", cost_chf=2.00, pickup_allowed=True),
        ShippingPreset(id="pickup_only", label="Nur Abholung vor Ort (0.00 CHF)", cost_chf=0.00, pickup_allowed=True),
    ])


class DraftImage(BaseModel):
    id: str
    original_filename: str
    active_mode: ImageVariantMode = ImageVariantMode.OPTIMIZED
    variants: Dict[ImageVariantMode, str] = Field(default_factory=dict)  # Relative URLs e.g. "/api/drafts/{id}/images/{img_id}/optimized"
    width: int
    height: int
    exif_stripped: bool = True


class EbaySoldStats(BaseModel):
    query: str
    sample_count: int = 0
    min_eur: Optional[float] = None
    max_eur: Optional[float] = None
    median_eur: Optional[float] = None
    median_chf: Optional[float] = None
    exchange_rate: float = 0.94


class VerificationLinks(BaseModel):
    ebay_sold_url: str
    ricardo_search_url: str
    toppreise_url: str
    digitec_url: str


class PriceAnalysis(BaseModel):
    ebay_stats: Optional[EbaySoldStats] = None
    ch_new_price_chf: Optional[float] = None
    ricardo_start_chf: float = 1.0
    ricardo_buynow_chf: float = 10.0
    tutti_vhb_chf: float = 10.0
    reasoning: str = ""
    verification_links: Optional[VerificationLinks] = None


class RicardoListing(BaseModel):
    title: str = Field(default="")
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    offer_type: OfferType = OfferType.AUCTION
    start_price_chf: float = 1.0
    buynow_price_chf: float = 10.0
    shipping_preset_id: str = "b_post_2kg"

    @field_validator("title", mode="before")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 60:
            return v[:60]
        return v


class TuttiListing(BaseModel):
    title: str = Field(default="")
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    price_vhb_chf: float = 10.0

    @field_validator("title", mode="before")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 80:
            return v[:80]
        return v


class Draft(BaseModel):
    id: str
    created_at: str
    updated_at: str
    status: DraftStatus = DraftStatus.DRAFT
    user_notes: str = ""
    identified_product: str = ""
    missing_photo_hints: List[str] = Field(default_factory=list)
    images: List[DraftImage] = Field(default_factory=list)
    price_analysis: PriceAnalysis = Field(default_factory=PriceAnalysis)
    ricardo: RicardoListing = Field(default_factory=RicardoListing)
    tutti: TuttiListing = Field(default_factory=TuttiListing)
