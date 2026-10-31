# Implementation Plan & Specification: Tutti & Ricardo AI Listing Assistant

> **Target Audience:** Implementing Software Engineering LLM / Developer  
> **Reference Requirements:** `REQUIREMENTS.md`  
> **Architecture:** Local Python FastAPI Backend (`127.0.0.1:8000`) + Local Web Dashboard + Firefox WebExtension (Manifest V3)  

---

## 1. Instructions for the Implementing LLM

1. **Follow Phases Strictly in Order:** Implement Phase 1 $\rightarrow$ run Phase 1 tests $\rightarrow$ Phase 2 $\rightarrow$ run Phase 2 tests $\rightarrow$ Phase 3 $\rightarrow$ run Phase 3 tests $\rightarrow$ Phase 4 $\rightarrow$ run Phase 4 tests.
2. **Do Not Guess Contracts:** Use the exact file paths, Pydantic schemas, REST endpoint routes, and extension message payloads specified in this document.
3. **Offline/Deterministic Testability:** Every external dependency (Google Gemini API, eBay.de HTTP requests, `rembg` neural network inference if slow in unit tests) MUST be injectable or mockable so the entire `pytest` suite runs deterministically in < 10 seconds without requiring live internet or a live API key.
4. **Hard Constraints to Enforce in Code:**
   - **Privacy:** Never send original full-resolution or EXIF-containing images to the Gemini API. Always strip EXIF/GPS metadata first and downscale to max `1024x1024` px before calling Gemini.
   - **Ricardo Title Limit:** Strictly $\le 60$ characters (validate and truncate/clean in Python as a hard safeguard even if the LLM returns > 60 chars).
   - **Tutti Title Limit:** Strictly $\le 80$ characters.
   - **Swiss Legal Disclaimer:** Every Ricardo and Tutti description must contain the private sale warranty disclaimer (`"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."`).
   - **CORS / CSP Bypass in Extension:** The Firefox Content Script (`content.js`) must **NEVER** call `fetch("http://127.0.0.1:8000/...")` directly. All HTTP calls to the local backend must happen inside `background.js` via `browser.runtime.onMessage` / `chrome.runtime.onMessage`.

---

## 2. Repository Structure & Dependencies

Create the following project structure in `/app`:

```text
/app
├── .env.example
├── requirements.txt
├── pytest.ini
├── REQUIREMENTS.md
├── IMPLEMENTATION_PLAN.md
├── data/                        # Runtime directory (gitignored, auto-created)
│   ├── drafts.json              # Persistent multi-draft store
│   ├── settings.json            # User presets (shipping, default offer type)
│   └── images/                  # Subfolders per draft_id: data/images/<draft_id>/
├── backend/
│   ├── __init__.py
│   ├── config.py                # Settings loaded from .env
│   ├── models.py                # Pydantic v2 schemas
│   ├── storage.py               # Thread-safe JSON/file persistence for drafts & settings
│   ├── main.py                  # FastAPI app, routes, static files, CORS
│   └── services/
│       ├── __init__.py
│       ├── image_service.py     # HEIC->JPG, EXIF strip, auto-contrast, Blur, rembg Cutout, 1024px AI resize
│       ├── ebay_service.py      # eBay DE sold listings fetcher/parser & verification link builder
│       └── ai_service.py        # Gemini API integration with Search Grounding & structured output
├── frontend/
│   ├── index.html               # Local Web Dashboard UI
│   ├── styles.css               # Clean, responsive dashboard styling
│   └── app.js                   # Dashboard state, drag&drop upload, iterative AI re-run, live char counters
├── extension/
│   ├── manifest.json            # Firefox WebExtension Manifest V3
│   ├── background.js            # Service worker / background script communicating with 127.0.0.1:8000
│   ├── content.js               # Smart-Panel UI, step-by-step React DOM injector, DataTransfer image uploader
│   └── panel.css                # Isolated CSS for the floating Smart-Panel on ricardo.ch & tutti.ch
└── tests/
    ├── conftest.py              # Shared pytest fixtures (temp data dir, sample EXIF images, mock HTML)
    ├── test_phase1_image_and_storage.py
    ├── test_phase2_pricing_and_ai.py
    ├── test_phase3_api_and_ui.py
    └── test_phase4_extension.py
```

