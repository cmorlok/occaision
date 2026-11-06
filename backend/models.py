import re
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_identifier(val: str, field_name: str = "id") -> str:
    if not isinstance(val, str) or not ID_PATTERN.match(val):
        raise ValueError(
            f"Invalid {field_name}: must be 1-64 characters matching [a-zA-Z0-9_-], got {val!r}"
        )
    return val


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
    cost: float = 0.0         # Cost in local currency (CHF for CH, EUR for DE)
    currency: str = "CHF"     # "CHF" or "EUR"
    pickup_allowed: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return validate_identifier(v, "preset_id")

    @property
    def cost_chf(self) -> float:
        return self.cost if self.currency == "CHF" else 0.0

    @model_validator(mode="before")
    @classmethod
    def populate_cost(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "cost" not in data and "cost_chf" in data:
                data["cost"] = data["cost_chf"]
        return data


DEFAULT_PRICE_SOURCES = [
    "ebay_de_sold",
    "kleinanzeigen",
    "idealo",
    "ricardo",
    "toppreise",
    "digitec",
    "tutti",
]


class PresetSettings(BaseModel):
    default_offer_type: OfferType = OfferType.AUCTION
    default_shipping_preset_id: str = "b_post_2kg"
    default_de_shipping_preset_id: str = "dhl_2kg"
    enabled_price_sources: List[str] = Field(default_factory=lambda: list(DEFAULT_PRICE_SOURCES))
    keep_tabs_open_after_search: bool = False
    shipping_presets: List[ShippingPreset] = Field(default_factory=lambda: [
        # Swiss Presets (CHF) - B-Post
        ShippingPreset(id="kleinsendung_100g", country=MarketCountry.CH, label="Kleinsendung B-Post bis 100 g (3.00 CHF)", cost=3.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="kleinsendung_500g", country=MarketCountry.CH, label="Kleinsendung B-Post bis 500 g (3.40 CHF)", cost=3.40, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="b_post_2kg", country=MarketCountry.CH, label="Paket B-Post bis 2 kg (9.00 CHF)", cost=9.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="b_post_10kg", country=MarketCountry.CH, label="Paket B-Post bis 10 kg (12.00 CHF)", cost=12.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="b_post_30kg", country=MarketCountry.CH, label="Paket B-Post bis 30 kg (21.00 CHF)", cost=21.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="pickup_only", country=MarketCountry.CH, label="Nur Abholung vor Ort (0.00 CHF)", cost=0.00, currency="CHF", pickup_allowed=True),
        # German Presets (EUR)
        ShippingPreset(id="grossbrief_500g_de", country=MarketCountry.DE, label="Großbrief bis 500 g (1.80 EUR)", cost=1.80, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="warensendung_1000g_de", country=MarketCountry.DE, label="Warensendung bis 1.000 g (2.70 EUR)", cost=2.70, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="warensendung_2000g_de", country=MarketCountry.DE, label="Warensendung bis 2.000 g (3.55 EUR)", cost=3.55, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="maxibrief_1000g_de", country=MarketCountry.DE, label="Maxibrief bis 1.000 g (2.90 EUR)", cost=2.90, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_paeckchen_s", country=MarketCountry.DE, label="DHL Päckchen S bis 2 kg (4.19 EUR)", cost=4.19, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_paeckchen_m", country=MarketCountry.DE, label="DHL Päckchen M bis 2 kg (5.19 EUR)", cost=5.19, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_2kg", country=MarketCountry.DE, label="DHL Paket bis 2 kg versichert (6.19 EUR)", cost=6.19, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_5kg", country=MarketCountry.DE, label="DHL Paket bis 5 kg versichert (7.69 EUR)", cost=7.69, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_10kg", country=MarketCountry.DE, label="DHL Paket bis 10 kg versichert (10.49 EUR)", cost=10.49, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_20kg", country=MarketCountry.DE, label="DHL Paket bis 20 kg versichert (18.99 EUR)", cost=18.99, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_31_5kg", country=MarketCountry.DE, label="DHL Paket bis 31.5 kg versichert (23.99 EUR)", cost=23.99, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="pickup_only_de", country=MarketCountry.DE, label="Nur Abholung vor Ort DE (0.00 EUR)", cost=0.00, currency="EUR", pickup_allowed=True),
    ])


class DraftImage(BaseModel):
    id: str
    original_filename: str
    active_mode: ImageVariantMode = ImageVariantMode.OPTIMIZED
    variants: Dict[ImageVariantMode, str] = Field(default_factory=dict)  # Relative URLs e.g. "/api/drafts/{id}/images/{img_id}/optimized"
    width: int
    height: int
    exif_stripped: bool = True

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return validate_identifier(v, "image_id")


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
    login_required: bool = False
    error: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    captured_at: Optional[str] = None
    query: Optional[str] = None
    confidence: Optional[float] = None


class VerificationLinks(BaseModel):
    ebay_sold_url: str
    kleinanzeigen_search_url: str = ""
    idealo_url: str = ""
    ricardo_search_url: str
    toppreise_url: str
    digitec_url: str
    tutti_search_url: str = ""


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
    model_config = ConfigDict(validate_assignment=True)
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
            return v[:60].rstrip()
        return v


class TuttiListing(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
    title: str = Field(default="")
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    price_vhb_chf: float = 10.0

    @field_validator("title", mode="before")
    @classmethod
    def truncate_title(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 60:
            return v[:60].rstrip()
        return v

    @field_validator("description", mode="before")
    @classmethod
    def truncate_description(cls, v: str) -> str:
        if isinstance(v, str) and len(v) > 4000:
            disclaimer = "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
            if disclaimer in v:
                idx = v.rfind(disclaimer)
                body = v[:idx].rstrip()
                tail = v[idx:]
                avail = 4000 - len(tail) - 2  # account for \n\n
                if avail > 0:
                    return f"{body[:avail].rstrip()}\n\n{tail}".strip()
            return v[:4000].rstrip()
        return v


class EbayDEListing(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
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
            return v[:80].rstrip()
        return v


class KleinanzeigenListing(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
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
            return v[:65].rstrip()
        return v


class Draft(BaseModel):
    id: str
    created_at: str
    updated_at: str
    revision: int = 1
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

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        return validate_identifier(v, "draft_id")


class UpdateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[str] = None
    user_notes: Optional[str] = None
    identified_product: Optional[str] = None
    status: Optional[DraftStatus] = None
    missing_photo_hints: Optional[List[str]] = None
    price_analysis: Optional[PriceAnalysis] = None
    ricardo: Optional[RicardoListing] = None
    tutti: Optional[TuttiListing] = None
    ebay_de: Optional[EbayDEListing] = None
    kleinanzeigen: Optional[KleinanzeigenListing] = None
    revision: Optional[int] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            return validate_identifier(v, "draft_id")
        return v
