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


class PriceTypeDE(str, Enum):
    VB = "vb"                 # Verhandlungsbasis
    FESTPREIS = "festpreis"   # Festpreis


class MarketCountry(str, Enum):
    CH = "CH"
    DE = "DE"


class ShippingPreset(BaseModel):
    id: str
    country: MarketCountry = MarketCountry.CH
    label: str                # e.g., "B-Post Paket bis 2 kg (8.50 CHF)" or "DHL Paket bis 2 kg (5.49 EUR)"
    cost_chf: float = 0.0     # Kept for backwards compatibility
    cost: float = 0.0         # Cost in local currency (CHF for CH, EUR for DE)
    currency: str = "CHF"     # "CHF" or "EUR"
    pickup_allowed: bool = True


class PresetSettings(BaseModel):
    default_offer_type: OfferType = OfferType.AUCTION
    default_shipping_preset_id: str = "b_post_2kg"
    default_de_shipping_preset_id: str = "dhl_2kg"
    shipping_presets: List[ShippingPreset] = Field(default_factory=lambda: [
        # Swiss Presets (CHF)
        ShippingPreset(id="b_post_2kg", country=MarketCountry.CH, label="Paket B-Post bis 2 kg (8.50 CHF)", cost_chf=8.50, cost=8.50, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="b_post_10kg", country=MarketCountry.CH, label="Paket B-Post bis 10 kg (11.50 CHF)", cost_chf=11.50, cost=11.50, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="grossbrief", country=MarketCountry.CH, label="Grossbrief B-Post (2.00 CHF)", cost_chf=2.00, cost=2.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="pickup_only", country=MarketCountry.CH, label="Nur Abholung vor Ort (0.00 CHF)", cost_chf=0.00, cost=0.00, currency="CHF", pickup_allowed=True),
        # German Presets (EUR)
        ShippingPreset(id="dhl_2kg", country=MarketCountry.DE, label="DHL Paket bis 2 kg versichert (5.49 EUR)", cost_chf=0.0, cost=5.49, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_5kg", country=MarketCountry.DE, label="DHL Paket bis 5 kg versichert (6.99 EUR)", cost_chf=0.0, cost=6.99, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="hermes_s", country=MarketCountry.DE, label="Hermes S-Paket versichert (4.95 EUR)", cost_chf=0.0, cost=4.95, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="warensendung_de", country=MarketCountry.DE, label="Deutsche Post Bücher-/Warensendung (2.55 EUR)", cost_chf=0.0, cost=2.55, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="pickup_only_de", country=MarketCountry.DE, label="Nur Abholung vor Ort DE (0.00 EUR)", cost_chf=0.0, cost=0.00, currency="EUR", pickup_allowed=True),
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


class MarketSourceStats(BaseModel):
    source_id: str
    label: str
    currency: str = "EUR"
    sample_count: int = 0
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    median_price: Optional[float] = None
    median_chf: Optional[float] = None
    url: str = ""
    method: str = "fetch"


class VerificationLinks(BaseModel):
    ebay_sold_url: str
    kleinanzeigen_search_url: str = ""
    idealo_url: str = ""
    ricardo_search_url: str
    toppreise_url: str
    digitec_url: str


class PriceAnalysis(BaseModel):
    ebay_stats: Optional[EbaySoldStats] = None
    market_sources: Dict[str, MarketSourceStats] = Field(default_factory=dict)
    prices_fetched_via_extension: bool = False
    ch_new_price_chf: Optional[float] = None
    de_new_price_eur: Optional[float] = None
    ricardo_start_chf: float = 1.0
    ricardo_buynow_chf: float = 10.0
    tutti_vhb_chf: float = 10.0
    ebay_start_eur: float = 1.0
    ebay_buynow_eur: float = 10.0
    kleinanzeigen_vb_eur: float = 10.0
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


class EbayDEListing(BaseModel):
    title: str = Field(default="")
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    offer_type: OfferType = OfferType.AUCTION
    start_price_eur: float = 1.0
    buynow_price_eur: float = 10.0
    shipping_preset_id: str = "dhl_2kg"

    @field_validator("title", mode="before")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 80:
            return v[:80]
        return v


class KleinanzeigenListing(BaseModel):
    title: str = Field(default="")
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    price_eur: float = 10.0
    price_type: PriceTypeDE = PriceTypeDE.VB
    shipping_preset_id: str = "dhl_2kg"

    @field_validator("title", mode="before")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 65:
            return v[:65]
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
    ebay_de: EbayDEListing = Field(default_factory=EbayDEListing)
    kleinanzeigen: KleinanzeigenListing = Field(default_factory=KleinanzeigenListing)