### 2.1 `requirements.txt`
```text
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
python-multipart>=0.0.9
pydantic>=2.7.0
pydantic-settings>=2.2.0
python-dotenv>=1.0.1
Pillow>=10.3.0
pillow-heif>=0.16.0
rembg>=2.0.56
onnxruntime>=1.17.0
httpx>=0.27.0
beautifulsoup4>=4.12.3
google-genai>=0.3.0
pytest>=8.1.0
pytest-asyncio>=0.23.6
```

### 2.2 `.env.example`
```ini
GEMINI_API_KEY=your_google_ai_studio_api_key_here
GEMINI_MODEL=gemini-2.5-flash
ENABLE_SEARCH_GROUNDING=true
EUR_TO_CHF_RATE=0.94
DATA_DIR=./data
HOST=127.0.0.1
PORT=8000
```

---

## 3. Data Models & Schemas (`backend/models.py`)

Implement the following exact Pydantic v2 models in `backend/models.py`:

```python
from enum import Enum
from typing import List, Optional
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
    variants: dict[ImageVariantMode, str] = Field(default_factory=dict)  # Relative URLs e.g. "/api/drafts/{id}/images/{img_id}/optimized"
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
```

---

## 4. Phase-by-Phase Implementation Specification

---

### PHASE 1: Backend Core, Multi-Draft Persistence & Image Pipeline

#### 4.1.1 `backend/storage.py`
* Implement a clean repository class `StorageService(data_dir: Path)`:
  * `list_drafts() -> List[Draft]` (sorted by `updated_at` descending).
  * `get_draft(draft_id: str) -> Optional[Draft]`.
  * `create_draft(user_notes: str = "") -> Draft` (pre-populates default `offer_type` and `shipping_preset_id` from `PresetSettings`).
  * `update_draft(draft: Draft) -> Draft` (enforces `len(draft.ricardo.title) <= 60` and `len(draft.tutti.title) <= 80`, updates `updated_at` ISO timestamp, saves atomically via temp file rename).
  * `delete_draft(draft_id: str) -> bool` (removes draft from `drafts.json` and deletes `data/images/<draft_id>/`).
  * `get_settings() -> PresetSettings` and `update_settings(settings: PresetSettings) -> PresetSettings`.

#### 4.1.2 `backend/services/image_service.py`
* Register HEIC opener at module import:
  ```python
  import pillow_heif
  pillow_heif.register_heif_opener()
  ```
* Implement `ImageService`:
  1. **Orientation & EXIF Stripping (`clean_and_orient(raw_bytes: bytes) -> Image.Image`):**
     * Open image with `PIL.Image.open(io.BytesIO(raw_bytes))`.
     * Call `ImageOps.exif_transpose(img)` FIRST so smartphone portrait photos are rotated upright.
     * Convert to `RGB` mode.
     * Create a brand new `Image.new("RGB", img.size)` and paste pixel data (or save without `exif` info) so **zero EXIF/GPS/camera metadata remains**.
  2. **Default Optimized Variant (`create_optimized_variant(clean_img: Image.Image) -> Image.Image`):**
     * Apply subtle auto-contrast: `ImageOps.autocontrast(clean_img, cutoff=0.5)`.
     * Limit max dimension to `2048px` (`thumbnail((2048, 2048), Image.Resampling.LANCZOS)`) for fast browser upload while keeping high clarity.
     * Save as `<image_id>_optimized.jpg` (JPEG quality=90, no EXIF).
  3. **AI Input Downscaled Variant (`create_ai_input_variant(clean_img: Image.Image) -> bytes`):**
     * Copy `clean_img`, resize via `thumbnail((1024, 1024), Image.Resampling.LANCZOS)`.
     * Save as `<image_id>_ai.jpg` (JPEG quality=85, no EXIF). Never exceed `1024px` on either axis.
  4. **On-Demand / Cached Cutout Variant (`get_or_create_cutout(draft_id, image_id)`):**
     * Run `rembg.remove(optimized_img)` to obtain RGBA foreground.
     * Composite foreground onto a clean neutral light-gray/white canvas `Image.new("RGB", rgba.size, (248, 249, 250))`.
     * Save to `<image_id>_cutout.jpg`.
     * *Testability requirement:* Allow injecting a custom `mask_extractor: Callable[[Image.Image], Image.Image]` into `ImageService.__init__` so unit tests can test cutout and blur pipelines instantly without downloading a 170MB U2Net ONNX model during unit tests if needed, while defaulting to `rembg.remove` in production.
  5. **On-Demand / Cached Background Blur Variant (`get_or_create_blurred(draft_id, image_id)`):**
     * Extract RGBA foreground via `mask_extractor` (`rembg.remove`).
     * Take `optimized_img`, apply `ImageFilter.GaussianBlur(radius=18)` to create blurred background.
     * Composite the sharp RGBA foreground over the blurred background using the alpha channel as mask: `Image.composite(optimized_img, blurred_bg, rgba.split()[3])`.
     * Save to `<image_id>_blurred.jpg`.

