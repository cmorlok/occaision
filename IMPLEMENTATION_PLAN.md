# Implementation Plan & Specification: Seller Assistant

> **Target Audience:** Implementing Software Engineering LLM / Developer  
> **Reference Requirements:** `REQUIREMENTS.md`  
> **Engineering Rules:** `AGENTS.md`  
> **Architecture:** Local Python FastAPI Backend (`127.0.0.1:8000`) + Local Web Dashboard + Firefox WebExtension (Manifest V3)  
> **Supported Marketplaces:** Switzerland (`ricardo.ch`, `tutti.ch`) & Germany (`ebay.de`, `kleinanzeigen.de`)

---

## 1. Instructions for the Implementing LLM

> **MANDATORY:** Read and follow all engineering rules in `AGENTS.md` before writing a single line of code.

1. **Strict Incremental TDD Loop (Env Setup $\rightarrow$ Test First $\rightarrow$ Implement $\rightarrow$ Test $\rightarrow$ Fix $\rightarrow$ Commit):**
   * **Never** implement multiple phases or the whole codebase before running tests.
   * First complete **Phase 0 (Development Environment Setup)** and verify `pytest --version` and `node --version` work.
   * For each subsequent phase (Phase 1 to Phase 4), follow this exact loop:
     1. **Write Tests First (RED):** Implement `tests/test_phaseX_*.py` based on the phase's Acceptance Criteria.
     2. **Run `pytest`:** Verify the new tests fail for the expected reason.
     3. **Implement Production Code:** Write the phase's modules cleanly and modularly.
     4. **Test & Fix Loop (GREEN):** Run `.venv/bin/pytest -v` (running the **entire** test suite to catch regressions). Fix any errors one by one until 100% of tests pass.
     5. **No Test Cheating:** Never delete, skip, or weaken assertions in a test to make it pass.
     6. **Git Commit:** Once `.venv/bin/pytest -v` is 100% green for the phase, check `git status` and create a clean Conventional Commit (`feat(phaseX): ...`) before starting the next phase.
2. **Do Not Guess Contracts:** Use the exact file paths, Pydantic schemas, REST endpoint routes, DOM IDs, and extension message payloads specified in this document.
3. **Offline/Deterministic Testability:** Every external dependency (Google Gemini API, eBay.de HTTP requests, `rembg` neural network inference) MUST be injectable or mockable so the entire `pytest` suite runs deterministically in < 10 seconds without requiring live internet, a live API key, or a 176 MB ONNX download during unit tests.
4. **Hard Constraints to Enforce in Code:**
   - **Neutral Naming (`AGENTS.md` Rule 6):** Never use third-party marketplace names in project titles, extension titles (`manifest.json`), dashboard main headers, or build artifact names. The canonical name is **`Seller Assistant`** (slug: `seller-assistant`).
   - **Privacy:** Never send original full-resolution or EXIF-containing images to the Gemini API. Always strip EXIF/GPS metadata first and downscale to max `1024x1024` px before calling Gemini.
   - **Title Length Limits:**
     - **Ricardo.ch:** Strictly $\le 60$ characters.
     - **Tutti.ch:** Strictly $\le 80$ characters.
     - **eBay.de:** Strictly $\le 80$ characters.
     - **Kleinanzeigen.de:** Strictly $\le 65$ characters.
   - **Platform-Dependent Orthography:**
     - **Swiss Platforms (`ricardo`, `tutti`):** Replace `ß` with `ss` in all generated titles and descriptions.
     - **German Platforms (`ebay_de`, `kleinanzeigen`):** Preserve standard German orthography (including `ß`).
   - **Platform-Dependent Legal Disclaimers:**
     - **Swiss Platforms (`ricardo`, `tutti`):** Every description must contain the Swiss private sale warranty disclaimer: `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."`
     - **German Platforms (`ebay_de`, `kleinanzeigen`):** Every description must contain the German/EU BGB private sale disclaimer: `"Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."`
   - **CORS / CSP Bypass in Extension:** The Firefox Content Script (`content.js`) must **NEVER** call `fetch("http://127.0.0.1:8000/...")` directly. All HTTP calls to the local backend must happen inside `background.js` via `browser.runtime.onMessage` / `chrome.runtime.onMessage`.

---

## 2. Phase 0: Development Environment & Repository Setup

Before writing application code, set up a clean, reproducible development environment.

### 2.1 System Prerequisites (Linux / Debian / Ubuntu / macOS)
Ensure the following OS-level packages are present (required by `rembg`/`opencv-python-headless`, `pillow-heif`, and JS syntax verification):

```bash
# On Debian/Ubuntu Linux:
sudo apt-get update && sudo apt-get install -y \
    python3 python3-venv python3-pip python3-dev \
    libgl1 libglib2.0-0 libheif-dev \
    nodejs
```

*(Note: **Python 3.11 or 3.12** is strongly recommended so `onnxruntime` and `numba`/`pymatting` install from prebuilt binary wheels without source compilation.)*

