import json
from pathlib import Path
import subprocess
import pytest


def test_manifest_v3_validity():
    manifest_path = Path("extension/manifest.json")
    assert manifest_path.exists(), "extension/manifest.json does not exist"
    
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
        
    assert manifest.get("manifest_version") == 3
    assert manifest.get("name") == "OccAIsion"
    assert "background" in manifest
    assert "scripts" in manifest["background"]
    assert "background.js" in manifest["background"]["scripts"]
    
    perms = manifest.get("permissions", [])
    assert "tabs" in perms
    assert "scripting" in perms

    host_perms = manifest.get("host_permissions", [])
    assert any("127.0.0.1:8000" in p for p in host_perms)
    assert any("ricardo.ch" in p for p in host_perms)
    assert any("tutti.ch" in p for p in host_perms)
    assert any("ebay.de" in p for p in host_perms)
    assert any("kleinanzeigen.de" in p for p in host_perms)
    assert any("idealo.de" in p for p in host_perms)
    assert any("toppreise.ch" in p for p in host_perms)
    assert any("digitec.ch" in p for p in host_perms)
    assert any("galaxus.ch" in p for p in host_perms)

    matches = manifest["content_scripts"][0].get("matches", [])
    assert any("127.0.0.1" in m for m in matches)
    assert any("localhost" in m for m in matches)
    assert any("ricardo.ch" in m for m in matches)
    assert any("tutti.ch" in m for m in matches)
    assert any("ebay.de" in m for m in matches)
    assert any("kleinanzeigen.de" in m for m in matches)
    assert any("idealo.de" in m for m in matches)
    assert any("toppreise.ch" in m for m in matches)
    assert any("digitec.ch" in m for m in matches)
    assert any("galaxus.ch" in m for m in matches)
    
    # Assert all referenced files exist
    assert (Path("extension") / "background.js").exists()
    assert (Path("extension") / "content.js").exists()
    assert (Path("extension") / "panel.css").exists()


def test_extension_js_syntax_and_xray_and_cors_safeguards():
    bg_file = Path("extension/background.js")
    content_file = Path("extension/content.js")
    
    assert bg_file.exists()
    assert content_file.exists()
    
    # 1. Syntax check via Node.js
    res_bg = subprocess.run(["node", "--check", str(bg_file)], capture_output=True, text=True)
    assert res_bg.returncode == 0, f"Syntax error in background.js: {res_bg.stderr}"
    
    res_content = subprocess.run(["node", "--check", str(content_file)], capture_output=True, text=True)
    assert res_content.returncode == 0, f"Syntax error in content.js: {res_content.stderr}"
    
    content_js_code = content_file.read_text(encoding="utf-8")
    bg_js_code = bg_file.read_text(encoding="utf-8")
    
    # 2. CORS / CSP Safeguard: content.js must NEVER directly call fetch() to localhost/127.0.0.1
    assert 'fetch("http://127.0.0.1' not in content_js_code
    assert 'fetch("http://localhost' not in content_js_code
    assert "fetch('http://127.0.0.1" not in content_js_code
    assert "fetch('http://localhost" not in content_js_code
    
    # 3. background.js message handling
    assert "LIST_DRAFTS" in bg_js_code
    assert "GET_DRAFT" in bg_js_code
    assert "FETCH_DRAFT_IMAGES" in bg_js_code
    
    # 4. content.js Xray vision, native setter & Smart-Panel elements
    assert "wrappedJSObject" in content_js_code
    assert "setNativeValue" in content_js_code
    assert "DataTransfer" in content_js_code
    assert "ai-ext-step1-btn" in content_js_code
    assert "ai-ext-step2-btn" in content_js_code
    assert "ai-ext-draft-select" in content_js_code
    assert "clipboard" in content_js_code.lower()
    assert "condition" in content_js_code.lower()

    # 5. DE marketplace functions & iframe description support
    assert "detectPlatform" in content_js_code
    assert "isEbayDE" in content_js_code
    assert "isKleinanzeigen" in content_js_code
    assert "setDescriptionValue" in content_js_code

    # 5b. Tutti & Ricardo specific autofill & MUI support
    assert "field:itemCondition" in content_js_code
    assert "field:shippingAvailable" in content_js_code
    assert "fillMuiSelect" in content_js_code
    assert "autoSelectTuttiCategory" in content_js_code
    assert 'input[name="subject"]' in content_js_code
    assert "listingType" in content_js_code
    assert "fillRicardoPrices" in content_js_code
    assert "SellingUI.start_price" in content_js_code
    assert "fillRicardoShipping" in content_js_code
    assert "shipping-cost-input" in content_js_code

    # 6. 6-source hybrid price scraper & dashboard bridge
    assert "SCRAPE_ALL_PRICE_SOURCES" in bg_js_code
    assert "scrapeSourceHybrid" in bg_js_code
    assert "LH_ItemCondition=3000" in bg_js_code
    assert "global.zustand:alright%2Clike_new%2Cok" in bg_js_code
    assert "anbieter:privat" in bg_js_code
    assert "isLocalDashboard" in content_js_code
    assert "OCCAISION_SCRAPE_PRICES" in content_js_code