#### 4.1.3 Phase 1 Automated Acceptance Criteria (`tests/test_phase1_image_and_storage.py`)
Write automated `pytest` tests verifying:
1. **`test_exif_and_gps_completely_stripped`**: Create a synthetic JPEG containing EXIF tags (Make, Model, GPSInfo), process it through `ImageService.process_upload()`, reload the saved `<image_id>_optimized.jpg` and `<image_id>_ai.jpg`, and assert `img.getexif()` is completely empty (`len(img.getexif()) == 0`).
2. **`test_ai_image_downscaled_to_max_1024px`**: Upload a `3000x2000` image and assert `<image_id>_ai.jpg` has dimensions `1024x683` ($\le 1024$ on both axes), while `<image_id>_optimized.jpg` is `2048x1365`.
3. **`test_heic_upload_converted_to_jpg`**: Generate an in-memory HEIF/HEIC image via `pillow_heif`, pass it to `process_upload()`, and assert it succeeds and outputs valid RGB `.jpg` files.
4. **`test_cutout_and_blur_generation`**: Process an image and trigger `cutout` and `blurred` modes; assert both `.jpg` files exist on disk, match the optimized image dimensions, and have RGB mode.
5. **`test_multi_draft_crud_persistence`**: Create 3 drafts, update status and titles, re-instantiate `StorageService` from disk, assert all 3 drafts persist in order, and verify deleting a draft removes both the JSON entry and its image folder.

---

### PHASE 2: Hybrid Price Engine & Gemini AI Service

#### 4.2.1 `backend/services/ebay_service.py`
* Implement `EbayService`:
  1. **`build_verification_links(query: str) -> VerificationLinks`**:
     * URL-encode `query`.
     * `ebay_sold_url`: `https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1`
     * `ricardo_search_url`: `https://www.ricardo.ch/de/s/{q}`
     * `toppreise_url`: `https://www.toppreise.ch/produktsuche?q={q}`
     * `digitec_url`: `https://www.digitec.ch/de/search?q={q}`
  2. **`parse_sold_html(html: str, query: str, eur_to_chf: float = 0.94) -> EbaySoldStats`**:
     * Parse eBay search result items (`.s-item` blocks) using `BeautifulSoup`.
     * Ignore placeholder items (e.g., title `"Shop on eBay"` or price ranges with `"bis"` / `"to"`).
     * Extract prices from `.s-item__price` using regex matching German/European currency formats (e.g. `EUR 145,00`, `145,00 €`, `1.250,50`).
     * If $\ge 4$ prices are found, apply interquartile trimming (remove bottom 10% and top 10% extreme outliers, e.g., defective parts or bundles).
     * Compute `min_eur`, `max_eur`, `median_eur`, and `median_chf = round(median_eur * eur_to_chf, 2)`.
  3. **`fetch_sold_stats(query: str) -> EbaySoldStats`**:
     * Perform async HTTP GET with realistic desktop `User-Agent` header and 6.0s timeout.
     * On network error or captcha/block, log a warning and return `EbaySoldStats(query=query, sample_count=0)` gracefully without crashing the pipeline.

