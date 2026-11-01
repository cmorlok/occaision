# Implementation Plan & Specification: Seller Assistant (DE-Erweiterung: eBay.de & Kleinanzeigen.de)

> **Target Audience:** Autonomous Software Engineering Agent / Implementing Developer  
> **Reference Requirements:** `REQUIREMENTS.md`  
> **Mandatory Engineering Rules:** `AGENTS.md`  
> **Current Repository Status:** **Phases 0–4 (Basis-Applikation mit Ricardo.ch & Tutti.ch) sind bereits vollständig implementiert und getestet.**  
> **Aufgabe dieses Plans:** Inkrementelle Erweiterung der bestehenden Codebasis um **eBay Deutschland (`ebay.de`)** und **Kleinanzeigen (`kleinanzeigen.de`)** in **4 atomaren TDD-Schritten (Step 1 bis Step 4)**, ohne bestehende Funktionen oder Signaturen zu brechen.

---

## 1. Übersicht: Was ist bereits vorhanden vs. Was wird angepasst?

| Modul / Datei | Status im Repo | Geplante Änderung für `ebay.de` & `kleinanzeigen.de` |
| :--- | :---: | :--- |
| `backend/config.py` | ✅ Fertig | **Keine Änderung nötig** (`Settings` funktioniert unverändert). |
| `backend/services/image_service.py` | ✅ Fertig | **Keine Änderung nötig** (HEIC, EXIF-Strip, 1024px-Resize, Blur & `rembg` sind plattformunabhängig). |
| `backend/models.py` | 🔄 Erweitern (**Step 1**) | Neue Modelle `EbayDEListing` (Titel $\le 80$), `KleinanzeigenListing` (Titel $\le 65$, `PriceTypeDE`), `MarketCountry`; Erweiterung von `PresetSettings` (DE-Versand-Presets), `VerificationLinks`, `PriceAnalysis` & `Draft`. |
| `backend/storage.py` | 🔄 Erweitern (**Step 1**) | `create_draft()` setzt DE-Defaults (`default_de_shipping_preset_id`, `default_offer_type`); `update_draft()` prüft zusätzlich Titellängen für `ebay_de` ($\le 80$) und `kleinanzeigen` ($\le 65$). |
| `backend/services/ebay_service.py` | 🔄 Erweitern (**Step 2**) | `build_verification_links()` ergänzt `kleinanzeigen_search_url` und `idealo_url`. |
| `backend/services/ai_service.py` | 🔄 Erweitern (**Step 2**) | `SYSTEM_INSTRUCTION`, `post_process_ai_output()` und `analyze_draft()` um DE-Preise (EUR), `ebay_de`- & `kleinanzeigen`-Texte, Erhalt von `ß` für DE und deutschen BGB-Disclaimer erweitern. |
| `backend/main.py` | ✅ Kompatibel | Routen nutzen `Draft` und `PresetSettings` automatisch über Pydantic. |
| `frontend/index.html` & `frontend/app.js` | 🔄 Erweitern (**Step 3**) | DE-Versand-Preset-Dropdown, DE-Preiskarten & Prüflinks (`Kleinanzeigen`, `Idealo`), sowie 2 neue editierbare Vorschau-Karten (**eBay.de** & **Kleinanzeigen.de**). |
| `extension/manifest.json`, `background.js`, `content.js` | 🔄 Erweitern (**Step 4**) | Host-Permissions & Matches für `ebay.de` & `kleinanzeigen.de`, `detectPlatform()`, `setDescriptionValue()` (inkl. `iframe`/`contenteditable` für eBay.de) und Auto-Fill für alle 4 Plattformen. |

---

## 2. Verbindliche Regeln für den ausführenden Agenten

1. **Bestehende Signaturen & Kompatibilität wahren:**
   * Ändere **keine** bestehenden Funktions- oder Konstruktor-Namen (`EbayService(default_eur_to_chf=0.94)`, `post_process_ai_output(payload: Dict[str, Any])`, `AIService.get_generate_config()`, `StorageService`, `ImageService`, `create_app()`).
   * Alle neuen Felder in bestehenden Pydantic-Modellen (`ShippingPreset`, `VerificationLinks`, `PriceAnalysis`, `Draft`) müssen sinnvolle Default-Werte besitzen, damit bestehende JSON-Daten und Tests abwärtskompatibel bleiben.