### 2.2 Python Virtual Environment Setup
Create an isolated virtual environment in `.venv` (which is gitignored):

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -r requirements.txt
```

### 2.3 Repository Structure
Create the following project structure in the workspace root:

```text
/
├── .env.example
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
│   ├── config.py                # Settings loaded from .env
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
│   ├── content.js               # Smart-Panel UI, platform detector (CH/DE), Xray-safe File injector, React setter
│   └── panel.css                # Isolated CSS for the floating Smart-Panel on ricardo.ch, tutti.ch, ebay.de, kleinanzeigen.de
└── tests/
    ├── conftest.py              # Shared pytest fixtures (temp data dir, synthetic EXIF images, mock HTML)
    ├── test_phase1_image_and_storage.py
    ├── test_phase2_pricing_and_ai.py
    ├── test_phase3_api_and_ui.py
    └── test_phase4_extension.py
```

### 2.4 `requirements.txt`
Use these exact package specifications to avoid known dependency/wheel issues:
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

### 2.5 `.env.example`
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

---

## 3. Data Models & Schemas (`backend/models.py`)

Implement the following exact Pydantic v2 models in `backend/models.py`:

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
    label: str                # e.g., "B-Post Paket bis 2 kg (8.50 CHF)" or "DHL Paket bis 2 kg (5.49 EUR)"
    cost: float               # Cost in local currency (CHF for CH, EUR for DE)
    currency: str = "CHF"     # "CHF" or "EUR"
    pickup_allowed: bool = True

class PresetSettings(BaseModel):
    default_offer_type: OfferType = OfferType.AUCTION
    default_shipping_preset_id: str = "b_post_2kg"
    default_de_shipping_preset_id: str = "dhl_2kg"
    shipping_presets: List[ShippingPreset] = Field(default_factory=lambda: [
        # Swiss Presets (CHF)
        ShippingPreset(id="b_post_2kg", country=MarketCountry.CH, label="Paket B-Post bis 2 kg (8.50 CHF)", cost=8.50, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="b_post_10kg", country=MarketCountry.CH, label="Paket B-Post bis 10 kg (11.50 CHF)", cost=11.50, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="grossbrief", country=MarketCountry.CH, label="Grossbrief B-Post (2.00 CHF)", cost=2.00, currency="CHF", pickup_allowed=True),
        ShippingPreset(id="pickup_only", country=MarketCountry.CH, label="Nur Abholung vor Ort CH (0.00 CHF)", cost=0.00, currency="CHF", pickup_allowed=True),
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
* Implement a clean repository class `StorageService(data_dir: Path)`:
  * `list_drafts() -> List[Draft]` (sorted by `updated_at` descending).
  * `get_draft(draft_id: str) -> Optional[Draft]`.
  * `create_draft(user_notes: str = "") -> Draft` (pre-populates default `offer_type`, `shipping_preset_id` for CH, and `default_de_shipping_preset_id` for DE from `PresetSettings`).
  * `update_draft(draft: Draft) -> Draft` (enforces `len(draft.ricardo.title) <= 60`, `len(draft.tutti.title) <= 80`, `len(draft.ebay_de.title) <= 80`, and `len(draft.kleinanzeigen.title) <= 65`, updates `updated_at` ISO timestamp, saves atomically via temp file rename).
  * `delete_draft(draft_id: str) -> bool` (removes draft from `drafts.json` and deletes `data/images/<draft_id>/`).
  * `get_settings() -> PresetSettings` and `update_settings(settings: PresetSettings) -> PresetSettings`.

#### 4.1.2 `backend/services/image_service.py`
* Register HEIC opener at module import:
  ```python
  import pillow_heif
  pillow_heif.register_heif_opener()
  ```
* **Performance Safeguard (`rembg` ONNX Session Reuse):**
  * Calling `rembg.remove(img)` without a `session` reloads the ONNX model from disk on *every single image* (taking 4–6 seconds and violating the `< 3s` requirement).
  * `ImageService` MUST lazily initialize and cache a single `self._rembg_session = rembg.new_session(model_name)` (default `"u2netp"` or `"u2net"` from `REMBG_MODEL` config) and pass `session=self._rembg_session` to `rembg.remove(img, session=self._rembg_session)`.
  * *Testability requirement:* Allow injecting a custom `mask_extractor: Optional[Callable[[Image.Image], Image.Image]] = None` in `ImageService.__init__` so unit tests run in milliseconds without downloading the ONNX weights.
* Implement `ImageService` pipeline steps:
  1. **Orientation & EXIF Stripping (`clean_and_orient(raw_bytes: bytes) -> Image.Image`):**
     * Open image with `PIL.Image.open(io.BytesIO(raw_bytes))`.
     * Call `ImageOps.exif_transpose(img)` FIRST so smartphone portrait photos are rotated upright.
     * Convert to `RGB` mode.
     * Create a brand new `Image.new("RGB", img.size)` and paste pixel data so **zero EXIF/GPS/camera metadata remains**.
  2. **Default Optimized Variant (`create_optimized_variant(clean_img: Image.Image) -> Image.Image`):**
     * Apply subtle auto-contrast: `ImageOps.autocontrast(clean_img, cutoff=0.5)`.
     * Limit max dimension to `2048px` (`thumbnail((2048, 2048), Image.Resampling.LANCZOS)`).
     * Save as `<image_id>_optimized.jpg` (JPEG quality=90, no EXIF).
  3. **AI Input Downscaled Variant (`create_ai_input_variant(clean_img: Image.Image) -> bytes`):**
     * Copy `clean_img`, resize via `thumbnail((1024, 1024), Image.Resampling.LANCZOS)`.
     * Save as `<image_id>_ai.jpg` (JPEG quality=85, no EXIF). Never exceed `1024px` on either axis.
  4. **On-Demand / Cached Cutout Variant (`get_or_create_cutout(draft_id, image_id)`):**
     * Extract RGBA foreground via `self.extract_foreground(optimized_img)`.
     * Composite foreground onto a clean neutral light-gray/white canvas `Image.new("RGB", rgba.size, (248, 249, 250))`.
     * Save to `<image_id>_cutout.jpg`.
  5. **On-Demand / Cached Background Blur Variant (`get_or_create_blurred(draft_id, image_id)`):**
     * Extract RGBA foreground via `self.extract_foreground(optimized_img)`.
     * Take `optimized_img`, apply `ImageFilter.GaussianBlur(radius=18)` to create blurred background.
     * Composite the sharp foreground over the blurred background using the alpha channel as mask: `Image.composite(optimized_img, blurred_bg, rgba.split()[3])`.
     * Save to `<image_id>_blurred.jpg`.

#### 4.1.3 Phase 1 Automated Acceptance Criteria (`tests/test_phase1_image_and_storage.py`)
Write automated `pytest` tests verifying:
1. **`test_exif_and_gps_completely_stripped`**: Create a synthetic JPEG containing EXIF tags (Make, Model, GPSInfo), process it through `ImageService.process_upload()`, reload the saved `<image_id>_optimized.jpg` and `<image_id>_ai.jpg`, and assert `len(img.getexif()) == 0`.
2. **`test_ai_image_downscaled_to_max_1024px`**: Upload a `3000x2000` image and assert `<image_id>_ai.jpg` has dimensions `1024x683` ($\le 1024$ on both axes), while `<image_id>_optimized.jpg` is `2048x1365`.
3. **`test_heic_upload_converted_to_jpg`**: Generate an in-memory HEIF/HEIC image via `pillow_heif`, pass it to `process_upload()`, and assert it succeeds and outputs valid RGB `.jpg` files.
4. **`test_cutout_and_blur_generation`**: Process an image and trigger `cutout` and `blurred` modes; assert both `.jpg` files exist on disk, match the optimized image dimensions, and have RGB mode.
5. **`test_multi_draft_crud_persistence`**: Create 3 drafts, update status and titles across CH and DE listings (`ricardo`, `tutti`, `ebay_de`, `kleinanzeigen`), re-instantiate `StorageService` from disk, assert all 3 drafts persist in order with CH and DE presets intact, and verify deleting a draft removes both the JSON entry and its image folder.

---

### PHASE 2: Hybrid Price Engine & Gemini AI Service (CH & DE)

#### 4.2.1 `backend/services/ebay_service.py` (With TLS-Fingerprint Bypass)
* **Technical Reality & Safeguard:**
  * Standard Python `httpx` or `requests` calls to `ebay.de` are frequently blocked by eBay's anti-bot TLS/JA3 fingerprinting (returning a `splashui/challenge` CAPTCHA page or `403`/`503`).
  * Therefore, `fetch_sold_stats()` MUST use **`curl_cffi.requests.AsyncSession(impersonate="chrome")`** (with fallback to `httpx` if `curl_cffi` is unavailable) so the TLS handshake and HTTP/2 frame fingerprint match a real Chrome browser.
* Implement `EbayService`:
  1. **`build_verification_links(query: str) -> VerificationLinks`**:
     * URL-encode `query` as `q`.
     * `ebay_sold_url`: `https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1`
     * `kleinanzeigen_search_url`: `https://www.kleinanzeigen.de/s-{q}/k0`
     * `idealo_url`: `https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}`
     * `ricardo_search_url`: `https://www.ricardo.ch/de/s/{q}`
     * `toppreise_url`: `https://www.toppreise.ch/produktsuche?q={q}`
     * `digitec_url`: `https://www.digitec.ch/de/search?q={q}`
  2. **`parse_sold_html(html: str, query: str, eur_to_chf: float = 0.94) -> EbaySoldStats`**:
     * First check if `html` is a challenge page (`"splashui/challenge"` or `"Pardon Our Interruption"` in `html`); if so, return `EbaySoldStats(query=query, sample_count=0)`.
     * Parse eBay search result items using `BeautifulSoup(html, "lxml")`, supporting both `.s-item` and `.s-card` item containers.
     * Ignore placeholder items (e.g., title `"Shop on eBay"` or price ranges containing `"bis"` / `"to"`).
     * Extract prices from `.s-item__price` / `.s-card__price` using regex matching German/European currency formats (`EUR 145,00`, `145,00 €`, `1.250,50`).
     * If $\ge 4$ prices are found, apply interquartile/10% trimming (remove bottom 10% and top 10% extreme outliers).
     * Compute `min_eur`, `max_eur`, `median_eur`, and `median_chf = round(median_eur * eur_to_chf, 2)`.
  3. **`fetch_sold_stats(query: str) -> EbaySoldStats`**:
     * Use `curl_cffi.requests.AsyncSession(impersonate="chrome")` with `Accept-Language: de-DE,de;q=0.9` and a 8.0s timeout.
     * On any network error or anti-bot block, log a warning and return `EbaySoldStats(query=query, sample_count=0)` gracefully without crashing.