#### 4.2.2 `backend/services/ai_service.py`
* Implement `AIService`:
  * Load `GEMINI_API_KEY`, `GEMINI_MODEL` (default `gemini-2.5-flash`), and `ENABLE_SEARCH_GROUNDING` from `config.py`.
  * **Input Preparation:**
    * Load only the `<image_id>_ai.jpg` (`<= 1024px`, EXIF-free) files for the draft's images (or if the user selected `cutout` / `blurred` and enabled pre-cutout privacy, resize that variant to `<= 1024px`).
  * **Prompt & Grounding:**
    * Enable Google Search Grounding (`tools=[{"google_search": {}}]`) when `ENABLE_SEARCH_GROUNDING=True` so Gemini looks up the current Swiss retail price (Digitec/Galaxus, Toppreise.ch) and product specifications.
    * Instruct Gemini to:
      1. Identify the exact brand and model from the images and `user_notes`.
      2. Perform a **Visual Quality & Completeness Check**: inspect the uploaded photos and return `missing_photo_hints` (in German) if important details for buyers are missing (e.g., *"Typenschild / Modellnummer nicht sichtbar"*, *"Nahaufnahme der erwähnten Gebrauchsspuren fehlt"*, *"Originalverpackung / Zubehör im Text erwähnt, aber nicht auf den Fotos"*).
      3. Combine the provided **eBay DE Sold Stats** (in CHF) and the **Swiss New Price (Digitec/Toppreise)** to recommend:
         * `ricardo_start_chf` (attractive auction start price, typically ~65–75% of realistic second-hand market value, rounded to whole CHF or .00/.50).
         * `ricardo_buynow_chf` (realistic Swiss second-hand market value, factoring in Ricardo's ~10–12% commission and never exceeding 80% of current Swiss new price unless collectible).
         * `tutti_vhb_chf` (slightly above expected final price to leave 5–10% negotiation room, no platform fee).
      4. Generate the **Ricardo listing** (German, Swiss spelling `ss` instead of `ß`):
         * `title`: **Maximum 60 characters**, keyword-optimized (`Brand + Model + Key Spec + Condition`), no filler words like *"Super!"* or *"Top Zustand!!!"*.
         * `description`: Structured sections (`Zustand`, `Lieferumfang`, `Technische Daten`, `Versand & Abholung`, and mandatory legal clause: `Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.`).
      5. Generate the **Tutti listing** (German, Swiss spelling `ss` instead of `ß`):
         * `title`: Maximum 80 characters.
         * `category_suggestion`: e.g. `"Audio & TV > Kopfhörer"`.
         * `description`: Friendly, trustworthy classified ad text including pickup/shipping & TWINT hint and mandatory legal clause (`Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.`).
  * **Post-Processing Safeguards (Mandatory in Python):**
    * Replace any `ß` with `ss` in generated titles and descriptions (Swiss standard).
    * Enforce `len(ricardo.title) <= 60` (if > 60, truncate cleanly at last word boundary $\le 60$ chars).
    * Enforce `len(tutti.title) <= 80`.
    * Ensure `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme"` is present in both descriptions; if missing, append `\n\nPrivatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme.`.

#### 4.2.3 Phase 2 Automated Acceptance Criteria (`tests/test_phase2_pricing_and_ai.py`)
Write automated `pytest` tests verifying:
1. **`test_ebay_sold_html_parser_and_currency_conversion`**: Feed realistic eBay.de HTML containing sold items (`EUR 150,00`, `EUR 160,00`, `EUR 170,00`, plus a `EUR 1,00` outlier and a `"EUR 100,00 bis EUR 200,00"` range item) into `parse_sold_html()`. Assert range items are skipped, median EUR is accurately calculated, and `median_chf` is converted properly.
2. **`test_verification_links_generation`**: Verify `build_verification_links("Sony WH-1000XM4")` produces valid URLs containing `LH_Sold=1&LH_Complete=1` for eBay, `ricardo.ch`, `toppreise.ch`, and `digitec.ch`.
3. **`test_ai_post_processing_safeguards`**: Pass a mock AI response with a 75-character Ricardo title containing `ß` (`"Großartiger Sony WH-1000XM4 Kopfhörer in weiß mit Zubehör und Originalverpackung"`) and a description missing the warranty disclaimer. Assert the service outputs a Ricardo title $\le 60$ chars, replaces `ß` with `ss`, and appends the mandatory Swiss legal disclaimer.
4. **`test_iterative_reanalysis_preserves_draft_id_and_updates_hints`**: Create a draft with 1 photo, run mocked AI analysis returning `missing_photo_hints=["Bitte Typenschild fotografieren"]`, upload a 2nd photo to the same draft, re-run AI analysis, and verify the existing draft is updated in-place with updated hints and listing fields.

---

### PHASE 3: FastAPI REST API & Local Web Dashboard

#### 4.3.1 REST API Specification (`backend/main.py`)
Configure `CORSMiddleware` with `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]` so the local dashboard and Firefox Extension Background Worker can communicate without restriction.

Implement the following endpoints:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/health` | Returns `{"status": "ok", "model": settings.gemini_model}` |
| `GET` | `/api/settings` | Returns `PresetSettings` |
| `PUT` | `/api/settings` | Updates and persists `PresetSettings` |
| `GET` | `/api/drafts` | Returns `List[Draft]` (all saved drafts) |
| `POST` | `/api/drafts` | Creates a new empty `Draft` (accepts optional `{"user_notes": "..."}`) |
| `GET` | `/api/drafts/{draft_id}` | Returns a single `Draft` (404 if not found) |
| `PUT` | `/api/drafts/{draft_id}` | Updates a `Draft` (manual edits to titles, descriptions, prices, status, notes) |
| `DELETE` | `/api/drafts/{draft_id}` | Deletes draft and its image files |
| `POST` | `/api/drafts/{draft_id}/images` | Multipart upload (`files: List[UploadFile]`). Processes each image (`optimized` + `ai` variants) and appends to `draft.images` |
| `DELETE` | `/api/drafts/{draft_id}/images/{image_id}` | Removes a specific image from the draft |
| `PATCH` | `/api/drafts/{draft_id}/images/{image_id}` | Body `{"active_mode": "optimized" \| "blurred" \| "cutout"}`. Generates variant if not cached yet and updates `active_mode` |
| `GET` | `/api/drafts/{draft_id}/images/{image_id}/{variant}` | Serves the `.jpg` file (`optimized`, `blurred`, `cutout`, or `active` which resolves to `img.active_mode`) |
| `POST` | `/api/drafts/{draft_id}/analyze` | Runs Hybrid Price Engine (eBay DE + Gemini Search Grounding) on the draft's current images & `user_notes`, updates `draft` and sets `status="ready"` |

#### 4.3.2 Local Web Dashboard UI (`frontend/index.html`, `frontend/app.js`, `frontend/styles.css`)
Serve `frontend/` at `/` via FastAPI `StaticFiles`. The dashboard must include:
1. **Left Sidebar – Multi-Draft List:**
   * `"Neues Inserat (+)"` button (`id="btn-new-draft"`).
   * List of drafts (`id="draft-list"`) showing title or product name, status badge (`draft`, `ready`, `published`), and delete button.
2. **Main Area – Section 1: Input & Images:**
   * Drag-and-drop file upload zone (`id="dropzone"`, `<input type="file" id="file-input" multiple accept=".jpg,.jpeg,.png,.webp,.heic">`).
   * Image gallery (`id="image-gallery"`): Each uploaded image card displays:
     * Preview of its currently selected `active_mode` variant.
     * 3-way mode selector buttons: `Original (Optimiert)`, `Hintergrund-Blur`, `Freigestellt (rembg)`.
     * Delete image button.
   * User notes `<textarea id="user-notes">` + Shipping Preset `<select id="shipping-preset">` + Offer Type `<select id="offer-type">`.
   * Primary action button: `"KI-Analyse & Preisrecherche starten"` (`id="btn-analyze"`).
3. **Main Area – Section 2: Iterative Quality Check & Hybrid Price Analysis:**
   * Missing photo hints alert box (`id="missing-hints-box"`): Displays `missing_photo_hints` with a prompt to drop additional photos above and click `"Erneut analysieren"`.
   * Price cards (`id="price-summary"`): Shows eBay DE Sold Median (EUR & CHF), CH New Price (CHF), Recommended Ricardo Start Price, Ricardo Buy-Now Price, and Tutti VHB Price, plus `reasoning`.
   * 1-Click Verification Links bar (`id="verification-links"`): Anchor tags opening `ebay_sold_url`, `ricardo_search_url`, `toppreise_url`, and `digitec_url` in a new tab (`target="_blank"`).
4. **Main Area – Section 3: Editable Platform Previews (Ricardo.ch & Tutti.ch):**
   * **Ricardo Card:**
     * Title `<input id="ricardo-title" maxlength="60">` with live counter `<span id="ricardo-title-count">0/60</span>`.
     * Condition `<select id="ricardo-condition">`, Start Price `<input type="number" id="ricardo-start-price">`, Buy-Now Price `<input type="number" id="ricardo-buynow-price">`.
     * Description `<textarea id="ricardo-description">`.
   * **Tutti Card:**
     * Title `<input id="tutti-title" maxlength="80">` with live counter `<span id="tutti-title-count">0/80</span>`.
     * Category Suggestion `<input id="tutti-category">`, Condition `<select id="tutti-condition">`, VHB Price `<input type="number" id="tutti-price">`.
     * Description `<textarea id="tutti-description">`.
   * `"Änderungen speichern"` button (`id="btn-save-draft"`) & Status selector (`draft` / `ready` / `published`).

#### 4.3.3 Phase 3 Automated Acceptance Criteria (`tests/test_phase3_api_and_ui.py`)
Write automated `pytest` tests using `fastapi.testclient.TestClient`:
1. **`test_full_rest_lifecycle`**: `POST /api/drafts` $\rightarrow$ `POST /api/drafts/{id}/images` (upload 2 test images) $\rightarrow$ `PATCH` image 1 to `blurred` $\rightarrow$ `GET /api/drafts/{id}/images/{img_id}/active` (assert HTTP 200 and `image/jpeg`) $\rightarrow$ `POST /api/drafts/{id}/analyze` (with mocked AI/eBay services) $\rightarrow$ `PUT /api/drafts/{id}` (manual title edit > 60 chars, assert response truncates to 60 chars) $\rightarrow$ `DELETE /api/drafts/{id}`.
2. **`test_dashboard_static_html_served_and_contains_required_elements`**: `GET /` returns HTTP 200 and HTML containing `#btn-new-draft`, `#dropzone`, `#btn-analyze`, `#ricardo-title`, `#tutti-title`, and `#verification-links`.

---

### PHASE 4: Firefox WebExtension (Manifest V3) with Smart-Panel

#### 4.4.1 `extension/manifest.json`
```json
{
  "manifest_version": 3,
  "name": "Tutti & Ricardo AI Listing Assistant",
  "version": "1.0.0",
  "description": "Smart-Panel und Schritt-für-Schritt Auto-Fill für Tutti.ch und Ricardo.ch",
  "permissions": ["storage", "activeTab"],
  "host_permissions": [
    "http://127.0.0.1:8000/*",
    "http://localhost:8000/*",
    "*://*.ricardo.ch/*",
    "*://*.tutti.ch/*"
  ],
  "background": {
    "scripts": ["background.js"]
  },
  "content_scripts": [
    {
      "matches": ["*://*.ricardo.ch/*", "*://*.tutti.ch/*"],
      "js": ["content.js"],
      "css": ["panel.css"],
      "run_at": "document_idle"
    }
  ],
  "browser_specific_settings": {
    "gecko": {
      "id": "listing-assistant@local.dev",
      "strict_min_version": "109.0"
    }
  }
}
```

#### 4.4.2 Background Worker Message Contract (`extension/background.js`)
`background.js` listens via `(globalThis.browser || globalThis.chrome).runtime.onMessage.addListener` and handles three action types:
1. **`{ action: "LIST_DRAFTS" }`**:
   * Fetches `GET http://127.0.0.1:8000/api/drafts`.
   * Returns `{ ok: true, drafts: [...] }` or `{ ok: false, error: "..." }`.
2. **`{ action: "GET_DRAFT", draftId: "<id>" }`**:
   * Fetches `GET http://127.0.0.1:8000/api/drafts/<id>`.
   * Returns `{ ok: true, draft: {...} }`.
3. **`{ action: "FETCH_DRAFT_IMAGES", draftId: "<id>" }`**:
   * Fetches the draft metadata, then fetches each image's `/api/drafts/<id>/images/<img_id>/active` binary endpoint, converts the `ArrayBuffer` to a Base64 Data URL (`data:image/jpeg;base64,...`), and returns:
     `{ ok: true, images: [{ id, filename: "<id>_<mode>.jpg", mimeType: "image/jpeg", dataUrl: "data:image/jpeg;base64,..." }] }`.
   * *Why:* Passing Base64 strings over the extension message bus allows `content.js` to reconstruct native `File` objects inside the page context and attach them to `<input type="file">` via `DataTransfer` without triggering any CORS or CSP blocks on `ricardo.ch` or `tutti.ch`.

#### 4.4.3 Smart-Panel & Step-by-Step Auto-Fill (`extension/content.js`)
Implement `content.js` so it works both in Firefox and in a Node/JSDOM test environment (export helper functions if `typeof module !== "undefined"`):
1. **React/Next.js Native Value Setter (`setNativeValue(element, value)`):**
   * Find the native property descriptor (`Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")` or `HTMLTextAreaElement.prototype` / `HTMLSelectElement.prototype`).
   * Call `setter.call(element, value)`.
   * Dispatch `new Event("input", { bubbles: true })`, `new Event("change", { bubbles: true })`, and `new Event("blur", { bubbles: true })`.
2. **Image File Injector (`injectFilesIntoInput(fileInput, imagePayloads)`):**
   * Convert each `{ filename, mimeType, dataUrl }` into a `Uint8Array` $\rightarrow$ `new File([bytes], filename, { type: mimeType })`.
   * Create `const dt = new DataTransfer()`, call `dt.items.add(file)` for each image, set `fileInput.files = dt.files`, and dispatch `input` and `change` events.
3. **Smart-Panel UI:**
   * Inject a floating widget (`#ai-listing-smart-panel`) at bottom-right of `ricardo.ch` and `tutti.ch` (collapsible into a small pill button).
   * Contains:
     * **Draft Selector Dropdown** (`#ai-ext-draft-select`) + Refresh button.
     * **Wizard Step 1 Button (`#ai-ext-step1-btn`):** *"Schritt 1: Bilder & Titel einfügen"* — injects all active images into `<input type="file">` and fills the Title field (Ricardo 60-char title on `ricardo.ch`, Tutti 80-char title on `tutti.ch`).
     * **Wizard Step 2 Button (`#ai-ext-step2-btn`):** *"Schritt 2: Beschreibung & Preis einfügen"* — fills the Description textarea/editor, Condition dropdown/radio (if matching selector is visible), and Price inputs (Start price / Buy-Now price on Ricardo; VHB price on Tutti).
     * **1-Click Copy Fallback Section:** Displays the selected draft's Title, Description, Start Price, and Buy-Now/VHB Price with a `"Kopieren"` button (`navigator.clipboard.writeText(...)`) next to each item so the user is never blocked even if Ricardo/Tutti changes its DOM structure.

#### 4.4.4 Phase 4 Automated Acceptance Criteria (`tests/test_phase4_extension.py`)
Write automated `pytest` tests verifying:
1. **`test_manifest_v3_validity`**: Parse `extension/manifest.json`, assert `manifest_version == 3`, verify `background.scripts` contains `background.js`, verify `host_permissions` includes `127.0.0.1:8000`, `ricardo.ch`, and `tutti.ch`, and verify all referenced files (`background.js`, `content.js`, `panel.css`) exist.
2. **`test_extension_js_syntax_and_no_direct_localhost_fetch_in_content_script`**:
   * Assert `content.js` does NOT contain `fetch("http://127.0.0.1` or `fetch("http://localhost` (enforcing that all backend communication uses `runtime.sendMessage` to `background.js`).
   * Assert `background.js` handles `LIST_DRAFTS`, `GET_DRAFT`, and `FETCH_DRAFT_IMAGES`.
   * Assert `content.js` implements `setNativeValue`, `DataTransfer` file injection, `#ai-ext-step1-btn`, `#ai-ext-step2-btn`, and clipboard copy fallbacks.

---

## 5. Verification & Acceptance Runbook

After completing all 4 phases, the implementing LLM must run:

```bash
pytest -v
```

### Definition of Done (All checks must pass):
- [ ] `pytest -v` passes 100% of tests across all 4 test files (`test_phase1_image_and_storage.py`, `test_phase2_pricing_and_ai.py`, `test_phase3_api_and_ui.py`, `test_phase4_extension.py`) with 0 failures and 0 errors.
- [ ] Starting the server via `uvicorn backend.main:app --host 127.0.0.1 --port 8000` serves the dashboard at `http://127.0.0.1:8000/` and OpenAPI docs at `http://127.0.0.1:8000/docs`.
- [ ] All EXIF/GPS metadata is stripped from uploaded images and AI-bound images are capped at `1024x1024` pixels.
- [ ] Ricardo titles never exceed 60 characters and both platforms include the Swiss private sale warranty disclaimer.