2. **Strikter TDD-Workflow pro Schritt (Step 1 $\rightarrow$ Step 2 $\rightarrow$ Step 3 $\rightarrow$ Step 4):**
   * Für jeden der 4 Schritte gilt:
     1. **Tests erweitern (RED):** Aktualisiere die zugehörige Testdatei (`tests/test_phaseX_*.py`) mit den neuen Assertions.
     2. **Pytest ausführen:** Prüfe mit `.venv/bin/pytest -v`, dass der neue Test wie erwartet fehlschlägt.
     3. **Code anpassen (GREEN):** Implementiere die Änderung im Produktionscode.
     4. **Gesamte Test-Suite ausführen:** Führe `.venv/bin/pytest -v` über **alle** 4 Testdateien aus, bis **0 Failures, 0 Errors** erreicht sind.
     5. **Git Commit:** Erstelle nach jedem grünen Schritt einen atomaren Conventional Commit.
3. **Neutrale Benennung (`AGENTS.md` Rule 6):**
   * Der Name in `manifest.json` (`"name": "Seller Assistant"`), im Dashboard-`<title>` und im Smart-Panel-Header muss strikt **`Seller Assistant`** bleiben. Plattformnamen (`Ricardo`, `Tutti`, `eBay`, `Kleinanzeigen`) dürfen niemals im App-/Extension-Namen auftauchen.

---

## 3. Schritt-für-Schritt Umsetzungsplan (Step 1 bis Step 4)

---

### STEP 1: Datenmodelle (`backend/models.py`) & Persistenz (`backend/storage.py`)

#### 1.1 Änderungen in `backend/models.py`
Erweitere `backend/models.py` um die deutschen Plattform-Modelle und Felder (unter Beibehaltung aller bestehenden Felder):

```python
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
```

* **`VerificationLinks` erweitern:**
  ```python
  class VerificationLinks(BaseModel):
      ebay_sold_url: str
      kleinanzeigen_search_url: str = ""
      idealo_url: str = ""
      ricardo_search_url: str
      toppreise_url: str
      digitec_url: str
  ```
* **`PriceAnalysis` erweitern:**
  ```python
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
  ```
* **Neue Listing-Modelle `EbayDEListing` & `KleinanzeigenListing`:**
  ```python
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
  ```
* **`Draft` erweitern:**
  Füge `ebay_de: EbayDEListing = Field(default_factory=EbayDEListing)` und `kleinanzeigen: KleinanzeigenListing = Field(default_factory=KleinanzeigenListing)` zu `Draft` hinzu.

#### 1.2 Änderungen in `backend/storage.py`
* In `create_draft()`:
  ```python
  draft.ricardo.offer_type = settings.default_offer_type
  draft.ricardo.shipping_preset_id = settings.default_shipping_preset_id
  draft.ebay_de.offer_type = settings.default_offer_type
  draft.ebay_de.shipping_preset_id = settings.default_de_shipping_preset_id
  draft.kleinanzeigen.shipping_preset_id = settings.default_de_shipping_preset_id
  ```
* In `update_draft()`:
  ```python
  if len(draft.ricardo.title) > 60:
      draft.ricardo.title = draft.ricardo.title[:60].rstrip()
  if len(draft.tutti.title) > 80:
      draft.tutti.title = draft.tutti.title[:80].rstrip()
  if len(draft.ebay_de.title) > 80:
      draft.ebay_de.title = draft.ebay_de.title[:80].rstrip()
  if len(draft.kleinanzeigen.title) > 65:
      draft.kleinanzeigen.title = draft.kleinanzeigen.title[:65].rstrip()
  ```

#### 1.3 Tests für Step 1 (`tests/test_phase1_image_and_storage.py`)
Erweitere `test_multi_draft_crud_persistence`:
* Prüfe, dass `settings.default_de_shipping_preset_id == "dhl_2kg"` und sowohl CH- als auch DE-Versandpresets in `settings.shipping_presets` enthalten sind.
* Prüfe beim Speichern überlanger Titel: `d2.ebay_de.title = "C" * 95` ($\rightarrow \le 80$) und `d2.kleinanzeigen.title = "D" * 80` ($\rightarrow \le 65$).
* **Commit nach grünem Pytest:** `feat(models): add eBay.de and Kleinanzeigen.de schemas and DE shipping presets`

