# Implementation Plan & Specification: Seller Assistant

> **Target Audience:** Autonomous Software Engineering Agent / Implementing Developer  
> **Reference Requirements:** `REQUIREMENTS.md`  
> **Mandatory Engineering Rules:** `AGENTS.md`  
> **Architecture:** Local Python FastAPI Backend (`127.0.0.1:8000`) + Local Web Dashboard + Firefox WebExtension (Manifest V3)  
> **Supported Marketplaces:** Switzerland (`ricardo.ch`, `tutti.ch`) & Germany (`ebay.de`, `kleinanzeigen.de`)

---

## 1. Execution Instructions for the Implementing Agent

> **MANDATORY:** Read `AGENTS.md`, `REQUIREMENTS.md`, and this `IMPLEMENTATION_PLAN.md` completely before writing a single line of code.

1. **Strict Incremental TDD Loop (Phase 0 $\rightarrow$ Phase 1 $\rightarrow$ Phase 2 $\rightarrow$ Phase 3 $\rightarrow$ Phase 4):**
   * **NEVER** implement multiple phases or the whole codebase at once before running tests.
   * First complete **Phase 0 (Development Environment & Scaffolding)** and commit.
   * For each subsequent phase (**Phase 1** through **Phase 4**), execute this exact loop:
     1. **Write Tests First (RED):** Create `tests/test_phaseX_*.py` covering all Acceptance Criteria for that phase.
     2. **Verify Red State:** Run `.venv/bin/pytest -v` and confirm the new tests fail because the implementation is not yet written (not because of syntax/import typos in the test file).
     3. **Implement Production Code:** Write clean, modular production code matching the exact contracts in this plan.
     4. **Test & Fix Loop (GREEN):** Run `.venv/bin/pytest -v` across the **entire** test suite. Fix any failures one by one until **100% of tests pass (0 failures, 0 errors)**.
     5. **Stop Gate:** Do **NOT** start Phase $N+1$ while any test in Phase $1..N$ is failing.
     6. **Atomic Git Commit:** Run `git status` and commit the green phase using the Conventional Commit message specified for that phase.
2. **Strict Contract Adherence:**
   * Do not invent new field names, route URLs, DOM element IDs, or extension message names. Use the exact identifiers specified in this document.
3. **Offline & Deterministic Testability (< 10 Seconds):**
   * Every external dependency (Google Gemini API, `ebay.de` HTTP calls, `rembg` ONNX inference) MUST be injectable or mockable so `.venv/bin/pytest -v` runs completely offline in < 10 seconds without a live API key, live internet access, or downloading a 176 MB ONNX model.
4. **Hard Constraints to Enforce in Code:**
   * **Neutral Naming (`AGENTS.md` Rule 6):** Never use third-party marketplace names (`"Tutti"`, `"Ricardo"`, `"eBay"`, `"Kleinanzeigen"`) in project titles, extension titles (`manifest.json`), dashboard main headers (`<h1>` / `<title>`), or build artifact names (`dist/seller-assistant.zip`). The mandatory project and extension name is **`Seller Assistant`** (slug: `seller-assistant`).
   * **Privacy & Image Security:** Strip all EXIF/GPS metadata on upload (`len(img.getexif()) == 0`) and downscale AI-bound images to max `1024x1024` pixels before sending to Gemini.
   * **Title Length Limits (Enforced in Models, Storage & AI Post-Processing):**
     * **Ricardo.ch (`ricardo.title`):** Strictly $\le 60$ characters.
     * **Tutti.ch (`tutti.title`):** Strictly $\le 80$ characters.
     * **eBay.de (`ebay_de.title`):** Strictly $\le 80$ characters.
     * **Kleinanzeigen.de (`kleinanzeigen.title`):** Strictly $\le 65$ characters.
   * **Platform-Dependent Orthography:**
     * **Swiss Platforms (`ricardo`, `tutti`):** Replace `ß` with `ss` in all generated titles and descriptions.
     * **German Platforms (`ebay_de`, `kleinanzeigen`):** Preserve standard German orthography (including `ß`).
   * **Platform-Dependent Legal Disclaimers:**
     * **Swiss Platforms (`ricardo`, `tutti`):** Every description must include: `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."`
     * **German Platforms (`ebay_de`, `kleinanzeigen`):** Every description must include: `"Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."`
   * **CORS / CSP Bypass in Extension:** `extension/content.js` must **NEVER** call `fetch("http://127.0.0.1:8000/...")` or `fetch("http://localhost:8000/...")` directly. All backend HTTP requests must go through `extension/background.js` via `runtime.sendMessage`.

---

## 2. Phase 0: Development Environment & Repository Setup

### 2.1 System Prerequisites (Linux / Debian / Ubuntu / macOS)
Ensure the following OS packages are installed (required by `rembg`/`opencv-python-headless`, `pillow-heif`, and Node.js syntax checks):

```bash
sudo apt-get update && sudo apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    libgl1 libglib2.0-0 libheif-dev \
    nodejs
```

### 2.2 Python Virtual Environment Setup
Create an isolated virtual environment in `.venv` (if not already present):

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements.txt
```

### 2.3 Target Repository Structure
Create the following project structure in the workspace root:

```text
.
├── .env.example
├── .gitignore
├── requirements.txt
├── pytest.ini
├── AGENTS.md
├── REQUIREMENTS.md
├── IMPLEMENTATION_PLAN.md
├── data/                        # Runtime directory (gitignored, auto-created)
│   ├── drafts.json              # Persistent multi-draft store
│   ├── settings.json            # User presets (CH & DE shipping, default offer type)
│   └── images/                  # Subfolders per draft_id: data/images/<draft_id>/
├── backend/
│   ├── __init__.py
│   ├── config.py                # Settings loaded from .env via pydantic-settings
│   ├── models.py                # Pydantic v2 schemas (CH & DE listings, pricing, presets)
│   ├── storage.py               # Thread-safe JSON/file persistence for drafts & settings
│   ├── main.py                  # FastAPI app, routes, static files, CORS
│   └── services/
│       ├── __init__.py
│       ├── image_service.py     # HEIC->JPG, EXIF strip, auto-contrast, Blur, rembg Cutout, 1024px AI resize
│       ├── ebay_service.py      # eBay DE sold listings fetcher (curl_cffi) & CH/DE verification link builder
│       └── ai_service.py        # Gemini API integration with Search Grounding & JSON extraction
├── frontend/
│   ├── index.html               # Local Web Dashboard UI (Seller Assistant)
│   ├── styles.css               # Clean, responsive dashboard styling
│   └── app.js                   # Dashboard state, drag&drop upload, iterative AI re-run, live char counters
├── extension/
│   ├── manifest.json            # Firefox WebExtension Manifest V3 (Seller Assistant)
│   ├── background.js            # Background script communicating with 127.0.0.1:8000 & permission helper
│   ├── content.js               # Smart-Panel UI, platform detector (CH/DE), Xray-safe File injector, React/iframe setter
│   └── panel.css                # Isolated CSS for the floating Smart-Panel on ricardo.ch, tutti.ch, ebay.de, kleinanzeigen.de
└── tests/
    ├── conftest.py              # Shared pytest fixtures (temp data dir, synthetic EXIF images, mock HTML)
    ├── test_phase1_image_and_storage.py
    ├── test_phase2_pricing_and_ai.py
    ├── test_phase3_api_and_ui.py
    └── test_phase4_extension.py