#### 4.2.2 `backend/services/ai_service.py` (With Tool + JSON Compatibility Fix)
* **Critical Gemini API Safeguard (`google_search` + JSON Output):**
  * **Technical Reality:** On the Gemini API (`google-genai`), combining `tools=[types.Tool(google_search=types.GoogleSearch())]` AND `response_mime_type="application/json"` in the same `GenerateContentConfig` raises `400 INVALID_ARGUMENT: Tool use with a response mime type: 'application/json' is unsupported` on standard production endpoints.
  * **Mandatory Implementation Pattern:**
    * When `enable_search_grounding=True`, pass `tools=[types.Tool(google_search=types.GoogleSearch())]` and **leave `response_mime_type` unset** (`None`).
    * Instruct Gemini in the system prompt to return **only a valid JSON object** matching the schema below.
    * Implement a helper `extract_and_parse_json(raw_text: str) -> dict` in `ai_service.py` that strips optional Markdown code fences (` ```json ... ``` `) or extracts the outermost `{ ... }` block and validates it via Pydantic (`AIAnalysisPayload.model_validate_json(...)`).
    * If `enable_search_grounding=False`, you may optionally set `response_mime_type="application/json"`, while still running `extract_and_parse_json()` for uniform handling.
* **Input Preparation:**
  * Load only the `<image_id>_ai.jpg` (`<= 1024px`, EXIF-free) files for the draft's images.