---

### STEP 2: Prüflinks (`backend/services/ebay_service.py`) & KI-Service (`backend/services/ai_service.py`)

#### 2.1 Änderungen in `backend/services/ebay_service.py`
Erweitere `build_verification_links(self, query: str) -> VerificationLinks`:
```python
def build_verification_links(self, query: str) -> VerificationLinks:
    q = urllib.parse.quote_plus(query.strip())
    return VerificationLinks(
        ebay_sold_url=f"https://www.ebay.de/sch/i.html?_nkw={q}&LH_Sold=1&LH_Complete=1",
        kleinanzeigen_search_url=f"https://www.kleinanzeigen.de/s-{q}/k0",
        idealo_url=f"https://www.idealo.de/preisvergleich/MainSearchProductCategory.html?q={q}",
        ricardo_search_url=f"https://www.ricardo.ch/de/s/{q}",
        toppreise_url=f"https://www.toppreise.ch/produktsuche?q={q}",
        digitec_url=f"https://www.digitec.ch/de/search?q={q}",
    )
```

#### 2.2 Änderungen in `backend/services/ai_service.py`
1. **Konstante für deutschen Rechtstext definieren:**
   ```python
   SWISS_LEGAL_DISCLAIMER = "Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."
   GERMAN_LEGAL_DISCLAIMER = (
       "Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. "
       "Keine Garantie oder Rücknahme, da Privatverkauf."
   )
   ```
2. **`post_process_ai_output(payload: Dict[str, Any]) -> Dict[str, Any]` plattformabhängig gestalten:**
   * **Schweizer Rechtschreibung (`ß` $\rightarrow$ `ss`):** Nur auf CH- und allgemeine Felder anwenden (`identified_product`, `missing_photo_hints`, `reasoning`, `ricardo_title`, `ricardo_description`, `tutti_title`, `tutti_category`, `tutti_description`). **Nicht** auf `ebay_de_*` und `kleinanzeigen_*` anwenden (dort bleibt `ß` erhalten!).
   * **Titellängen-Kappung (mit Wortgrenzen-Logik):**
     * `ricardo_title`: $\le 60$ Zeichen
     * `tutti_title`: $\le 80$ Zeichen
     * `ebay_de_title`: $\le 80$ Zeichen
     * `kleinanzeigen_title`: $\le 65$ Zeichen
   * **Pflicht-Rechtstexte:**
     * `ricardo_description` & `tutti_description`: Falls `"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme"` fehlt, `SWISS_LEGAL_DISCLAIMER` anhängen.
     * `ebay_de_description` & `kleinanzeigen_description`: Falls `"Ausschluss jeglicher Sachmängelhaftung"` fehlt, `GERMAN_LEGAL_DISCLAIMER` anhängen.
3. **`SYSTEM_INSTRUCTION` erweitern:**
   Instruiere Gemini, im JSON-Objekt zusätzlich folgende Felder zurückzugeben:
   * `"de_new_price_eur": float` (Deutscher Neupreis z.B. via Idealo/Geizhals in EUR)
   * `"ebay_start_eur": float`, `"ebay_buynow_eur": float`, `"kleinanzeigen_vb_eur": float`
   * `"ebay_de_title": "string (max 80 Zeichen, Standard-Deutsch)"`
   * `"ebay_de_category": "string"`
   * `"ebay_de_description": "string (Standard-Deutsch inkl. ß und deutschem Sachmängelhaftungsausschluss)"`
   * `"ebay_de_condition": "neu" | "wie_neu" | "gebraucht" | "defekt"`
   * `"kleinanzeigen_title": "string (max 65 Zeichen, Standard-Deutsch)"`
   * `"kleinanzeigen_category": "string"`
   * `"kleinanzeigen_description": "string (Standard-Deutsch inkl. ß, Hinweis auf Abholung/DHL/Direkt kaufen und deutschem Sachmängelhaftungsausschluss)"`
   * `"kleinanzeigen_condition": "neu" | "wie_neu" | "gebraucht" | "defekt"`