```

### 2.4 `requirements.txt`
```text
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
pydantic>=2.7.0
pydantic-settings>=2.2.0
python-dotenv>=1.0.1
Pillow>=10.3.0
pillow-heif>=0.16.0
numba>=0.60.0
onnxruntime>=1.18.0
rembg[cpu]>=2.0.57
httpx>=0.27.0
curl-cffi>=0.7.0
beautifulsoup4>=4.12.3
lxml>=5.2.0
google-genai>=0.3.0
pytest>=8.1.0
pytest-asyncio>=0.23.6
```

### 2.5 `.env.example`, `.gitignore`, and `pytest.ini`
* **`.env.example`:**
  ```ini
  GEMINI_API_KEY=your_google_ai_studio_api_key_here
  GEMINI_MODEL=gemini-2.5-flash
  ENABLE_SEARCH_GROUNDING=true
  EUR_TO_CHF_RATE=0.94
  REMBG_MODEL=u2netp
  DATA_DIR=./data
  HOST=127.0.0.1
  PORT=8000
  ```
* **`.gitignore`:** Ignore `.venv/`, `__pycache__/`, `.pytest_cache/`, `.env`, `data/`, `dist/`, `*.pyc`.
* **`pytest.ini`:**
  ```ini
  [pytest]
  testpaths = tests
  asyncio_mode = auto
  pythonpath = .
  ```
* **Phase 0 Commit:** Once scaffolding and `tests/conftest.py` are in place, commit:
  `chore: initialize project structure and dependencies`

---

## 3. Core Configuration & Data Models (`backend/config.py` & `backend/models.py`)

### 3.1 `backend/config.py`
Implement `Settings` using `pydantic_settings.BaseSettings`:

```python
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    enable_search_grounding: bool = True
    eur_to_chf_rate: float = 0.94
    rembg_model: str = "u2netp"
    data_dir: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = 8000

settings = Settings()
```

### 3.2 `backend/models.py`
Implement these exact Pydantic v2 models in `backend/models.py`:

```python
from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

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
    label: str                # e.g., "Paket B-Post bis 2 kg (8.50 CHF)" or "DHL Paket bis 2 kg versichert (5.49 EUR)"
    cost: float               # Cost in local currency (CHF for CH, EUR for DE)
    cost_chf: Optional[float] = None
    currency: str = "CHF"     # "CHF" or "EUR"
    pickup_allowed: bool = True