def test_extension_price_parser_and_stats_via_node():
    node_script = """
    const fs = require('fs');
    const bg = require('./extension/background.js');

    // Test Kleinanzeigen verification URL structure
    const links = bg.buildVerificationLinks('HP Color LaserJet');
    if (!links.kleinanzeigen_search_url.includes('anbieter:privat') || !links.kleinanzeigen_search_url.includes('global.zustand:alright%2Clike_new%2Cok')) {
      throw new Error('Kleinanzeigen search url missing condition or private filter: ' + links.kleinanzeigen_search_url);
    }
    if (!links.ricardo_search_url.includes('item_condition=used') || !links.ricardo_search_url.includes('seller_type=individual') || !links.ricardo_search_url.includes('HP%20Color%20LaserJet')) {
      throw new Error('Ricardo search url invalid: ' + links.ricardo_search_url);
    }
    if (!links.tutti_search_url.includes('tutti.ch')) {
      throw new Error('Tutti search url invalid: ' + links.tutti_search_url);
    }

    // Test Kleinanzeigen JSON parsing
    const kaJsonContent = fs.readFileSync('temp/kleinanzeigen.json', 'utf8');
    const kaItems = bg.extractKleinanzeigenItems(kaJsonContent);
    if (!Array.isArray(kaItems) || kaItems.length !== 25) {
      throw new Error('Expected 25 kleinanzeigen items from temp/kleinanzeigen.json, got: ' + (kaItems ? kaItems.length : 0));
    }
    for (const item of kaItems) {
      if (!item.title || typeof item.price !== 'number' || item.posterType !== 'PRIVATE') {
        throw new Error('Invalid kleinanzeigen item: ' + JSON.stringify(item));
      }
    }
    const kaPrices = bg.extractPricesFromHtml('kleinanzeigen', kaJsonContent);
    if (kaPrices.length !== 25 || kaPrices[0] !== 50) {
      throw new Error('Unexpected extractPricesFromHtml for kleinanzeigen: ' + JSON.stringify(kaPrices));
    }

    // Test Idealo extraction for .sr-resultList_* .sr-detailedPriceInfo__price_* (first entry only)
    const idealoHtml = `
      <div class="sr-resultList_NAJkZ">
        <div class="sr-resultList__item">
          <div class="sr-productSummary__title_f5flP productSummary__title--GRID">HP Color LaserJet Pro MFP 4302dw (4RA83F)</div>
          <span class="sr-detailedPriceInfo__price_sYVmx">499,00 €</span>
        </div>
        <div class="sr-resultList__item">
          <div class="sr-productSummary__title_f5flP">HP Toner Schwarz</div>
          <span class="sr-detailedPriceInfo__price_sYVmx">65,00 €</span>
        </div>
      </div>
    `;
    const idealoItems = bg.extractIdealoItems(idealoHtml);
    if (!idealoItems || idealoItems.length !== 1) {
      throw new Error('Expected exactly 1 idealo item (top product), got: ' + JSON.stringify(idealoItems));
    }
    if (idealoItems[0].price !== 499 || idealoItems[0].title !== 'HP Color LaserJet Pro MFP 4302dw (4RA83F)') {
      throw new Error('Unexpected idealo item 0: ' + JSON.stringify(idealoItems[0]));
    }
    const idealoPrices = bg.extractPricesFromHtml('idealo', idealoHtml);
    if (idealoPrices.length !== 1 || idealoPrices[0] !== 499) {
      throw new Error('Expected exactly [499] in idealoPrices: ' + JSON.stringify(idealoPrices));
    }

    // Test real Idealo HTML with window.csr.initialData (no background tab DOM rendering required)
    const realIdealoHtml = fs.readFileSync('temp/idealo.html', 'utf8');
    const realIdealoItems = bg.extractIdealoItems(realIdealoHtml);
    if (!realIdealoItems || realIdealoItems.length !== 1) {
      throw new Error('Expected 1 idealo item from temp/idealo.html via window.csr, got: ' + JSON.stringify(realIdealoItems));
    }
    if (realIdealoItems[0].price !== 499 || !realIdealoItems[0].title.includes('HP Color LaserJet Pro MFP 4302fdw')) {
      throw new Error('Unexpected real idealo item: ' + JSON.stringify(realIdealoItems[0]));
    }
    const realIdealoPrices = bg.extractPricesFromHtml('idealo', realIdealoHtml);
    if (realIdealoPrices.length !== 1 || realIdealoPrices[0] !== 499) {
      throw new Error('Expected [499] from extractPricesFromHtml for real idealo HTML, got: ' + JSON.stringify(realIdealoPrices));
    }

    // Test Toppreise extraction for single product page and search result list (first entry only)
    const tpSingleHtml = fs.readFileSync('temp/toppreise-SONY Alpha 7 V Body (ILCE7M5B) ab CHF 2\\'173.45 bei Toppreise.ch.html', 'utf8');
    const tpSingleItems = bg.extractToppreiseItems(tpSingleHtml);
    if (!tpSingleItems || tpSingleItems.length !== 1) {
      throw new Error('Expected exactly 1 toppreise item from single product page, got: ' + JSON.stringify(tpSingleItems));
    }
    if (tpSingleItems[0].price !== 2173.45 || !tpSingleItems[0].title.includes('SONY Alpha 7 V')) {
      throw new Error('Unexpected toppreise single item: ' + JSON.stringify(tpSingleItems[0]));
    }

    const tpListHtml = fs.readFileSync('temp/toppreise-Alpha 7 V - Preisvergleich und Bewertungen bei Toppreise.ch.html', 'utf8');
    const tpListItems = bg.extractToppreiseItems(tpListHtml);
    if (!tpListItems || tpListItems.length !== 1) {
      throw new Error('Expected exactly 1 toppreise item from search list, got: ' + JSON.stringify(tpListItems));
    }
    if (tpListItems[0].price !== 2173.45 || !tpListItems[0].title.includes('SONY Alpha 7 V')) {
      throw new Error('Unexpected toppreise list item: ' + JSON.stringify(tpListItems[0]));
    }

    const tpHpHtml = fs.readFileSync('temp/toppreise-HP Color LaserJet Pro MFP 4302fdw - Preisvergleich und Bewertungen bei Toppreise.ch.htm', 'utf8');
    const tpHpItems = bg.extractToppreiseItems(tpHpHtml);
    if (!tpHpItems || tpHpItems.length !== 1) {
      throw new Error('Expected exactly 1 toppreise item from HP list, got: ' + JSON.stringify(tpHpItems));
    }
    if (tpHpItems[0].price !== 387 || !tpHpItems[0].title.includes('HP Color LaserJet Pro MFP 4302fdw')) {
      throw new Error('Unexpected toppreise HP item: ' + JSON.stringify(tpHpItems[0]));
    }
    const tpPrices = bg.extractPricesFromHtml('toppreise', tpHpHtml);
    if (tpPrices.length !== 1 || tpPrices[0] !== 387) {
      throw new Error('Expected exactly [387] from extractPricesFromHtml toppreise, got: ' + JSON.stringify(tpPrices));
    }

    // Test Swiss notation with entities and HTML snippet: <div class="Plugin_Price "> 2'173.45 </div>
    const swissCases = [
      '<div class="Plugin_Price "> 2\\\'173.45 </div>',
      '<div class="Plugin_Price "> 2&#39;173.45 </div>',
      '<div class="Plugin_Price "> 2&apos;173.45 </div>',
      '<div class="Plugin_Price "> 2&#x27;173.45 </div>',
      '<div class="Plugin_Price "> 2’173.45 </div>',
      '<div class="Plugin_Price "> 2`173.45 </div>',
      '<div class="Plugin_Price "> 2 173.45 </div>',
      '<div class="Plugin_Price "> 2\\u202f173.45 </div>',
      '<div class="Plugin_Price "> 2&nbsp;173.45 </div>',
      '2\\\'173.–'
    ];
    for (const sc of swissCases) {
      const parsed = bg.parsePriceText(sc);
      if (parsed !== 2173.45 && parsed !== 2173) {
        throw new Error('Swiss price parsing failed for ' + sc + ', got: ' + parsed);
      }
    }

    // Test Galaxus / Digitec extraction for first product
    const galaxusHtml = fs.readFileSync('temp/galaxus-HP Color LaserJet Pro MFP 4302fdw_ Suche - Galaxus.html', 'utf8');
    const galaxusItems = bg.extractDigitecItems(galaxusHtml);
    if (!galaxusItems || galaxusItems.length !== 1) {
      throw new Error('Expected exactly 1 galaxus item, got: ' + JSON.stringify(galaxusItems));
    }
    if (galaxusItems[0].price !== 428 || !galaxusItems[0].title.includes('HP Color LaserJet Pro MFP 4302fdw')) {
      throw new Error('Unexpected galaxus item 0: ' + JSON.stringify(galaxusItems[0]));
    }
    const galaxusPrices = bg.extractPricesFromHtml('digitec', galaxusHtml);
    if (galaxusPrices.length !== 1 || galaxusPrices[0] !== 428) {
      throw new Error('Expected [428] from extractPricesFromHtml for digitec/galaxus: ' + JSON.stringify(galaxusPrices));
    }

    const digitecHtml = fs.readFileSync('temp/digitec-HP Color LaserJet Pro MFP 4302fdw_ Suche - Digitec.html', 'utf8');
    const digitecItems = bg.extractDigitecItems(digitecHtml);
    if (!digitecItems || digitecItems.length !== 1) {
      throw new Error('Expected exactly 1 digitec item, got: ' + JSON.stringify(digitecItems));
    }
    if (digitecItems[0].price !== 428 || !digitecItems[0].title.includes('HP Color LaserJet Pro MFP 4302fdw')) {
      throw new Error('Unexpected digitec item 0: ' + JSON.stringify(digitecItems[0]));
    }

    const ricardoHtml = fs.readFileSync('temp/ricardo-Hp Color Laserjet Pro Mfp 4302fdw kaufen _ Günstig auf Ricardo.ch finden.html', 'utf8');
    const ricardoItems = bg.extractRicardoItems(ricardoHtml);
    if (!Array.isArray(ricardoItems) || ricardoItems.length !== 1) {
      throw new Error('Expected exactly 1 regular ricardo item (excluding relaxed search keywords), got: ' + (ricardoItems ? ricardoItems.length : 0));
    }
    if (ricardoItems[0].price !== 300 || !ricardoItems[0].title.includes('HP Color LaserJet Pro MFP 4302fdw')) {
      throw new Error('Unexpected ricardo item 0: ' + JSON.stringify(ricardoItems[0]));
    }
    const ricardoPrices = bg.extractPricesFromHtml('ricardo', ricardoHtml);
    if (!ricardoPrices || ricardoPrices.length !== 1 || ricardoPrices[0] !== 300) {
      throw new Error('Expected [300] from extractPricesFromHtml for regular ricardo results, got: ' + JSON.stringify(ricardoPrices));
    }

    const tuttiHtml = fs.readFileSync('temp/tutti-13 Inserate für _HP Color LaserJet Pro MFP 4302fdw_ in Alle Kategorien - tutti.html', 'utf8');
    const tuttiItems = bg.extractTuttiItems(tuttiHtml);
    if (!Array.isArray(tuttiItems) || tuttiItems.length !== 13) {
      throw new Error('Expected exactly 13 tutti items (excluding Ricardo ads), got: ' + (tuttiItems ? tuttiItems.length : 0));
    }
    if (tuttiItems[0].price !== 250 || !tuttiItems[0].title.includes('HP Color LaserJet Pro MFP 4302fdw')) {
      throw new Error('Unexpected tutti item 0: ' + JSON.stringify(tuttiItems[0]));
    }
    const tuttiPrices = bg.extractPricesFromHtml('tutti', tuttiHtml);
    if (!tuttiPrices || tuttiPrices.length !== 13 || tuttiPrices[0] !== 250) {
      throw new Error('Expected 13 prices starting with 250 from extractPricesFromHtml for tutti, got: ' + JSON.stringify(tuttiPrices));
    }
    const copytronItem = tuttiItems.find(it => it.title.includes('cyan Toner, 220X, W2201X'));
    if (!copytronItem || copytronItem.price !== 178) {
      throw new Error('Expected price 178 for Copytron cyan toner with logo (not postal code 8152), got: ' + JSON.stringify(copytronItem));
    }

    const ebayHtml = `
      <div class="s-item"><div class="s-item__title">Shop on eBay</div><span class="s-item__price">EUR 19,99</span></div>
      <div class="s-item"><div class="s-item__title">HP 4302fdw</div><span class="s-item__price">EUR 250,00</span></div>
      <div class="s-item"><div class="s-item__title">HP 4302fdw Drucker</div><span class="s-item__price">290,00 €</span></div>
      <div class="s-item"><div class="s-item__title">HP 4302fdw Spanne</div><span class="s-item__price">EUR 100,00 bis EUR 400,00</span></div>
    `;
    const ebayPrices = bg.extractPricesFromHtml('ebay_de_sold', ebayHtml);
    if (ebayPrices.length !== 2 || ebayPrices[0] !== 250 || ebayPrices[1] !== 290) {
      throw new Error('Unexpected ebay prices: ' + JSON.stringify(ebayPrices));
    }
    const ebayItems = bg.extractEbayItemsFromHtml(ebayHtml);
    if (ebayItems.length !== 2) {
      throw new Error('Expected 2 ebay items, got ' + ebayItems.length);
    }
    if (ebayItems[0].title !== 'HP 4302fdw' || ebayItems[0].price !== 250) {
      throw new Error('Unexpected ebay item[0]: ' + JSON.stringify(ebayItems[0]));
    }

    const ebayFewerKeywordsHtml = `
      <div class="s-item"><div class="s-item__title">HP 4302fdw</div><span class="s-item__price">EUR 250,00</span></div>
      <div class="s-item"><div class="s-item__title">HP 4302fdw Drucker</div><span class="s-item__price">290,00 €</span></div>
      <div class="srp-river-answer"><h3>Ergebnisse für weniger Suchbegriffe</h3></div>
      <div class="s-item"><div class="s-item__title">HP Toner Schwarz</div><span class="s-item__price">50,00 €</span></div>
      <div class="s-item"><div class="s-item__title">Anderes Modell</div><span class="s-item__price">465,82 €</span></div>
    `;
    const filteredItems = bg.extractEbayItemsFromHtml(ebayFewerKeywordsHtml);
    if (filteredItems.length !== 2) {
      throw new Error('Expected 2 items before fewer words divider, got: ' + filteredItems.length);
    }
    const stats = bg.computeSourceStats(
      { id: 'ebay_de_sold', label: 'eBay DE (Gebraucht & Beendet)', currency: 'EUR' },
      ebayPrices,
      'https://www.ebay.de/test',
      'fetch',
      0.94
    );
    if (stats.sample_count !== 2 || stats.median_price !== 270 || stats.median_chf !== 253.8) {
      throw new Error('Unexpected stats: ' + JSON.stringify(stats));
    }

    const jsonLdHtml = `
      <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"Product","offers":{"@type":"AggregateOffer","lowPrice":"419.00","priceCurrency":"CHF"}}
      </script>
    `;
    const digitecPrices = bg.extractPricesFromHtml('digitec', jsonLdHtml);
    if (!digitecPrices.includes(419)) {
      throw new Error('Expected 419 from JSON-LD: ' + JSON.stringify(digitecPrices));
    }

    // Verify eBay login detection
    if (!bg.isEbayLoginRequired('<html><head><title>Bitte einloggen | eBay</title></head><body><form id="signin-form"></form></body></html>', 'https://signin.ebay.de/ws/eBayISAPI.dll?SignIn')) {
      throw new Error('Expected isEbayLoginRequired to detect signin page');
    }
    if (bg.isEbayLoginRequired(ebayHtml, 'https://www.ebay.de/sch/i.html?_nkw=HP')) {
      throw new Error('Expected isEbayLoginRequired to be false on valid search results');
    }
    const loginStats = bg.computeSourceStats(
      { id: 'ebay_de_sold', label: 'eBay DE (Gebraucht & Beendet)', currency: 'EUR' },
      [],
      'https://www.ebay.de/test',
      'tab',
      0.94,
      { login_required: true, error: 'Login auf ebay.de erforderlich' }
    );
    if (!loginStats.login_required || !loginStats.error) {
      throw new Error('Expected login_required=true in stats: ' + JSON.stringify(loginStats));
    }
    (async () => {
      // Test enabledSources filtering in scrapeAllPriceSources
      const resEnabled = await bg.scrapeAllPriceSources('Test Query', 0.94, ['kleinanzeigen', 'toppreise']);
      const keys = Object.keys(resEnabled.sources);
      if (keys.length !== 2 || !resEnabled.sources.kleinanzeigen || !resEnabled.sources.toppreise) {
        throw new Error('Expected only kleinanzeigen and toppreise: ' + JSON.stringify(keys));
      }
      if (resEnabled.sources.ebay_de_sold || resEnabled.sources.idealo) {
        throw new Error('resEnabled.sources has disabled keys: ' + JSON.stringify(keys));
      }

      // Test keepTabsOpen behavior in scrapeViaBackgroundTab
      let removedTabs = [];
      global.browser = {
        tabs: {
          create: async () => ({ id: 42 }),
          onUpdated: { addListener: (cb) => setTimeout(() => cb(42, { status: "complete" }), 10), removeListener: () => {} },
          remove: async (id) => { removedTabs.push(id); },
        },
        scripting: {
          executeScript: async () => [{ result: { html: "", currentUrl: "", priceNodes: [] } }]
        }
      };

      // 1. When keepTabsOpen = false -> tab 42 must be removed
      removedTabs = [];
      await bg.scrapeViaBackgroundTab("https://example.com", "toppreise", false);
      if (!removedTabs.includes(42)) {
        throw new Error("Expected tab 42 to be removed when keepTabsOpen=false");
      }

      // 2. When keepTabsOpen = true -> tab 42 must NOT be removed
      removedTabs = [];
      await bg.scrapeViaBackgroundTab("https://example.com", "toppreise", true);
      if (removedTabs.includes(42)) {
        throw new Error("Expected tab 42 NOT to be removed when keepTabsOpen=true");
      }
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"


def test_extension_ricardo_price_autofill_via_node():
    node_script = """
    const content = require('./extension/content.js');

    (async () => {
      let events = [];
      const startPriceMock = {
        value: '',
        dispatchEvent: (ev) => events.push('start:' + ev.type)
      };

      const buyNowPriceMock = {
        value: '',
        dispatchEvent: (ev) => events.push('buynow:' + ev.type)
      };

      let fixedPriceToggled = false;
      const fixedPriceSwitchMock = {
        checked: false,
        click: () => {
          fixedPriceToggled = true;
          fixedPriceSwitchMock.checked = true;
        }
      };

      global.Event = function(type) { this.type = type; };
      global.document = {
        getElementById: (id) => {
          if (id === 'SellingUI.start_price') return startPriceMock;
          if (id === 'price') return fixedPriceToggled ? buyNowPriceMock : null;
          return null;
        },
        querySelector: (selector) => {
          if (selector.includes('SellingUI.start_price') || selector.includes('start_price')) {
            return startPriceMock;
          }
          if (selector.includes('FixedPrice')) {
            return fixedPriceSwitchMock;
          }
          if (selector.includes('price')) {
            return fixedPriceToggled ? buyNowPriceMock : null;
          }
          return null;
        },
        querySelectorAll: () => []
      };

      const draft = {
        id: 'test-draft',
        ricardo: {
          start_price_chf: 50.0,
          buynow_price_chf: 120.0,
          offer_type: 'auction'
        }
      };

      const data = content.getPlatformData(draft, 'ricardo');
      if (data.startPrice !== 50.0 || data.buyNowPrice !== 120.0) {
        throw new Error('Unexpected getPlatformData: ' + JSON.stringify(data));
      }

      await content.fillRicardoPrices(draft, data);

      if (startPriceMock.value !== '50') {
        throw new Error('Expected startPriceMock.value to be "50", got: ' + startPriceMock.value);
      }
      if (!fixedPriceToggled) {
        throw new Error('Expected FixedPrice toggle switch to have been clicked');
      }
      if (buyNowPriceMock.value !== '120') {
        throw new Error('Expected buyNowPriceMock.value to be "120", got: ' + buyNowPriceMock.value);
      }
      if (!events.includes('start:input') || !events.includes('buynow:input')) {
        throw new Error('Expected input events to be dispatched, got: ' + JSON.stringify(events));
      }
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"


def test_extension_ricardo_shipping_autofill_via_node():
    node_script = """
    const content = require('./extension/content.js');

    (async () => {
      // 1. Test standard default shipping (b_post_2kg): turns on shipping switch
      let shippingToggled = false;
      const shippingSwitch = {
        checked: false,
        click: () => {
          shippingToggled = true;
          shippingSwitch.checked = true;
        }
      };

      const pickupSwitch = {
        checked: true,
        click: () => { pickupSwitch.checked = !pickupSwitch.checked; }
      };

      global.Event = function(type) { this.type = type; };
      global.document = {
        querySelector: (selector) => {
          if (selector.includes('Shipping')) return shippingSwitch;
          if (selector.includes('Pickup')) return pickupSwitch;
          return null;
        },
        querySelectorAll: () => []
      };

      const draft2kg = {
        ricardo: { shipping_preset_id: 'b_post_2kg' }
      };

      await content.fillRicardoShipping(draft2kg);

      if (!shippingToggled) {
        throw new Error('Expected Shipping switch to be activated for b_post_2kg');
      }

      // 2. Test non-default shipping (b_post_10kg): clicks Bearbeiten, Dialog 1 Paket, Dialog 2 10kg, Speichern
      let editClicked = false;
      let paketCategoryClicked = false;
      let chip10kgClicked = false;
      let saveClicked = false;
      let costInputValue = '';

      const editBtn = {
        textContent: 'Bearbeiten',
        click: () => { editClicked = true; }
      };

      const paketCatBtn = {
        textContent: 'Paket',
        click: () => { paketCategoryClicked = true; }
      };

      const chip10kg = {
        textContent: 'bis 10kg',
        click: () => { chip10kgClicked = true; }
      };

      const costInput = {
        value: '',
        dispatchEvent: () => {}
      };

      const saveBtn = {
        textContent: 'Speichern',
        disabled: false,
        click: () => { saveClicked = true; }
      };

      let dialogStep = 1;
      const dialogMock = {
        querySelectorAll: (sel) => {
          if (dialogStep === 1) {
            return [paketCatBtn];
          } else {
            return [chip10kg, saveBtn];
          }
        },
        querySelector: (sel) => {
          if (sel.includes('shipping-cost-input')) return costInput;
          return null;
        }
      };

      // Wrap click on paket to advance dialog step
      paketCatBtn.click = () => {
        paketCategoryClicked = true;
        dialogStep = 2;
      };

      global.document = {
        querySelector: (selector) => {
          if (selector.includes('Shipping')) return { checked: true, click: () => {} };
          if (selector.includes('Pickup')) return { checked: true, click: () => {} };
          if (selector.includes('dialog')) return dialogMock;
          return null;
        },
        querySelectorAll: (selector) => {
          if (selector.includes('button')) return [editBtn];
          return [];
        }
      };

      const draft10kg = {
        ricardo: { shipping_preset_id: 'b_post_10kg' }
      };

      await content.fillRicardoShipping(draft10kg);

      if (!editClicked) throw new Error('Expected Bearbeiten button to be clicked');
      if (!paketCategoryClicked) throw new Error('Expected Paket category button to be clicked');
      if (!chip10kgClicked) throw new Error('Expected 10kg chip to be clicked');
      if (!saveClicked) throw new Error('Expected Speichern button to be clicked');
      if (costInput.value !== '12') throw new Error('Expected cost input to be "12", got: ' + costInput.value);

    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"