4. **`analyze_draft()` erweitern:**
   Mappe die neuen Felder in `draft.price_analysis`, `draft.ebay_de` und `draft.kleinanzeigen` (mit sinnvollen Fallbacks, falls ein Mock im Test nur Teilfelder liefert).

#### 2.3 Tests für Step 2 (`tests/test_phase2_pricing_and_ai.py`)
* Erweitere `test_verification_links_generation`: Prüfe `links.kleinanzeigen_search_url` (`"kleinanzeigen.de"`) und `links.idealo_url` (`"idealo.de"`).
* Erweitere `test_ai_post_processing_safeguards`:
  * Übergib `ebay_de_title` (95 Zeichen, mit `"Größe"`), `ebay_de_description` (ohne Disclaimer), `kleinanzeigen_title` (78 Zeichen, mit `"weiß"`), `kleinanzeigen_description` (ohne Disclaimer).
  * Prüfe: `len(processed["ebay_de_title"]) <= 80`, `len(processed["kleinanzeigen_title"]) <= 65`, `"ß"` ist in `ebay_de_title` / `kleinanzeigen_title` erhalten, und `"Ausschluss jeglicher Sachmängelhaftung"` ist in `ebay_de_description` und `kleinanzeigen_description` enthalten.
* **Commit nach grünem Pytest:** `feat(ai): support eBay.de and Kleinanzeigen.de pricing, orthography and BGB disclaimer`

---

### STEP 3: Lokales Web-Dashboard (`frontend/index.html` & `frontend/app.js`)

#### 3.1 Änderungen in `frontend/index.html`
1. **Section 1 (Inputs):** Ergänze neben `#shipping-preset` (Schweiz) ein Dropdown für Deutschland:
   ```html
   <div class="form-group flex-1">
     <label for="de-shipping-preset">Versand-Preset (Deutschland):</label>
     <select id="de-shipping-preset"></select>
   </div>
   ```
2. **Section 2 (Preiskarten & Prüflinks):**
   * Ergänze Preiskarten für:
     * `id="price-de-new"` (DE Neupreis Idealo/Geizhals)
     * `id="price-rec-ebay-start"` (eBay.de Startpreis EUR)
     * `id="price-rec-ebay-buynow"` (eBay.de Sofort-Kaufen EUR)
     * `id="price-rec-kleinanzeigen"` (Kleinanzeigen VB EUR)
   * Ergänze Prüflinks in `#verification-links`:
     * `<a id="link-kleinanzeigen" href="#" target="_blank" class="badge-link">Kleinanzeigen.de Suche</a>`
     * `<a id="link-idealo" href="#" target="_blank" class="badge-link">Idealo.de Neupreis</a>`
3. **Section 3 (Plattform-Vorschau):**
   Ergänze in `.platform-grid` neben Ricardo.ch und Tutti.ch zwei weitere Karten:
   * **eBay.de Card (`.ebay-de-card`):**
     * `<input type="text" id="ebay-de-title" maxlength="80">` + `<span id="ebay-de-title-count" class="counter">0/80</span>`
     * `<input type="text" id="ebay-de-category">`
     * `<select id="ebay-de-condition">` (`neu`, `wie_neu`, `gebraucht`, `defekt`)
     * `<select id="ebay-de-offer-type">` (`auction`, `fixed_price`)
     * `<input type="number" id="ebay-de-start-price" step="0.5" min="1.0">`
     * `<input type="number" id="ebay-de-buynow-price" step="0.5" min="1.0">`
     * `<textarea id="ebay-de-description" rows="12"></textarea>`
   * **Kleinanzeigen.de Card (`.kleinanzeigen-card`):**
     * `<input type="text" id="kleinanzeigen-title" maxlength="65">` + `<span id="kleinanzeigen-title-count" class="counter">0/65</span>`
     * `<input type="text" id="kleinanzeigen-category">`
     * `<select id="kleinanzeigen-condition">` (`neu`, `wie_neu`, `gebraucht`, `defekt`)
     * `<input type="number" id="kleinanzeigen-price" step="1.0" min="1.0">`
     * `<select id="kleinanzeigen-price-type">` (`<option value="vb">VB (Verhandlungsbasis)</option>`, `<option value="festpreis">Festpreis</option>`)
     * `<textarea id="kleinanzeigen-description" rows="12"></textarea>`