class PresetSettings(BaseModel):
    default_offer_type: OfferType = OfferType.AUCTION
    default_shipping_preset_id: str = "b_post_2kg"
    default_de_shipping_preset_id: str = "dhl_2kg"
    shipping_presets: List[ShippingPreset] = Field(default_factory=lambda: [
        # Swiss Presets (CHF)
        ShippingPreset(id="b_post_2kg", country=MarketCountry.CH, label="Paket B-Post bis 2 kg (8.50 CHF)", cost=8.50, cost_chf=8.50, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="b_post_10kg", country=MarketCountry.CH, label="Paket B-Post bis 10 kg (11.50 CHF)", cost=11.50, cost_chf=11.50, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="grossbrief", country=MarketCountry.CH, label="Grossbrief B-Post (2.00 CHF)", cost=2.00, cost_chf=2.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="pickup_only", country=MarketCountry.CH, label="Nur Abholung vor Ort CH (0.00 CHF)", cost=0.00, cost_chf=0.00, currency="CHF", pickup_allowed=True),
        # German Presets (EUR)
        ShippingPreset(id="dhl_2kg", country=MarketCountry.DE, label="DHL Paket bis 2 kg versichert (5.49 EUR)", cost=5.49, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="dhl_5kg", country=MarketCountry.DE, label="DHL Paket bis 5 kg versichert (6.99 EUR)", cost=6.99, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="hermes_s", country=MarketCountry.DE, label="Hermes S-Paket versichert (4.95 EUR)", cost=4.95, currency="EUR", pickup_allowed=True),
        ShippingPreset(id="warensendung_de", country=MarketCountry.DE, label="Deutsche Post Bücher-/Warensendung (2.55 EUR)", cost=2.55, currency="EUR", pickup_allowed=True),
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
    kleinanzeigen_search_url: str
    idealo_url: str
    ricardo_search_url: str
    toppreise_url: str
    digitec_url: str

class PriceAnalysis(BaseModel):
    ebay_stats: Optional[EbaySoldStats] = None
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
    title: str = Field(default="", max_length=60)
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    offer_type: OfferType = OfferType.AUCTION
    start_price_chf: float = 1.0
    buynow_price_chf: float = 10.0
    shipping_preset_id: str = "b_post_2kg"

class TuttiListing(BaseModel):
    title: str = Field(default="", max_length=80)
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    price_vhb_chf: float = 10.0

class EbayDEListing(BaseModel):
    title: str = Field(default="", max_length=80)
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    offer_type: OfferType = OfferType.AUCTION
    start_price_eur: float = 1.0
    buynow_price_eur: float = 10.0
    shipping_preset_id: str = "dhl_2kg"

class KleinanzeigenListing(BaseModel):
    title: str = Field(default="", max_length=65)
    category_suggestion: str = ""
    description: str = ""
    condition: ConditionType = ConditionType.GEBRAUCHT
    price_eur: float = 10.0
    price_type: PriceTypeDE = PriceTypeDE.VB
    shipping_preset_id: str = "dhl_2kg"

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
```

---

## 4. Phase-by-Phase Implementation Specification & Technical Safeguards

---

### PHASE 1: Backend Core, Multi-Draft Persistence & Image Pipeline

#### 4.1.1 `backend/storage.py`
Implement `StorageService(data_dir: Path)` with thread-safe (`threading.RLock`) and atomic file writes (write to `.tmp` file then `os.replace`):
* `list_drafts() -> List[Draft]`: Returns all drafts sorted by `updated_at` descending.
* `get_draft(draft_id: str) -> Optional[Draft]`: Returns the matching `Draft` or `None`.
* `create_draft(user_notes: str = "") -> Draft`:
  * Generates a unique `id` (e.g., `uuid4().hex[:12]`) and ISO-8601 UTC timestamps (`created_at`, `updated_at`).
  * Pre-populates `ricardo.offer_type = settings.default_offer_type`, `ricardo.shipping_preset_id = settings.default_shipping_preset_id`, `ebay_de.offer_type = settings.default_offer_type`, `ebay_de.shipping_preset_id = settings.default_de_shipping_preset_id`, and `kleinanzeigen.shipping_preset_id = settings.default_de_shipping_preset_id`.
* `update_draft(draft: Draft) -> Draft`:
  * Enforces title length limits before validating/saving:
    * `draft.ricardo.title = truncate_title(draft.ricardo.title, 60)`
    * `draft.tutti.title = truncate_title(draft.tutti.title, 80)`
    * `draft.ebay_de.title = truncate_title(draft.ebay_de.title, 80)`
    * `draft.kleinanzeigen.title = truncate_title(draft.kleinanzeigen.title, 65)`
  * Updates `draft.updated_at` to a fresh ISO-8601 UTC timestamp and persists atomically to `data_dir / "drafts.json"`.
* `delete_draft(draft_id: str) -> bool`:
  * Removes the draft from `drafts.json` and deletes `data_dir / "images" / draft_id` via `shutil.rmtree(..., ignore_errors=True)`. Returns `True` if deleted, `False` if not found.
* `get_settings() -> PresetSettings` and `update_settings(settings: PresetSettings) -> PresetSettings`:
  * Reads/writes `data_dir / "settings.json"`.

#### 4.1.2 `backend/services/image_service.py`
* Register HEIC opener at module import:
  ```python
  import pillow_heif
  pillow_heif.register_heif_opener()
  ```
* **Constructor & Testability (`ImageService.__init__`):**
  ```python
  class ImageService:
      def __init__(
          self,
          data_dir: Path,
          rembg_model: str = "u2netp",
          mask_extractor: Optional[Callable[[Image.Image], Image.Image]] = None,
      ):
          self.data_dir = Path(data_dir)
          self.rembg_model = rembg_model
          self._mask_extractor = mask_extractor
          self._rembg_session = None
  ```
  * When `self._mask_extractor` is provided (e.g. in unit tests), `extract_foreground(img)` calls `self._mask_extractor(img).convert("RGBA")`.
  * Otherwise, `extract_foreground(img)` lazily initializes `self._rembg_session = rembg.new_session(self.rembg_model)` once and calls `rembg.remove(img, session=self._rembg_session)`.
* **Pipeline Methods:**
  1. `clean_and_orient(raw_bytes: bytes) -> Image.Image`:
     * Open image with `Image.open(io.BytesIO(raw_bytes))`.
     * Call `ImageOps.exif_transpose(img)` FIRST so portrait smartphone photos are oriented upright.
     * Convert to `"RGB"`.
     * Create a brand new `clean = Image.new("RGB", img.size)` and `clean.paste(img)` so **zero EXIF/GPS/camera metadata remains** (`len(clean.getexif()) == 0`).
  2. `create_optimized_variant(clean_img: Image.Image) -> Image.Image`:
     * Copy `clean_img`, apply `ImageOps.autocontrast(..., cutoff=0.5)`, and resize in-place via `thumbnail((2048, 2048), Image.Resampling.LANCZOS)`.
  3. `create_ai_input_variant(clean_img: Image.Image) -> Image.Image`:
     * Copy `clean_img` and resize in-place via `thumbnail((1024, 1024), Image.Resampling.LANCZOS)`. Never exceed `1024px` on either axis.
  4. `process_upload(draft_id: str, filename: str, raw_bytes: bytes, image_id: Optional[str] = None) -> DraftImage`:
     * Creates directory `self.data_dir / "images" / draft_id`.
     * Generates `optimized_img` and saves to `<image_id>_optimized.jpg` (`format="JPEG"`, `quality=90`).
     * Generates `ai_img` and saves to `<image_id>_ai.jpg` (`format="JPEG"`, `quality=85`).
     * Returns `DraftImage` with `id=image_id`, `original_filename=filename`, `active_mode=ImageVariantMode.OPTIMIZED`, `variants={ImageVariantMode.OPTIMIZED: f"/api/drafts/{draft_id}/images/{image_id}/optimized"}`, `width=optimized_img.width`, `height=optimized_img.height`, `exif_stripped=True`.
  5. `get_or_create_cutout(draft_id: str, image_id: str) -> Path`:
     * If `<image_id>_cutout.jpg` does not exist yet, load `<image_id>_optimized.jpg`, extract RGBA foreground via `self.extract_foreground(optimized_img)`, composite onto neutral light-gray/white canvas `Image.new("RGB", rgba.size, (248, 249, 250))` using `rgba.split()[3]` as mask, and save as `<image_id>_cutout.jpg` (`quality=90`). Return path.
  6. `get_or_create_blurred(draft_id: str, image_id: str) -> Path`:
     * If `<image_id>_blurred.jpg` does not exist yet, load `<image_id>_optimized.jpg`, extract RGBA foreground via `self.extract_foreground(optimized_img)`, create `blurred_bg = optimized_img.filter(ImageFilter.GaussianBlur(radius=18))`, composite `Image.composite(optimized_img, blurred_bg, rgba.split()[3])`, and save as `<image_id>_blurred.jpg` (`quality=90`). Return path.
  7. `get_variant_path(draft_id: str, image_id: str, mode: ImageVariantMode) -> Path`:
     * Dispatches to `<image_id>_optimized.jpg`, `get_or_create_blurred()`, or `get_or_create_cutout()`.
  8. `get_ai_image_bytes(draft_id: str, image_id: str) -> bytes`:
     * Reads and returns bytes of `<image_id>_ai.jpg`.

#### 4.1.3 Phase 1 Automated Acceptance Criteria (`tests/test_phase1_image_and_storage.py`)
Write automated `pytest` tests verifying:
1. **`test_exif_and_gps_completely_stripped`**: Create a synthetic JPEG containing EXIF tags (`Make`, `Model`, `GPSInfo`), process it through `ImageService.process_upload()`, reload `<image_id>_optimized.jpg` and `<image_id>_ai.jpg` from disk, and assert `len(img.getexif()) == 0`.
2. **`test_ai_image_downscaled_to_max_1024px`**: Upload a `3000x2000` image and assert `<image_id>_ai.jpg` has dimensions `1024x683` ($\le 1024$ on both axes), while `<image_id>_optimized.jpg` is `2048x1365`.
3. **`test_heic_upload_converted_to_jpg`**: Generate an in-memory HEIF/HEIC image via `pillow_heif`, pass it to `process_upload()`, and assert it succeeds and outputs valid RGB `.jpg` files.
4. **`test_cutout_and_blur_generation`**: Process an image with an injected fast `mask_extractor` and trigger `cutout` and `blurred` modes; assert both `.jpg` files exist on disk, match the optimized image dimensions, and have RGB mode.
5. **`test_multi_draft_crud_persistence`**: Create 3 drafts, update status and titles across CH and DE listings (`ricardo`, `tutti`, `ebay_de`, `kleinanzeigen`), re-instantiate `StorageService` from disk, assert all 3 drafts persist in order with CH and DE presets intact, verify title truncation (`60`, `80`, `80`, `65`), and verify deleting a draft removes both the JSON entry and its image folder.
* **Phase 1 Commit:** `feat(phase1): implement storage service and image pipeline with EXIF stripping`

---

### PHASE 2: Hybrid Price Engine & Gemini AI Service (CH & DE)

#### 4.2.1 `backend/services/ebay_service.py` (With TLS-Fingerprint Bypass)
* **Technical Reality & Safeguard:**
  * Standard `httpx` calls to `ebay.de` are frequently blocked by eBay's anti-bot TLS/JA3 fingerprinting (`splashui/challenge`).
  * `fetch_sold_stats()` MUST use **`curl_cffi.requests.AsyncSession(impersonate="chrome")`** (with fallback to `httpx.AsyncClient` if needed) and support an optional injectable `http_get: Optional[Callable[[str], Awaitable[str]]] = None` in `EbayService.__init__` for offline unit testing.
* Implement `EbayService(eur_to_chf: float = 0.94, http_get: Optional[...] = None)`:
  1. **`build_verification_links(query: str) -> VerificationLinks`**:
     * URL-encode `query` using `urllib.parse.quote_plus(query.strip())` as `q`.
     * `ebay_sold_url`: `f"https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1"`
     * `kleinanzeigen_search_url`: `f"https://www.kleinanzeigen.de/s-{q}/k0"`
     * `idealo_url`: `f"https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}"`
     * `ricardo_search_url`: `f"https://www.ricardo.ch/de/s/{q}"`
     * `toppreise_url`: `f"https://www.toppreise.ch/produktsuche?q={q}"`
     * `digitec_url`: `f"https://www.digitec.ch/de/search?q={q}"`
  2. **`parse_sold_html(html: str, query: str, eur_to_chf: Optional[float] = None) -> EbaySoldStats`**:
     * First check if `html` is empty or a challenge page (`"splashui/challenge"` or `"Pardon Our Interruption"` in `html`); if so, return `EbaySoldStats(query=query, sample_count=0, exchange_rate=rate)`.
     * Parse eBay search result items using `BeautifulSoup(html, "lxml")`, selecting `.s-item, .s-card`.
     * Ignore placeholder items (e.g., title `"Shop on eBay"` or `"irrelevant"`) and skip price strings containing ranges (`"bis"`, `"to"`, `"-"` between two numbers).
     * Extract prices from `.s-item__price, .s-card__price` using regex matching European/German currency formats (e.g., `EUR 145,00`, `145,00 €`, `1.250,50`, `150.00`).
     * Filter out unrealistic `<= 0` prices. If $\ge 4$ prices are found, sort and apply 10% outlier trimming (`trim = max(1, int(len(prices) * 0.1))` if `len(prices) >= 5`, or drop min & max if `len(prices) >= 4` when extreme outlier ratio is detected: specifically, drop bottom 10% / top 10% or any price $< 0.2 \times \text{median}$).
     * Compute `min_eur`, `max_eur`, `median_eur = round(statistics.median(filtered), 2)`, and `median_chf = round(median_eur * rate, 2)`.
  3. **`fetch_sold_stats(query: str) -> EbaySoldStats`**:
     * Fetches `build_verification_links(query).ebay_sold_url` with timeout `8.0s` and `Accept-Language: de-DE,de;q=0.9`.
     * On any exception, logs a warning and returns `EbaySoldStats(query=query, sample_count=0, exchange_rate=self.eur_to_chf)`.

#### 4.2.2 `backend/services/ai_service.py` (With Tool + JSON Compatibility Fix)
* **Critical Gemini API Safeguard (`google_search` + JSON Output):**
  * On `google-genai`, combining `tools=[types.Tool(google_search=types.GoogleSearch())]` AND `response_mime_type="application/json"` in `GenerateContentConfig` raises `400 INVALID_ARGUMENT`.
  * **Mandatory Implementation Pattern:**
    * Implement `build_generate_config(enable_search_grounding: bool) -> types.GenerateContentConfig`:
      * When `enable_search_grounding=True`: set `tools=[types.Tool(google_search=types.GoogleSearch())]`, and ensure `response_mime_type` is `None`.
      * When `enable_search_grounding=False`: set `response_mime_type="application/json"`.
    * Implement `extract_and_parse_json(raw_text: str) -> dict`:
      * Strips markdown fences (` ```json ... ``` `) or extracts from the first `{` to the last `}` and parses via `json.loads()`.
* **Post-Processing Safeguards (`apply_post_processing_safeguards(draft: Draft) -> Draft`):**
  1. **Word-Boundary Truncation Helper (`truncate_cleanly(text: str, max_len: int) -> str`):**
     * Collapses multiple spaces, strips whitespace, and if `len(text) > max_len`, truncates at the last space $\le max\_len$ (or `text[:max_len].rstrip()` if no space).
  2. **Swiss Platforms (`draft.ricardo` & `draft.tutti`):**
     * Replace `ß` with `ss` in `ricardo.title`, `ricardo.description`, `tutti.title`, `tutti.description`, and `tutti.category_suggestion`.
     * Enforce `len(draft.ricardo.title) <= 60` and `len(draft.tutti.title) <= 80`.
     * Ensure `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme"` is present in both `ricardo.description` and `tutti.description`; if missing, append `"\n\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."`.
  3. **German Platforms (`draft.ebay_de` & `draft.kleinanzeigen`):**
     * **Preserve `ß`** (do NOT replace `ß` with `ss` in `ebay_de` or `kleinanzeigen`).
     * Enforce `len(draft.ebay_de.title) <= 80` and `len(draft.kleinanzeigen.title) <= 65`.
     * Ensure `"Ausschluss jeglicher Sachmängelhaftung"` is present in both `ebay_de.description` and `kleinanzeigen.description`; if missing, append `"\n\nDer Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."`.
* **Injectable AI Client for Deterministic Testing:**
  * Allow passing a custom `llm_callable: Optional[Callable[[List[bytes], str, EbaySoldStats], Awaitable[str | dict]]] = None` in `AIService.__init__` so unit and API tests can supply mock JSON responses without calling the live Google Gemini endpoint.
* **`analyze_draft(draft: Draft, image_service: ImageService, ebay_service: EbayService) -> Draft`:**
  1. Loads only `<image_id>_ai.jpg` bytes (`<= 1024px`, EXIF-free) for each image in `draft.images`.
  2. Runs a quick product query derivation (or uses `draft.user_notes` / identified product) to fetch `ebay_stats = await ebay_service.fetch_sold_stats(query)` and `verification_links = ebay_service.build_verification_links(identified_product_or_query)`.
  3. Calls Gemini (or `llm_callable`) with the AI images, `user_notes`, and `ebay_stats`.
  4. Parses the JSON response, populates `draft.identified_product`, `draft.missing_photo_hints`, `draft.price_analysis`, `draft.ricardo`, `draft.tutti`, `draft.ebay_de`, and `draft.kleinanzeigen`.
  5. Calls `apply_post_processing_safeguards(draft)` and sets `draft.status = DraftStatus.READY`.

#### 4.2.3 Phase 2 Automated Acceptance Criteria (`tests/test_phase2_pricing_and_ai.py`)
Write automated `pytest` tests verifying:
1. **`test_ebay_sold_html_parser_and_currency_conversion`**: Feed realistic eBay.de HTML containing sold items (`EUR 150,00`, `EUR 160,00`, `EUR 170,00`, plus a `EUR 1,00` outlier and a `"EUR 100,00 bis EUR 200,00"` range item) into `parse_sold_html()`. Assert range items and outliers are excluded, `median_eur == 160.0`, and `median_chf == round(160.0 * 0.94, 2)`. Also verify challenge HTML (`splashui/challenge`) returns `sample_count == 0` gracefully.
2. **`test_verification_links_generation`**: Verify `build_verification_links("Sony WH-1000XM4")` produces valid URLs containing `LH_Sold=1&LH_Complete=1` for `ebay.de`, plus URLs for `kleinanzeigen.de`, `idealo.de`, `ricardo.ch`, `toppreise.ch`, and `digitec.ch`.
3. **`test_ai_json_extractor_and_grounding_config_compatibility`**: Verify that when `enable_search_grounding=True`, `build_generate_config(True)` sets `google_search` tool and does NOT set `response_mime_type="application/json"`, and `extract_and_parse_json()` cleanly parses JSON wrapped in ` ```json ... ``` ` fences and preamble text.
4. **`test_ai_post_processing_safeguards_ch_and_de`**:
   * Pass a mock AI response containing:
     * A 75-character Ricardo title with `ß` (e.g. `"Großartiger..."`) and a description missing the Swiss warranty disclaimer.
     * A 95-character eBay.de title and an 80-character Kleinanzeigen.de title containing valid German `ß` (e.g. `"Größe XL weiß"`), with descriptions missing the German BGB Sachmängelhaftung disclaimer.
   * Assert the service:
     * Truncates `ricardo.title` to $\le 60$ chars, `tutti.title` to $\le 80$ chars, `ebay_de.title` to $\le 80$ chars, and `kleinanzeigen.title` to $\le 65$ chars.
     * Replaces `ß` with `ss` in `ricardo` and `tutti`, while **preserving `ß`** in `ebay_de` and `kleinanzeigen`.
     * Appends `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."` to `ricardo` and `tutti`, and appends `"Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."` to `ebay_de` and `kleinanzeigen`.
5. **`test_iterative_reanalysis_preserves_draft_id_and_updates_hints`**: Create a draft with 1 photo, run mocked AI analysis returning `missing_photo_hints=["Bitte Typenschild fotografieren"]`, upload a 2nd photo to the same draft, re-run AI analysis, and verify the existing draft ID is preserved and updated in-place across all 4 platform listings.
* **Phase 2 Commit:** `feat(phase2): add hybrid eBay DE parser and Gemini AI service with safeguards`

---

### PHASE 3: FastAPI REST API & Local Web Dashboard (`Seller Assistant`)

#### 4.3.1 REST API Specification (`backend/main.py`)
Configure `CORSMiddleware` with `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]`.
Provide a factory `create_app(...)` (and module-level `app = create_app()`) so tests can override `StorageService`, `ImageService`, `EbayService`, and `AIService` cleanly.

Implement the following exact endpoints:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Returns `{"status": "ok", "model": settings.gemini_model}` |
| `GET` | `/api/settings` | Returns `PresetSettings` (with CH & DE shipping presets) |
| `PUT` | `/api/settings` | Updates and persists `PresetSettings` |
| `GET` | `/api/drafts` | Returns `List[Draft]` (all saved drafts) |
| `POST` | `/api/drafts` | Creates a new empty `Draft` (accepts optional body `{"user_notes": "..."}`) |
| `GET` | `/api/drafts/{draft_id}` | Returns a single `Draft` (HTTP 404 if not found) |
| `PUT` | `/api/drafts/{draft_id}` | Updates a `Draft` (accepts full or partial draft payload; enforces title length limits $\le 60 / 80 / 80 / 65$) |
| `DELETE` | `/api/drafts/{draft_id}` | Deletes draft and its image files (`{"deleted": True}`) |
| `POST` | `/api/drafts/{draft_id}/images` | Multipart upload (`files: List[UploadFile]`). Processes each image (`optimized` + `ai` variants) and appends to `draft.images` |
| `DELETE` | `/api/drafts/{draft_id}/images/{image_id}` | Removes a specific image from the draft |
| `PATCH` | `/api/drafts/{draft_id}/images/{image_id}` | Body `{"active_mode": "optimized" \| "blurred" \| "cutout"}`. Generates variant if not cached yet and updates `active_mode` |
| `GET` | `/api/drafts/{draft_id}/images/{image_id}/{variant}` | Serves the `.jpg` file (`optimized`, `blurred`, `cutout`, or `active` which resolves to `img.active_mode`) with `media_type="image/jpeg"` |
| `POST` | `/api/drafts/{draft_id}/analyze` | Runs Hybrid Price Engine (eBay DE + Gemini Search Grounding) on the draft's current images & `user_notes`, updates `draft` (CH & DE listings) and sets `status="ready"` |

#### 4.3.2 Local Web Dashboard UI (`frontend/index.html`, `frontend/app.js`, `frontend/styles.css`)
Serve `frontend/` at `/` via FastAPI `StaticFiles`.
* **Mandatory Neutral Naming (`AGENTS.md` Rule 6):** The `<title>` and main header `<h1>` of `frontend/index.html` MUST be **`Seller Assistant`** (never put platform names in the application title or main header).

Include the following exact DOM IDs in `frontend/index.html`:
1. **Left Sidebar – Multi-Draft List:**
   * `"Neues Inserat (+)"` button (`id="btn-new-draft"`).
   * Draft list container (`id="draft-list"`).
2. **Main Area – Section 1: Input & Images:**
   * Drag-and-drop upload zone (`id="dropzone"`) and `<input type="file" id="file-input" multiple accept=".jpg,.jpeg,.png,.webp,.heic">`.
   * Image gallery (`id="image-gallery"`): Each card shows preview + 3 mode buttons (`optimized`, `blurred`, `cutout`) + delete button.
   * User notes `<textarea id="user-notes">`, CH Shipping Preset `<select id="shipping-preset">`, DE Shipping Preset `<select id="de-shipping-preset">`, Offer Type `<select id="offer-type">`.
   * Primary button: `"KI-Analyse & Preisrecherche starten"` (`id="btn-analyze"`).
3. **Main Area – Section 2: Quality Hints & Hybrid Price Analysis (CH & DE):**
   * Missing photo hints alert box (`id="missing-hints-box"`).
   * Price summary container (`id="price-summary"`): Displays eBay DE Sold Median (EUR & CHF), DE New Price (EUR), CH New Price (CHF), Recommended CH Prices (`ricardo_start_chf`, `ricardo_buynow_chf`, `tutti_vhb_chf`), Recommended DE Prices (`ebay_start_eur`, `ebay_buynow_eur`, `kleinanzeigen_vb_eur`), and `reasoning`.
   * 1-Click Verification Links bar (`id="verification-links"`): Links for `ebay_sold_url`, `kleinanzeigen_search_url`, `idealo_url`, `ricardo_search_url`, `toppreise_url`, and `digitec_url`.
4. **Main Area – Section 3: Editable Platform Previews (CH & DE):**
   * **Ricardo.ch Card (CHF):**
     * `<input id="ricardo-title" maxlength="60">`, `<span id="ricardo-title-count">0/60</span>`, `<select id="ricardo-condition">`, `<input type="number" id="ricardo-start-price">`, `<input type="number" id="ricardo-buynow-price">`, `<textarea id="ricardo-description">`.
   * **Tutti.ch Card (CHF):**
     * `<input id="tutti-title" maxlength="80">`, `<span id="tutti-title-count">0/80</span>`, `<input id="tutti-category">`, `<select id="tutti-condition">`, `<input type="number" id="tutti-price">`, `<textarea id="tutti-description">`.
   * **eBay.de Card (EUR):**
     * `<input id="ebay-de-title" maxlength="80">`, `<span id="ebay-de-title-count">0/80</span>`, `<input id="ebay-de-category">`, `<select id="ebay-de-condition">`, `<select id="ebay-de-offer-type">`, `<input type="number" id="ebay-de-start-price">`, `<input type="number" id="ebay-de-buynow-price">`, `<textarea id="ebay-de-description">`.
   * **Kleinanzeigen.de Card (EUR):**
     * `<input id="kleinanzeigen-title" maxlength="65">`, `<span id="kleinanzeigen-title-count">0/65</span>`, `<input id="kleinanzeigen-category">`, `<select id="kleinanzeigen-condition">`, `<input type="number" id="kleinanzeigen-price">`, `<select id="kleinanzeigen-price-type">`, `<textarea id="kleinanzeigen-description">`.
   * Save button (`id="btn-save-draft"`) & Status `<select id="draft-status">`.

#### 4.3.3 Phase 3 Automated Acceptance Criteria (`tests/test_phase3_api_and_ui.py`)
Write automated `pytest` tests using `fastapi.testclient.TestClient`:
1. **`test_full_rest_lifecycle`**: `POST /api/drafts` $\rightarrow$ `POST /api/drafts/{id}/images` (upload 2 test images) $\rightarrow$ `PATCH` image 1 to `blurred` $\rightarrow$ `GET /api/drafts/{id}/images/{img_id}/active` (assert HTTP 200 and `image/jpeg`) $\rightarrow$ `POST /api/drafts/{id}/analyze` (with mocked AI/eBay services) $\rightarrow$ `PUT /api/drafts/{id}` (manual title edits exceeding limits on `ricardo`, `ebay_de`, and `kleinanzeigen`; assert response truncates `ricardo` to $\le 60$, `ebay_de` to $\le 80$, and `kleinanzeigen` to $\le 65$ chars) $\rightarrow$ `DELETE /api/drafts/{id}`.
2. **`test_dashboard_static_html_served_and_contains_required_elements`**: `GET /` returns HTTP 200, neutral title `Seller Assistant` (without third-party marketplace names in `<title>` or `<h1>`), and HTML containing `#btn-new-draft`, `#dropzone`, `#btn-analyze`, `#ricardo-title`, `#tutti-title`, `#ebay-de-title`, `#kleinanzeigen-title`, and `#verification-links`.
* **Phase 3 Commit:** `feat(phase3): implement FastAPI endpoints and local web dashboard UI`

---

### PHASE 4: Firefox WebExtension (Manifest V3) with Smart-Panel & Xray Vision Compatibility

#### 4.4.1 `extension/manifest.json`
*(Strictly uses neutral naming `Seller Assistant` per `AGENTS.md` Rule 6, while declaring host permissions and content script matches for all 4 supported marketplaces.)*
```json
{
  "manifest_version": 3,
  "name": "Seller Assistant",
  "version": "1.1.0",
  "description": "Smart-Panel und Schritt-für-Schritt Auto-Fill für Online-Marktplätze",
  "permissions": ["storage", "activeTab"],
  "host_permissions": [
    "http://127.0.0.1:8000/*",
    "http://localhost:8000/*",
    "*://*.ricardo.ch/*",
    "*://*.tutti.ch/*",
    "*://*.ebay.de/*",
    "*://*.kleinanzeigen.de/*"
  ],
  "action": {
    "default_title": "Seller Assistant (Berechtigungen prüfen)"
  },
  "background": {
    "scripts": ["background.js"]
  },
  "content_scripts": [
    {
      "matches": [
        "*://*.ricardo.ch/*",
        "*://*.tutti.ch/*",
        "*://*.ebay.de/*",
        "*://*.kleinanzeigen.de/*"
      ],
      "js": ["content.js"],
      "css": ["panel.css"],
      "run_at": "document_idle"
    }
  ],
  "browser_specific_settings": {
    "gecko": {
      "id": "seller-assistant@local.dev",
      "strict_min_version": "109.0"
    }
  }
}
```

#### 4.4.2 Background Worker & Host Permission Helper (`extension/background.js`)
* **Firefox MV3 Host Permissions Safeguard:**
  * Register an `action.onClicked` listener in `background.js` that calls:
    ```javascript
    permissions.request({
      origins: [
        "http://127.0.0.1:8000/*",
        "http://localhost:8000/*",
        "*://*.ricardo.ch/*",
        "*://*.tutti.ch/*",
        "*://*.ebay.de/*",
        "*://*.kleinanzeigen.de/*"
      ]
    })
    ```
* **Message Bus Contract:**
  `background.js` listens via `(globalThis.browser || globalThis.chrome).runtime.onMessage.addListener` and handles three action types:
  1. **`{ action: "LIST_DRAFTS" }`**: Fetches `GET http://127.0.0.1:8000/api/drafts` $\rightarrow$ `{ ok: true, drafts: [...] }` or `{ ok: false, error: "..." }`.
  2. **`{ action: "GET_DRAFT", draftId: "<id>" }`**: Fetches `GET http://127.0.0.1:8000/api/drafts/<id>` $\rightarrow$ `{ ok: true, draft: {...} }`.
  3. **`{ action: "FETCH_DRAFT_IMAGES", draftId: "<id>" }`**: Fetches draft metadata, then fetches each image's `/api/drafts/<id>/images/<img_id>/active` binary endpoint, converts the `ArrayBuffer` to Base64 Data URL (`data:image/jpeg;base64,...`), and returns `{ ok: true, images: [{ id, filename: "<id>_<mode>.jpg", mimeType: "image/jpeg", dataUrl: "data:image/jpeg;base64,..." }] }`.

#### 4.4.3 Smart-Panel, Platform Detection, React/Rich-Text Setter & Firefox Xray-Safe File Injector (`extension/content.js`)
Implement `content.js` so it works both in Firefox and in a Node/JSDOM test environment (export helper functions via `if (typeof module !== "undefined" && module.exports)`):

1. **Marketplace Detection (`detectPlatform(hostname)`):**
   * Returns:
     * `"ricardo"` if `hostname.includes("ricardo.ch")`
     * `"tutti"` if `hostname.includes("tutti.ch")`
     * `"ebay_de"` if `hostname.includes("ebay.de")`
     * `"kleinanzeigen"` if `hostname.includes("kleinanzeigen.de")`
   * Maps the active draft to the corresponding platform listing object (`draft.ricardo`, `draft.tutti`, `draft.ebay_de`, or `draft.kleinanzeigen`) and currency (`CHF` vs. `EUR`).

2. **React/Next.js/Marko Native Value Setter (`setNativeValue(element, value)`):**
   * Unwrap target element if needed (`const rawEl = element.wrappedJSObject || element;`) and look up the native value setter on `HTMLInputElement.prototype` / `HTMLTextAreaElement.prototype` / `HTMLSelectElement.prototype` (checking both `window.wrappedJSObject` and `window`).
   * Call `setter.call(element, value)`.
   * Dispatch `new Event("input", { bubbles: true })`, `new Event("change", { bubbles: true })`, and `new Event("blur", { bubbles: true })`.

3. **Rich-Text / `iframe` / `contenteditable` Description Setter (`setDescriptionValue(value, doc)`):**
   * **Technical Safeguard (eBay.de `/lstng` Description Editor):** On `ebay.de`, the item description editor is rendered either as a standard `<textarea>` (when HTML view is active) or inside a same-origin `<iframe>` (e.g., `iframe.ux-action-menu__iframe`, `iframe[id*="desc" i]`, `iframe[title*="Beschreibung" i]`) whose internal document contains a `[contenteditable="true"]` or `body` element.
   * `setDescriptionValue(value, doc = document)` must check:
     1. Standard `<textarea>` matching platform selectors $\rightarrow$ call `setNativeValue(textarea, value)`.
     2. Same-origin editor `<iframe>` $\rightarrow$ access `iframe.contentDocument || iframe.contentWindow?.document`, find `.editable-text-area, [contenteditable="true"], body`, set `innerHTML` (escaping HTML entities and converting `\n` to `<br>`), and dispatch `input`, `change`, and `blur` events.
     3. Direct `[contenteditable="true"]` element in the main document $\rightarrow$ set `innerText = value` and dispatch `input` and `blur` events.

4. **Firefox Xray-Safe Image File Injector (`injectFilesIntoInput(fileInput, imagePayloads)`):**
   * Construct `DataTransfer` and `File` using the page compartment (`const pageWin = (typeof window !== "undefined" && window.wrappedJSObject) ? window.wrappedJSObject : window;`) and use `cloneInto` when available in Firefox:
     ```javascript
     const pageWin = (typeof window !== "undefined" && window.wrappedJSObject) ? window.wrappedJSObject : window;
     const DataTransferCtor = pageWin.DataTransfer || DataTransfer;
     const FileCtor = pageWin.File || File;
     const dt = new DataTransferCtor();
     for (const img of imagePayloads) {
       const bytes = dataUrlToUint8Array(img.dataUrl);
       const pageBytes = typeof cloneInto === "function" ? cloneInto(bytes, window) : bytes;
       const opts = typeof cloneInto === "function" ? cloneInto({ type: img.mimeType }, window) : { type: img.mimeType };
       const file = new FileCtor([pageBytes], img.filename, opts);
       dt.items.add(file);
     }
     const targetInput = fileInput.wrappedJSObject || fileInput;
     targetInput.files = dt.files;
     fileInput.dispatchEvent(new Event("input", { bubbles: true }));
     fileInput.dispatchEvent(new Event("change", { bubbles: true }));
     ```
   * Also dispatch a synthetic `drop` event (`new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt })`) on the closest dropzone container if present.

5. **Platform-Specific DOM Selector Cascades:**
   * **Ricardo.ch (`ricardo`):**
     * Title: `input[name*="title" i]`, `#title`, `input[data-testid*="title" i]`
     * Description: `textarea[name*="description" i]`, `#description`
     * Prices: Start price (`input[name*="startPrice" i]`, `input[name*="startingPrice" i]`, `input[name*="price" i]`), Buy-Now price (`input[name*="buyNow" i]`, `input[name*="instantPrice" i]`)
   * **Tutti.ch (`tutti`):**
     * Title: `input[name="subject"]`, `input[name*="title" i]`, `#title`
     * Description: `textarea[name="body"]`, `textarea[name*="description" i]`
     * Price: `input[name="price"]`, `input[name*="price" i]`
   * **eBay.de (`ebay_de`):**
     * Title: `input[name="title"]`, `input[id*="title" i]`, `input[aria-label*="Titel" i]`, `input[placeholder*="Titel" i]`
     * Description: `textarea[name*="description" i]`, `iframe.ux-action-menu__iframe`, `iframe[id*="desc" i]`, `iframe[title*="Beschreibung" i]`, `[contenteditable="true"]`
     * Prices: Start price (`input[name*="startPrice" i]`, `input[aria-label*="Startpreis" i]`), Buy-Now price (`input[name*="buyItNowPrice" i]`, `input[name="price"]`, `input[aria-label*="Sofort-Kaufen" i]`, `input[aria-label*="Preis" i]`)
   * **Kleinanzeigen.de (`kleinanzeigen`):**
     * Title: `#postad-title`, `#pstad-title`, `input[name="title"]`, `input[name="pstad-title"]`
     * Description: `#pstad-descrptn`, `#pstad-descr`, `textarea[name="description"]`, `textarea[name="pstad-descrptn"]`
     * Price & Type: `#pstad-price`, `input[name="price"]`, `input[name="priceType"]`, `select[name="priceType"]`

6. **Smart-Panel UI:**
   * Inject floating widget (`#ai-listing-smart-panel`) with neutral header **`Seller Assistant`** at bottom-right of `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de`.
   * Contains:
     * **Active Platform Badge (`#ai-ext-platform-badge`):** Shows detected marketplace & currency (`Ricardo.ch (CHF)`, `Tutti.ch (CHF)`, `eBay.de (EUR)`, `Kleinanzeigen.de (EUR)`).
     * **Draft Selector Dropdown** (`#ai-ext-draft-select`) + Refresh button.
     * **Wizard Step 1 Button (`#ai-ext-step1-btn`):** *"Schritt 1: Bilder & Titel einfügen"* — injects active images into `<input type="file">` and fills the Title field for the active platform (`ricardo` 60-char, `tutti` 80-char, `ebay_de` 80-char, or `kleinanzeigen` 65-char title).
     * **Wizard Step 2 Button (`#ai-ext-step2-btn`):** *"Schritt 2: Beschreibung & Preis einfügen"* — fills the Description field (via `setDescriptionValue`), Condition selector, and Price inputs (CHF on Ricardo/Tutti; EUR on eBay.de/Kleinanzeigen.de).
     * **1-Click Copy Fallback Section:** Displays the selected draft's platform-specific Title, Description, Category Suggestion, and Prices with a `"Kopieren"` button (`navigator.clipboard.writeText(...)`) next to each item.

#### 4.4.4 Phase 4 Automated Acceptance Criteria (`tests/test_phase4_extension.py`)
Write automated `pytest` tests verifying:
1. **`test_manifest_v3_validity_and_neutral_naming`**: Parse `extension/manifest.json`, assert `manifest_version == 3`, assert `name == "Seller Assistant"` (and verify no third-party marketplace names appear in `name` or `action.default_title`), verify `background.scripts` contains `background.js`, verify `host_permissions` and `content_scripts[0].matches` include `127.0.0.1:8000` (in `host_permissions`), `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de`, and verify all referenced files (`background.js`, `content.js`, `panel.css`) exist.
2. **`test_extension_js_syntax_and_xray_and_cors_safeguards`**:
   * Run `node --check extension/background.js` and `node --check extension/content.js` to assert zero JS syntax errors.
   * Assert `content.js` does NOT contain `fetch("http://127.0.0.1` or `fetch("http://localhost` (enforcing that all backend communication uses `runtime.sendMessage` to `background.js`).
   * Assert `background.js` handles `LIST_DRAFTS`, `GET_DRAFT`, and `FETCH_DRAFT_IMAGES`.
   * Assert `content.js` implements `detectPlatform` supporting `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de`, `setDescriptionValue` (with `iframe` / `contenteditable` support), `wrappedJSObject` Xray unwrap support, `setNativeValue`, `DataTransfer` file injection, `#ai-ext-step1-btn`, `#ai-ext-step2-btn`, and clipboard copy fallbacks.
* **Phase 4 Commit:** `feat(phase4): add Firefox MV3 extension with background proxy and smart-panel`

---

## 5. Final Verification & Acceptance Runbook

After completing all 4 phases, the implementing agent must run:

```bash
.venv/bin/pytest -v
git status
```

### Definition of Done (All checks must pass before finishing):
- [x] `.venv/bin/pytest -v` passes 100% of tests across all 4 test files (`test_phase1_image_and_storage.py`, `test_phase2_pricing_and_ai.py`, `test_phase3_api_and_ui.py`, `test_phase4_extension.py`) with 0 failures and 0 errors.
- [x] Starting the server via `.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000` serves the dashboard at `http://127.0.0.1:8000/` and OpenAPI docs at `http://127.0.0.1:8000/docs`.
- [x] All EXIF/GPS metadata is stripped from uploaded images and AI-bound images are capped at `1024x1024` pixels.
- [x] Platform-specific constraints are enforced:
  - **Ricardo.ch:** Title $\le 60$ chars, `ss` orthography, prices in CHF, Swiss warranty disclaimer.
  - **Tutti.ch:** Title $\le 80$ chars, `ss` orthography, prices in CHF, Swiss warranty disclaimer.
  - **eBay.de:** Title $\le 80$ chars, standard German (`ß`), prices in EUR, German BGB Sachmängelhaftung disclaimer.
  - **Kleinanzeigen.de:** Title $\le 65$ chars, standard German (`ß`), prices in EUR (VB/Festpreis), German BGB Sachmängelhaftung disclaimer.
- [x] User-facing project, dashboard, and extension names strictly use the neutral title **`Seller Assistant`**.
- [x] Working tree (`git status`) is clean with all changes committed.