* **Prompt Instructions:**
  1. Identify the exact brand and model from the images and `user_notes`.
  2. **Visual Quality & Completeness Check:** Return `missing_photo_hints` (in German) if important details for buyers are missing (e.g., *"Typenschild / Modellnummer nicht sichtbar"*, *"Nahaufnahme der erwähnten Gebrauchsspuren fehlt"*).
  3. **Hybrid Price Strategy (CH in CHF & DE in EUR):** Combine the provided **eBay DE Sold Stats** (in EUR and CHF) and **Google Search Grounding** (Swiss new price on Digitec/Toppreise in CHF + German new price on Idealo/Geizhals in EUR) to recommend:
     * `ch_new_price_chf`: Current Swiss retail price in CHF (if found).
     * `de_new_price_eur`: Current German retail price in EUR (if found).
     * **Swiss Prices (CHF):**
       * `ricardo_start_chf`: Attractive auction start price (~65–75% of realistic Swiss second-hand market value).
       * `ricardo_buynow_chf`: Realistic Swiss second-hand value (factoring in Ricardo's ~10–12% commission and never exceeding 80% of current Swiss new price unless collectible).
       * `tutti_vhb_chf`: Slightly above expected final CHF price for 5–10% negotiation margin.
     * **German Prices (EUR):**
       * `ebay_start_eur`: Attractive auction start price in EUR for eBay.de (~60–70% of realistic eBay DE sold median).
       * `ebay_buynow_eur`: Realistic eBay.de Sofort-Kaufen price in EUR (anchored on `ebay_stats.median_eur` and capped appropriately below `de_new_price_eur`).
       * `kleinanzeigen_vb_eur`: Realistic Kleinanzeigen.de VB price in EUR (typically `ebay_buynow_eur` + 5–10% negotiation buffer).
  4. **Swiss Listings (Swiss German `ss` instead of `ß`, Prices in CHF, Swiss Legal Disclaimer):**
     * **Ricardo.ch (`ricardo`):**
       * `title`: **Maximum 60 characters**, keyword-optimized (`Brand + Model + Key Spec + Condition`).
       * `description`: Structured sections (`Zustand`, `Lieferumfang`, `Technische Daten`, `Versand & Abholung`, and mandatory Swiss legal clause: `Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.`).
     * **Tutti.ch (`tutti`):**
       * `title`: **Maximum 80 characters**.
       * `category_suggestion`: e.g. `"Audio & TV > Kopfhörer"`.
       * `description`: Friendly classified ad text including pickup/shipping & TWINT hint and mandatory Swiss legal clause (`Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.`).
  5. **German Listings (Standard German orthography with `ß`, Prices in EUR, German/EU BGB Legal Disclaimer):**
     * **eBay.de (`ebay_de`):**
       * `title`: **Maximum 80 characters**, search-optimized for eBay Germany (`Marke + Modell + Hauptmerkmal + Zustand`).
       * `category_suggestion`: e.g. `"TV, Video & Audio > Tragbare Audio- & Videogeräte > Kopfhörer"`.
       * `description`: Structured sections (`Zustand`, `Lieferumfang`, `Technische Daten`, `Versand & Bezahlung` via DHL/Hermes) and mandatory German BGB private sale clause: `Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf.`.
     * **Kleinanzeigen.de (`kleinanzeigen`):**
       * `title`: **Maximum 65 characters**, clear and appealing classified ad title.
       * `category_suggestion`: e.g. `"Audio & Hifi > Kopfhörer"`.
       * `description`: Friendly German classified ad text mentioning pickup or insured shipping (DHL/Hermes), payment via "Direkt kaufen" / PayPal / cash on pickup, and mandatory German BGB private sale clause: `Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf.`.
* **Post-Processing Safeguards (Mandatory in Python):**
  * **Swiss Platforms (`ricardo`, `tutti`):**
    * Replace any `ß` with `ss` in `ricardo.title`, `ricardo.description`, `tutti.title`, and `tutti.description`.
    * Enforce `len(ricardo.title) <= 60` and `len(tutti.title) <= 80` (truncate cleanly at word boundary if exceeded).
    * Ensure `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme"` is present in both `ricardo.description` and `tutti.description`; if missing, append `\n\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.`.
  * **German Platforms (`ebay_de`, `kleinanzeigen`):**
    * Enforce `len(ebay_de.title) <= 80` and `len(kleinanzeigen.title) <= 65` (truncate cleanly at word boundary if exceeded).
    * Ensure `"Ausschluss jeglicher Sachmängelhaftung"` is present in both `ebay_de.description` and `kleinanzeigen.description`; if missing, append `\n\nDer Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf.`.

#### 4.2.3 Phase 2 Automated Acceptance Criteria (`tests/test_phase2_pricing_and_ai.py`)
Write automated `pytest` tests verifying:
1. **`test_ebay_sold_html_parser_and_currency_conversion`**: Feed realistic eBay.de HTML containing sold items (`EUR 150,00`, `EUR 160,00`, `EUR 170,00`, plus a `EUR 1,00` outlier and a `"EUR 100,00 bis EUR 200,00"` range item) into `parse_sold_html()`. Assert range items are skipped, median EUR is accurately calculated, and `median_chf` is converted properly. Also test that challenge HTML returns `sample_count == 0` gracefully.
2. **`test_verification_links_generation`**: Verify `build_verification_links("Sony WH-1000XM4")` produces valid URLs containing `LH_Sold=1&LH_Complete=1` for `ebay.de`, `kleinanzeigen.de`, `idealo.de`, `ricardo.ch`, `toppreise.ch`, and `digitec.ch`.
3. **`test_ai_json_extractor_and_grounding_config_compatibility`**: Verify that when `enable_search_grounding=True`, `GenerateContentConfig` does NOT set `response_mime_type="application/json"` (preventing the 400 API error), and `extract_and_parse_json()` cleanly parses JSON even when wrapped in ` ```json ... ``` ` markdown fences and preamble text.
4. **`test_ai_post_processing_safeguards_ch_and_de`**:
   * Pass a mock AI response with:
     * A 75-character Ricardo title containing `ß` and a description missing the Swiss warranty disclaimer.
     * A 95-character eBay.de title and an 80-character Kleinanzeigen.de title (containing valid German `ß` e.g. `"Größe"`), with descriptions missing the German Sachmängelhaftung disclaimer.
   * Assert the service:
     * Truncates `ricardo.title` to $\le 60$ chars, `tutti.title` to $\le 80$ chars, `ebay_de.title` to $\le 80$ chars, and `kleinanzeigen.title` to $\le 65$ chars.
     * Replaces `ß` with `ss` in `ricardo` and `tutti`, while preserving `ß` in `ebay_de` and `kleinanzeigen`.
     * Appends the Swiss disclaimer (`"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."`) to `ricardo` and `tutti`, and appends the German BGB disclaimer (`"Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung..."`) to `ebay_de` and `kleinanzeigen`.
5. **`test_iterative_reanalysis_preserves_draft_id_and_updates_hints`**: Create a draft with 1 photo, run mocked AI analysis returning `missing_photo_hints=["Bitte Typenschild fotografieren"]`, upload a 2nd photo to the same draft, re-run AI analysis, and verify the existing draft is updated in-place across all 4 platform listings.

---

### PHASE 3: FastAPI REST API & Local Web Dashboard (`Seller Assistant`)

#### 4.3.1 REST API Specification (`backend/main.py`)
Configure `CORSMiddleware` with `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]` so the local dashboard and Firefox Extension Background Worker can communicate without restriction.

Implement the following endpoints:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Returns `{"status": "ok", "model": settings.gemini_model}` |
| `GET` | `/api/settings` | Returns `PresetSettings` (with CH & DE shipping presets) |
| `PUT` | `/api/settings` | Updates and persists `PresetSettings` |
| `GET` | `/api/drafts` | Returns `List[Draft]` (all saved drafts) |
| `POST` | `/api/drafts` | Creates a new empty `Draft` (accepts optional `{"user_notes": "..."}`) |
| `GET` | `/api/drafts/{draft_id}` | Returns a single `Draft` (404 if not found) |
| `PUT` | `/api/drafts/{draft_id}` | Updates a `Draft` (manual edits to titles, descriptions, prices, status, notes across CH & DE listings) |
| `DELETE` | `/api/drafts/{draft_id}` | Deletes draft and its image files |
| `POST` | `/api/drafts/{draft_id}/images` | Multipart upload (`files: List[UploadFile]`). Processes each image (`optimized` + `ai` variants) and appends to `draft.images` |
| `DELETE` | `/api/drafts/{draft_id}/images/{image_id}` | Removes a specific image from the draft |
| `PATCH` | `/api/drafts/{draft_id}/images/{image_id}` | Body `{"active_mode": "optimized" \| "blurred" \| "cutout"}`. Generates variant if not cached yet and updates `active_mode` |
| `GET` | `/api/drafts/{draft_id}/images/{image_id}/{variant}` | Serves the `.jpg` file (`optimized`, `blurred`, `cutout`, or `active` which resolves to `img.active_mode`) |
| `POST` | `/api/drafts/{draft_id}/analyze` | Runs Hybrid Price Engine (eBay DE + Gemini Search Grounding) on the draft's current images & `user_notes`, updates `draft` (CH & DE listings) and sets `status="ready"` |

#### 4.3.2 Local Web Dashboard UI (`frontend/index.html`, `frontend/app.js`, `frontend/styles.css`)
Serve `frontend/` at `/` via FastAPI `StaticFiles`.
* **Mandatory Neutral Naming:** The `<title>` and main header `<h1>` of `frontend/index.html` MUST be **`Seller Assistant`** (never include platform names in the application title/header).

The dashboard must include:
1. **Left Sidebar – Multi-Draft List:**
   * `"Neues Inserat (+)"` button (`id="btn-new-draft"`).
   * List of drafts (`id="draft-list"`) showing title or product name, status badge (`draft`, `ready`, `published`), and delete button.
2. **Main Area – Section 1: Input & Images:**
   * Drag-and-drop file upload zone (`id="dropzone"`, `<input type="file" id="file-input" multiple accept=".jpg,.jpeg,.png,.webp,.heic">`).
   * Image gallery (`id="image-gallery"`): Each uploaded image card displays:
     * Preview of its currently selected `active_mode` variant.
     * 3-way mode selector buttons: `Original (Optimiert)`, `Hintergrund-Blur`, `Freigestellt (rembg)`.
     * Delete image button.
   * User notes `<textarea id="user-notes">` + CH Shipping Preset `<select id="shipping-preset">` + DE Shipping Preset `<select id="de-shipping-preset">` + Offer Type `<select id="offer-type">`.
   * Primary action button: `"KI-Analyse & Preisrecherche starten"` (`id="btn-analyze"`).
3. **Main Area – Section 2: Iterative Quality Check & Hybrid Price Analysis (CH & DE):**
   * Missing photo hints alert box (`id="missing-hints-box"`): Displays `missing_photo_hints` with a prompt to drop additional photos above and click `"Erneut analysieren"`.
   * Price cards (`id="price-summary"`):
     * **Marktdaten:** eBay DE Sold Median (EUR & CHF), DE New Price (EUR), CH New Price (CHF).
     * **Empfohlene CH-Preise (CHF):** Ricardo Start Price, Ricardo Buy-Now Price, Tutti VHB Price.
     * **Empfohlene DE-Preise (EUR):** eBay.de Start Price, eBay.de Buy-Now Price, Kleinanzeigen.de VB Price.
     * Price reasoning text (`reasoning`).
   * 1-Click Verification Links bar (`id="verification-links"`): Anchor tags opening `ebay_sold_url`, `kleinanzeigen_search_url`, `idealo_url`, `ricardo_search_url`, `toppreise_url`, and `digitec_url` in a new tab (`target="_blank"`).
4. **Main Area – Section 3: Editable Platform Previews (CH: Ricardo.ch & Tutti.ch | DE: eBay.de & Kleinanzeigen.de):**
   * **Ricardo.ch Card (CHF):**
     * Title `<input id="ricardo-title" maxlength="60">` with live counter `<span id="ricardo-title-count">0/60</span>`.
     * Condition `<select id="ricardo-condition">`, Start Price (CHF) `<input type="number" id="ricardo-start-price">`, Buy-Now Price (CHF) `<input type="number" id="ricardo-buynow-price">`.
     * Description `<textarea id="ricardo-description">`.
   * **Tutti.ch Card (CHF):**
     * Title `<input id="tutti-title" maxlength="80">` with live counter `<span id="tutti-title-count">0/80</span>`.
     * Category Suggestion `<input id="tutti-category">`, Condition `<select id="tutti-condition">`, VHB Price (CHF) `<input type="number" id="tutti-price">`.
     * Description `<textarea id="tutti-description">`.
   * **eBay.de Card (EUR):**
     * Title `<input id="ebay-de-title" maxlength="80">` with live counter `<span id="ebay-de-title-count">0/80</span>`.
     * Category Suggestion `<input id="ebay-de-category">`, Condition `<select id="ebay-de-condition">`, Offer Type `<select id="ebay-de-offer-type">`, Start Price (EUR) `<input type="number" id="ebay-de-start-price">`, Buy-Now Price (EUR) `<input type="number" id="ebay-de-buynow-price">`.
     * Description `<textarea id="ebay-de-description">`.
   * **Kleinanzeigen.de Card (EUR):**
     * Title `<input id="kleinanzeigen-title" maxlength="65">` with live counter `<span id="kleinanzeigen-title-count">0/65</span>`.
     * Category Suggestion `<input id="kleinanzeigen-category">`, Condition `<select id="kleinanzeigen-condition">`, Price (EUR) `<input type="number" id="kleinanzeigen-price">`, Price Type `<select id="kleinanzeigen-price-type">` (`vb` / `festpreis`).
     * Description `<textarea id="kleinanzeigen-description">`.
   * `"Änderungen speichern"` button (`id="btn-save-draft"`) & Status selector (`draft` / `ready` / `published`).

#### 4.3.3 Phase 3 Automated Acceptance Criteria (`tests/test_phase3_api_and_ui.py`)
Write automated `pytest` tests using `fastapi.testclient.TestClient`:
1. **`test_full_rest_lifecycle`**: `POST /api/drafts` $\rightarrow$ `POST /api/drafts/{id}/images` (upload 2 test images) $\rightarrow$ `PATCH` image 1 to `blurred` $\rightarrow$ `GET /api/drafts/{id}/images/{img_id}/active` (assert HTTP 200 and `image/jpeg`) $\rightarrow$ `POST /api/drafts/{id}/analyze` (with mocked AI/eBay services) $\rightarrow$ `PUT /api/drafts/{id}` (manual title edits exceeding limits on `ricardo`, `ebay_de`, and `kleinanzeigen`; assert response truncates `ricardo` to 60, `ebay_de` to 80, and `kleinanzeigen` to 65 chars) $\rightarrow$ `DELETE /api/drafts/{id}`.
2. **`test_dashboard_static_html_served_and_contains_required_elements`**: `GET /` returns HTTP 200, neutral title `Seller Assistant`, and HTML containing `#btn-new-draft`, `#dropzone`, `#btn-analyze`, `#ricardo-title`, `#tutti-title`, `#ebay-de-title`, `#kleinanzeigen-title`, and `#verification-links`.

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
  * In Firefox Manifest V3, `host_permissions` may not be auto-granted on installation until approved by the user.
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
    so clicking the extension toolbar icon immediately prompts and grants all required host permissions if missing.
* **Message Bus Contract:**
  `background.js` listens via `(globalThis.browser || globalThis.chrome).runtime.onMessage.addListener` and handles three action types (returning `true` when using `sendResponse` asynchronously):
  1. **`{ action: "LIST_DRAFTS" }`**:
     * Fetches `GET http://127.0.0.1:8000/api/drafts`.
     * Returns `{ ok: true, drafts: [...] }` or `{ ok: false, error: "..." }`.
  2. **`{ action: "GET_DRAFT", draftId: "<id>" }`**:
     * Fetches `GET http://127.0.0.1:8000/api/drafts/<id>`.
     * Returns `{ ok: true, draft: {...} }`.
  3. **`{ action: "FETCH_DRAFT_IMAGES", draftId: "<id>" }`**:
     * Fetches the draft metadata, then fetches each image's `/api/drafts/<id>/images/<img_id>/active` binary endpoint, converts the `ArrayBuffer` to a Base64 Data URL (`data:image/jpeg;base64,...`), and returns:
       `{ ok: true, images: [{ id, filename: "<id>_<mode>.jpg", mimeType: "image/jpeg", dataUrl: "data:image/jpeg;base64,..." }] }`.

#### 4.4.3 Smart-Panel, Platform Detection, React/Rich-Text Setter & Firefox Xray-Safe File Injector (`extension/content.js`)
Implement `content.js` so it works both in Firefox and in a Node/JSDOM test environment (export helper functions if `typeof module !== "undefined"`):

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
   * **Rich-Text / `contenteditable` Support (for eBay.de description editor):** If the target description field is a `[contenteditable="true"]` element or an editor `iframe` body, set `innerText` / `innerHTML` (converting newlines to `<br>`) and dispatch `input` and `change` events.

3. **Firefox Xray-Safe Image File Injector (`injectFilesIntoInput(fileInput, imagePayloads)`):**
   * **Technical Safeguard (Firefox Xray Vision):** In Firefox Content Scripts, creating `new DataTransfer()` or `new File()` in the isolated extension compartment and assigning `fileInput.files = dt.files` can fail across compartment boundaries or be ignored by dropzone libraries.
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
   * Also dispatch a synthetic `drop` event (`new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt })`) on the closest dropzone container if present, ensuring compatibility across `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de`.

4. **Platform-Specific DOM Selector Cascades:**
   * **Ricardo.ch (`ricardo`):** Title input (`input[name*="title" i]`, `#title`), Description textarea (`textarea[name*="description" i]`), Start/Buy-Now price inputs (`input[name*="price" i]`).
   * **Tutti.ch (`tutti`):** Title input (`input[name="subject"]`, `input[name*="title" i]`), Description textarea (`textarea[name="body"]`, `textarea[name*="description" i]`), Price input (`input[name="price"]`).
   * **eBay.de (`ebay_de`):** Title input (`input[name="title"]`, `input[id*="title" i]`, `input[aria-label*="Titel" i]`), Description (`textarea[name*="description" i]`, `iframe[id*="desc" i]`, `[contenteditable="true"]`), Start price (`input[name*="startPrice" i]`, `input[aria-label*="Startpreis" i]`), Buy-Now price (`input[name*="buyItNowPrice" i]`, `input[name*="price" i]`, `input[aria-label*="Sofort-Kaufen" i]`).
   * **Kleinanzeigen.de (`kleinanzeigen`):** Title input (`#postad-title`, `input[name="title"]`), Description textarea (`#pstad-descrptn`, `textarea[name="description"]`), Price input (`#pstad-price`, `input[name="price"]`), Price type radio/select (`input[name="priceType"]`, `select[name="priceType"]` for `VB` / `FIXED`).

5. **Smart-Panel UI:**
   * Inject a floating widget (`#ai-listing-smart-panel`) with neutral header **`Seller Assistant`** at bottom-right of `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de` (collapsible into a small pill button).
   * Contains:
     * **Active Platform Badge:** Displays detected marketplace & currency (e.g., `Ricardo.ch (CHF)`, `Tutti.ch (CHF)`, `eBay.de (EUR)`, `Kleinanzeigen.de (EUR)`).
     * **Draft Selector Dropdown** (`#ai-ext-draft-select`) + Refresh button.
     * **Wizard Step 1 Button (`#ai-ext-step1-btn`):** *"Schritt 1: Bilder & Titel einfügen"* — injects all active images into `<input type="file">` and fills the Title field for the active platform (`ricardo` 60-char, `tutti` 80-char, `ebay_de` 80-char, or `kleinanzeigen` 65-char title).
     * **Wizard Step 2 Button (`#ai-ext-step2-btn`):** *"Schritt 2: Beschreibung & Preis einfügen"* — fills the Description field (`<textarea>` or `contenteditable`), Condition dropdown/radio (if matching selector is visible), and Price inputs (Start/Buy-Now in CHF on Ricardo; VHB in CHF on Tutti; Start/Buy-Now in EUR on eBay.de; VB/Festpreis in EUR on Kleinanzeigen.de).
     * **1-Click Copy Fallback Section:** Displays the selected draft's platform-specific Title, Description, Category Suggestion, and Prices with a `"Kopieren"` button (`navigator.clipboard.writeText(...)`) next to each item.

#### 4.4.4 Phase 4 Automated Acceptance Criteria (`tests/test_phase4_extension.py`)
Write automated `pytest` tests verifying:
1. **`test_manifest_v3_validity_and_neutral_naming`**: Parse `extension/manifest.json`, assert `manifest_version == 3`, assert `name == "Seller Assistant"` (and verify no third-party marketplace names appear in `name` or `action.default_title`), verify `background.scripts` contains `background.js`, verify `host_permissions` and `content_scripts[0].matches` include `127.0.0.1:8000` (in `host_permissions`), `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de`, and verify all referenced files (`background.js`, `content.js`, `panel.css`) exist.
2. **`test_extension_js_syntax_and_xray_and_cors_safeguards`**:
   * Run `node --check extension/background.js` and `node --check extension/content.js` (if `node` is installed) to assert zero JS syntax errors.
   * Assert `content.js` does NOT contain `fetch("http://127.0.0.1` or `fetch("http://localhost` (enforcing that all backend communication uses `runtime.sendMessage` to `background.js`).
   * Assert `background.js` handles `LIST_DRAFTS`, `GET_DRAFT`, and `FETCH_DRAFT_IMAGES`.
   * Assert `content.js` implements `detectPlatform` supporting `ricardo.ch`, `tutti.ch`, `ebay.de`, and `kleinanzeigen.de`, `wrappedJSObject` Xray unwrap support, `setNativeValue`, `DataTransfer` file injection, `#ai-ext-step1-btn`, `#ai-ext-step2-btn`, and clipboard copy fallbacks.

---

## 5. Verification & Acceptance Runbook

After completing all 4 phases, the implementing LLM must run:

```bash
.venv/bin/pytest -v
```

### Definition of Done (All checks must pass):
- [x] `.venv/bin/pytest -v` passes 100% of tests across all 4 test files (`test_phase1_image_and_storage.py`, `test_phase2_pricing_and_ai.py`, `test_phase3_api_and_ui.py`, `test_phase4_extension.py`) with 0 failures and 0 errors.
- [x] Starting the server via `.venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000` serves the dashboard at `http://127.0.0.1:8000/` and OpenAPI docs at `http://127.0.0.1:8000/docs`.
- [x] All EXIF/GPS metadata is stripped from uploaded images and AI-bound images are capped at `1024x1024` pixels.
- [x] Platform-specific constraints are enforced:
  - **Ricardo.ch:** Title $\le 60$ chars, `ss` orthography, prices in CHF, Swiss warranty disclaimer.
  - **Tutti.ch:** Title $\le 80$ chars, `ss` orthography, prices in CHF, Swiss warranty disclaimer.
  - **eBay.de:** Title $\le 80$ chars, standard German (`ß`), prices in EUR, German BGB Sachmängelhaftung disclaimer.
  - **Kleinanzeigen.de:** Title $\le 65$ chars, standard German (`ß`), prices in EUR (VB/Festpreis), German BGB Sachmängelhaftung disclaimer.
- [x] User-facing project, dashboard, and extension names strictly use the neutral title **`Seller Assistant`**.