#### 3.2 Änderungen in `frontend/app.js`
* Befülle `#shipping-preset` mit CH-Presets (`p.country === "CH"` oder `!p.country`) und `#de-shipping-preset` mit DE-Presets (`p.country === "DE"`).
* Binde in `populateForm()`, `setupEventListeners()` (Live-Char-Counter für `#ebay-de-title` 80 und `#kleinanzeigen-title` 65) und `syncDraftFromForm()` alle Felder von `currentDraft.ebay_de` und `currentDraft.kleinanzeigen` sowie die neuen Preiskarten und Prüflinks an.

#### 3.3 Tests für Step 3 (`tests/test_phase3_api_and_ui.py`)
* Erweitere `test_full_rest_lifecycle`: Prüfe bei `PUT /api/drafts/{id}`, dass auch `analyzed["ebay_de"]["title"] = "E" * 95` auf $\le 80$ und `analyzed["kleinanzeigen"]["title"] = "K" * 80` auf $\le 65$ Zeichen gekürzt werden.
* Erweitere `test_dashboard_static_html_served_and_contains_required_elements`: Prüfe, dass `ebay-de-title`, `kleinanzeigen-title`, `ebay-de-description`, `kleinanzeigen-description` und `de-shipping-preset` im ausgelieferten HTML vorhanden sind.
* **Commit nach grünem Pytest:** `feat(ui): add eBay.de and Kleinanzeigen.de cards, presets and verification links to dashboard`

---

### STEP 4: Firefox WebExtension (`extension/manifest.json`, `background.js`, `content.js`)

#### 4.1 Änderungen in `extension/manifest.json`
* Behalte `"name": "Seller Assistant"` und `"default_title": "Seller Assistant (Berechtigungen prüfen)"` strikt neutral bei.
* Erweitere `host_permissions` und `content_scripts[0].matches` um:
  * `"*://*.ebay.de/*"`
  * `"*://*.kleinanzeigen.de/*"`

#### 4.2 Änderungen in `extension/background.js`
* Erweitere `permissions.request` im `action.onClicked`-Listener um `"*://*.ebay.de/*"` und `"*://*.kleinanzeigen.de/*"`.

#### 4.3 Änderungen in `extension/content.js`
1. **Plattform-Erkennung (`detectPlatform`, `isEbayDE`, `isKleinanzeigen`):**
   ```javascript
   function isRicardo(hostname) {
     const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
     return h.includes("ricardo.ch");
   }
   function isTutti(hostname) {
     const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
     return h.includes("tutti.ch");
   }
   function isEbayDE(hostname) {
     const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
     return h.includes("ebay.de");
   }
   function isKleinanzeigen(hostname) {
     const h = hostname || (typeof location !== "undefined" ? location.hostname : "");
     return h.includes("kleinanzeigen.de");
   }
   function detectPlatform(hostname) {
     if (isRicardo(hostname)) return "ricardo";
     if (isTutti(hostname)) return "tutti";
     if (isEbayDE(hostname)) return "ebay_de";
     if (isKleinanzeigen(hostname)) return "kleinanzeigen";
     return "unknown";
   }
   ```
2. **Rich-Text / `iframe` / `contenteditable` Beschreibungs-Injektor (`setDescriptionValue(value, rootDoc)`):**
   * Da `ebay.de/lstng` die Beschreibung oft in einem Same-Origin-`iframe` (`iframe.ux-action-menu__iframe`, `iframe[id*="desc" i]`, `iframe[title*="Beschreibung" i]`) oder einem `[contenteditable="true"]`-Element rendert, implementiere `setDescriptionValue(value, rootDoc = document)`:
     1. Suche zuerst nach einem passenden `<textarea>` (`#pstad-descrptn`, `#pstad-descr`, `textarea[name*="description" i]`, `textarea[name="body"]`, `textarea[id*="description" i]`). Falls gefunden $\rightarrow$ `setNativeValue(textarea, value)`.
     2. Suche andernfalls nach einem Beschreibungs-`iframe` (`iframe.ux-action-menu__iframe, iframe[id*="desc" i], iframe[title*="Beschreibung" i], iframe[title*="description" i]`), greife auf `iframe.contentDocument || (iframe.contentWindow && iframe.contentWindow.document)` zu, finde `.editable-text-area, [contenteditable="true"], body`, setze `innerHTML` (mit Zeilenumbrüchen `\n` $\rightarrow$ `<br>`) und löse `input`-, `change`- und `blur`-Events aus.
     3. Suche andernfalls nach einem direkten `[contenteditable="true"]`-Editor im Dokument, setze ` textContent` / `innerText` und löse `input` und `blur` aus.
3. **Plattformabhängige Feld-Zuordnung in `executeStep1`, `executeStep2` & 1-Klick-Copy-Buttons:**
   * Hilfsfunktion `getPlatformData(draft, platform)` gibt `{ title, description, condition, startPrice, buyNowPrice, currency, priceType }` je nach aktiver Plattform (`ricardo`, `tutti`, `ebay_de`, `kleinanzeigen`) zurück.
   * **Selektoren in `executeStep1` (Titel):**
     * Unterstützt `#postad-title`, `#pstad-title`, `input[name="title"]`, `input[name="pstad-title"]`, `input[name="subject"]`, `input[name*="title" i]`, `input[id*="title" i]`, `input[aria-label*="Titel" i]`, `input[placeholder*="titel" i]`, `input[data-testid*="title" i]`.
   * **Selektoren in `executeStep2` (Beschreibung, Zustand & Preise):**
     * Beschreibung über `setDescriptionValue(data.description)`.
     * Preise:
       * Auf `ricardo` und `ebay_de`: Startpreis (`input[name*="startPrice" i]`, `input[id*="start-price" i]`, `input[aria-label*="Startpreis" i]`) und Sofortkauf-Preis (`input[name*="buyNowPrice" i]`, `input[name*="buyItNowPrice" i]`, `input[id*="buy-now-price" i]`, `input[aria-label*="Sofort-Kaufen" i]`, `input[name="price"]`).
       * Auf `tutti` und `kleinanzeigen`: Preis (`#pstad-price`, `input[name="price"]`, `input[name*="price" i]`, `input[id*="price" i]`) sowie auf `kleinanzeigen` optional Preistyp (`select[name="priceType"]`, `input[name="priceType"]`).
4. **Module-Exports am Dateiende erweitern:**
   Exportiere zusätzlich `isEbayDE`, `isKleinanzeigen`, `detectPlatform` und `setDescriptionValue` in `module.exports`.

#### 4.4 Tests für Step 4 (`tests/test_phase4_extension.py`)
* Erweitere `test_manifest_v3_validity`:
  * Prüfe `manifest["name"] == "Seller Assistant"`.
  * Prüfe, dass `"ebay.de"` und `"kleinanzeigen.de"` sowohl in `host_permissions` als auch in `content_scripts[0]["matches"]` enthalten sind.
* Erweitere `test_extension_js_syntax_and_xray_and_cors_safeguards`:
  * Prüfe `node --check` für `background.js` und `content.js`.
  * Prüfe, dass `detectPlatform`, `isEbayDE`, `isKleinanzeigen` und `setDescriptionValue` in `content.js` implementiert sind.
* **Commit nach grünem Pytest:** `feat(extension): add eBay.de and Kleinanzeigen.de auto-fill and iframe description support`

---

## 4. Abschluss-Verifikation (Definition of Done)

Führe nach Abschluss von Step 4 folgende Befehle aus:

```bash
.venv/bin/pytest -v
git status
```

Alle Tests in `test_phase1_image_and_storage.py`, `test_phase2_pricing_and_ai.py`, `test_phase3_api_and_ui.py` und `test_phase4_extension.py` müssen zu **100 % grün** sein (`0 failed, 0 errors`), und `git status` muss einen sauberen Working-Tree zeigen.
