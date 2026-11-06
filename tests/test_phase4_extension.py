import json
import subprocess
from pathlib import Path

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
    assert "FETCH_EXTERNAL_IMAGE" in bg_js_code

    # 4. content.js Xray vision, native setter & Smart-Panel elements
    assert "wrappedJSObject" in content_js_code
    assert "setNativeValue" in content_js_code
    assert "DataTransfer" in content_js_code
    assert "ai-ext-step1-btn" in content_js_code
    assert "ai-ext-step2-btn" in content_js_code
    assert "ai-ext-step3-btn" in content_js_code
    assert "executeEbayStep1" in content_js_code
    assert "executeEbayStep2" in content_js_code
    assert "executeEbayStep3" in content_js_code
    assert "selectEbayProductMatch" in content_js_code
    assert "extractEbayStockImageUrl" in content_js_code
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
    const links = bg.buildVerificationLinks('RetroWidget Hyper Pro');
    if (!links.kleinanzeigen_search_url.includes('anbieter:privat') || !links.kleinanzeigen_search_url.includes('global.zustand:alright%2Clike_new%2Cok')) {
      throw new Error('Kleinanzeigen search url missing condition or private filter: ' + links.kleinanzeigen_search_url);
    }
    if (!links.ricardo_search_url.includes('item_condition=used') || !links.ricardo_search_url.includes('seller_type=individual') || !links.ricardo_search_url.includes('RetroWidget%20Hyper%20Pro')) {
      throw new Error('Ricardo search url invalid: ' + links.ricardo_search_url);
    }
    if (!links.tutti_search_url.includes('tutti.ch')) {
      throw new Error('Tutti search url invalid: ' + links.tutti_search_url);
    }

    // Test Kleinanzeigen JSON parsing
    const kaJsonObj = {
      result: {
        resultList: Array.from({ length: 25 }, (_, i) => ({
          organicAdPreview: {
            id: 'ka-' + i,
            title: 'RetroWidget Hyper Pro Angebot ' + i,
            price: i === 0 ? '50 €' : (50 + i) + ' €',
            posterType: 'PRIVATE',
            condition: 'Gebraucht'
          }
        }))
      }
    };
    const kaJsonContent = JSON.stringify(kaJsonObj);
    const kaItems = bg.extractKleinanzeigenItems(kaJsonContent);
    if (!Array.isArray(kaItems) || kaItems.length !== 25) {
      throw new Error('Expected 25 kleinanzeigen items, got: ' + (kaItems ? kaItems.length : 0));
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
          <div class="sr-productSummary__title_f5flP productSummary__title--GRID">Acme Gizmo Pro 500 (AG-500)</div>
          <span class="sr-detailedPriceInfo__price_sYVmx">499,00 €</span>
        </div>
        <div class="sr-resultList__item">
          <div class="sr-productSummary__title_f5flP">Acme Gizmo Zubehör</div>
          <span class="sr-detailedPriceInfo__price_sYVmx">65,00 €</span>
        </div>
      </div>
    `;
    const idealoItems = bg.extractIdealoItems(idealoHtml);
    if (!idealoItems || idealoItems.length !== 1) {
      throw new Error('Expected exactly 1 idealo item (top product), got: ' + JSON.stringify(idealoItems));
    }
    if (idealoItems[0].price !== 499 || idealoItems[0].title !== 'Acme Gizmo Pro 500 (AG-500)') {
      throw new Error('Unexpected idealo item 0: ' + JSON.stringify(idealoItems[0]));
    }
    const idealoPrices = bg.extractPricesFromHtml('idealo', idealoHtml);
    if (idealoPrices.length !== 1 || idealoPrices[0] !== 499) {
      throw new Error('Expected exactly [499] in idealoPrices: ' + JSON.stringify(idealoPrices));
    }

    // Test real Idealo HTML with window.csr.initialData (no background tab DOM rendering required)
    const csrPayload = Buffer.from(JSON.stringify({
      items: [
        {
          title: 'RetroWidget Hyper Pro',
          rawPrice: 499,
          offerInfo: { formattedPrice: '499,00 €' }
        }
      ]
    })).toString('base64');
    const realIdealoHtml = `<script>window.csr.initialData['searchResult'] = '${csrPayload}';</script>`;
    const realIdealoItems = bg.extractIdealoItems(realIdealoHtml);
    if (!realIdealoItems || realIdealoItems.length !== 1) {
      throw new Error('Expected 1 idealo item via window.csr, got: ' + JSON.stringify(realIdealoItems));
    }
    if (realIdealoItems[0].price !== 499 || !realIdealoItems[0].title.includes('RetroWidget Hyper Pro')) {
      throw new Error('Unexpected real idealo item: ' + JSON.stringify(realIdealoItems[0]));
    }
    const realIdealoPrices = bg.extractPricesFromHtml('idealo', realIdealoHtml);
    if (realIdealoPrices.length !== 1 || realIdealoPrices[0] !== 499) {
      throw new Error('Expected [499] from extractPricesFromHtml for real idealo HTML, got: ' + JSON.stringify(realIdealoPrices));
    }

    // Test Toppreise extraction for single product page and search result list (first entry only)
    const tpSingleHtml = `
      <script type="application/ld+json">
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "XenoPix Alpha 99 Body (XP99B)",
        "offers": {
          "@type": "AggregateOffer",
          "lowPrice": "2'173.45",
          "priceCurrency": "CHF"
        }
      }
      </script>
    `;
    const tpSingleItems = bg.extractToppreiseItems(tpSingleHtml);
    if (!tpSingleItems || tpSingleItems.length !== 1) {
      throw new Error('Expected exactly 1 toppreise item from single product page, got: ' + JSON.stringify(tpSingleItems));
    }
    if (tpSingleItems[0].price !== 2173.45 || !tpSingleItems[0].title.includes('XenoPix Alpha 99')) {
      throw new Error('Unexpected toppreise single item: ' + JSON.stringify(tpSingleItems[0]));
    }

    const tpListHtml = `
      <main>
        <div class="Plugin_Product">
          <a class="bold" href="/preisvergleich/xenopix-alpha-99">XenoPix Alpha 99 Body</a>
          <div class="Plugin_Price">2'173.45</div>
        </div>
      </main>
    `;
    const tpListItems = bg.extractToppreiseItems(tpListHtml);
    if (!tpListItems || tpListItems.length !== 1) {
      throw new Error('Expected exactly 1 toppreise item from search list, got: ' + JSON.stringify(tpListItems));
    }
    if (tpListItems[0].price !== 2173.45 || !tpListItems[0].title.includes('XenoPix Alpha 99')) {
      throw new Error('Unexpected toppreise list item: ' + JSON.stringify(tpListItems[0]));
    }

    const tpHpHtml = `
      <main>
        <div class="Plugin_Product">
          <a class="bold" href="/preisvergleich/retrowidget-hyper-pro">RetroWidget Hyper Pro</a>
          <div class="Plugin_Price">387.00</div>
        </div>
      </main>
    `;
    const tpHpItems = bg.extractToppreiseItems(tpHpHtml);
    if (!tpHpItems || tpHpItems.length !== 1) {
      throw new Error('Expected exactly 1 toppreise item from HP list, got: ' + JSON.stringify(tpHpItems));
    }
    if (tpHpItems[0].price !== 387 || !tpHpItems[0].title.includes('RetroWidget Hyper Pro')) {
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
    const galaxusHtml = `
      <article>
        <a href="/product/123" aria-label="RetroWidget Hyper Pro">RetroWidget Hyper Pro</a>
        <div>CHF 428.–</div>
      </article>
    `;
    const galaxusItems = bg.extractDigitecItems(galaxusHtml);
    if (!galaxusItems || galaxusItems.length !== 1) {
      throw new Error('Expected exactly 1 galaxus item, got: ' + JSON.stringify(galaxusItems));
    }
    if (galaxusItems[0].price !== 428 || !galaxusItems[0].title.includes('RetroWidget Hyper Pro')) {
      throw new Error('Unexpected galaxus item 0: ' + JSON.stringify(galaxusItems[0]));
    }
    const galaxusPrices = bg.extractPricesFromHtml('digitec', galaxusHtml);
    if (galaxusPrices.length !== 1 || galaxusPrices[0] !== 428) {
      throw new Error('Expected [428] from extractPricesFromHtml for digitec/galaxus: ' + JSON.stringify(galaxusPrices));
    }

    const digitecHtml = `
      <article>
        <a href="/product/456" aria-label="RetroWidget Hyper Pro">RetroWidget Hyper Pro</a>
        <div>CHF 428.–</div>
      </article>
    `;
    const digitecItems = bg.extractDigitecItems(digitecHtml);
    if (!digitecItems || digitecItems.length !== 1) {
      throw new Error('Expected exactly 1 digitec item, got: ' + JSON.stringify(digitecItems));
    }
    if (digitecItems[0].price !== 428 || !digitecItems[0].title.includes('RetroWidget Hyper Pro')) {
      throw new Error('Unexpected digitec item 0: ' + JSON.stringify(digitecItems[0]));
    }

    const ricardoHtml = `
      <div data-testid="regular-results">
        <a href="/de/a/retrowidget-123">
          <span class="MuiTypography-body1">RetroWidget Hyper Pro</span>
          <span>300.00 Sofort kaufen</span>
        </a>
        <h2>Ergebnisse für ähnliche Suchbegriffe</h2>
        <a href="/de/a/retrowidget-relaxed-456">
          <span class="MuiTypography-body1">RetroWidget Relaxed</span>
          <span>150.00 Sofort kaufen</span>
        </a>
      </div>
    `;
    const ricardoItems = bg.extractRicardoItems(ricardoHtml);
    if (!Array.isArray(ricardoItems) || ricardoItems.length !== 1) {
      throw new Error('Expected exactly 1 regular ricardo item (excluding relaxed search keywords), got: ' + (ricardoItems ? ricardoItems.length : 0));
    }
    if (ricardoItems[0].price !== 300 || !ricardoItems[0].title.includes('RetroWidget Hyper Pro')) {
      throw new Error('Unexpected ricardo item 0: ' + JSON.stringify(ricardoItems[0]));
    }
    const ricardoPrices = bg.extractPricesFromHtml('ricardo', ricardoHtml);
    if (!ricardoPrices || ricardoPrices.length !== 1 || ricardoPrices[0] !== 300) {
      throw new Error('Expected [300] from extractPricesFromHtml for regular ricardo results, got: ' + JSON.stringify(ricardoPrices));
    }

    let tuttiHtml = `
      <div data-private-srp-listing-item-id="ricardo-ad">
        <a href="https://www.ricardo.ch/de/a/ad-1">Sponsored Ricardo</a>
        <h2>Gesponserte Ricardo Anzeige</h2>
        <span>99.–</span>
      </div>
      <div data-private-srp-listing-item-id="item-0">
        <a href="/vi/item-0">Link 0</a>
        <h2>RetroWidget Hyper Pro</h2>
        <span>250.–</span>
      </div>
      <div data-private-srp-listing-item-id="item-1">
        <a href="/vi/item-1">Link 1</a>
        <span class="badge">Logo MegaVendor 8152 Glattbrugg</span>
        <h2>ChromaModule Cyan 99X</h2>
        <span>178.–</span>
      </div>
    `;
    for (let i = 2; i < 13; i++) {
      tuttiHtml += `
        <div data-private-srp-listing-item-id="item-` + i + `">
          <a href="/vi/item-` + i + `">Link ` + i + `</a>
          <h2>RetroWidget Accessoire ` + i + `</h2>
          <span>` + (50 + i * 10) + `.–</span>
        </div>
      `;
    }
    const tuttiItems = bg.extractTuttiItems(tuttiHtml);
    if (!Array.isArray(tuttiItems) || tuttiItems.length !== 13) {
      throw new Error('Expected exactly 13 tutti items (excluding Ricardo ads), got: ' + (tuttiItems ? tuttiItems.length : 0));
    }
    if (tuttiItems[0].price !== 250 || !tuttiItems[0].title.includes('RetroWidget Hyper Pro')) {
      throw new Error('Unexpected tutti item 0: ' + JSON.stringify(tuttiItems[0]));
    }
    const tuttiPrices = bg.extractPricesFromHtml('tutti', tuttiHtml);
    if (!tuttiPrices || tuttiPrices.length !== 13 || tuttiPrices[0] !== 250) {
      throw new Error('Expected 13 prices starting with 250 from extractPricesFromHtml for tutti, got: ' + JSON.stringify(tuttiPrices));
    }
    const vendorItem = tuttiItems.find(it => it.title.includes('ChromaModule Cyan 99X'));
    if (!vendorItem || vendorItem.price !== 178) {
      throw new Error('Expected price 178 for vendor cyan module with logo (not postal code 8152), got: ' + JSON.stringify(vendorItem));
    }

    const ebayHtml = `
      <div class="s-item"><div class="s-item__title">Shop on eBay</div><span class="s-item__price">EUR 19,99</span></div>
      <div class="s-item"><div class="s-item__title">RetroWidget Pro</div><span class="s-item__price">EUR 250,00</span></div>
      <div class="s-item"><div class="s-item__title">RetroWidget Pro Gerät</div><span class="s-item__price">290,00 €</span></div>
      <div class="s-item"><div class="s-item__title">RetroWidget Pro Spanne</div><span class="s-item__price">EUR 100,00 bis EUR 400,00</span></div>
    `;
    const ebayPrices = bg.extractPricesFromHtml('ebay_de_sold', ebayHtml);
    if (ebayPrices.length !== 2 || ebayPrices[0] !== 250 || ebayPrices[1] !== 290) {
      throw new Error('Unexpected ebay prices: ' + JSON.stringify(ebayPrices));
    }
    const ebayItems = bg.extractEbayItemsFromHtml(ebayHtml);
    if (ebayItems.length !== 2) {
      throw new Error('Expected 2 ebay items, got ' + ebayItems.length);
    }
    if (ebayItems[0].title !== 'RetroWidget Pro' || ebayItems[0].price !== 250) {
      throw new Error('Unexpected ebay item[0]: ' + JSON.stringify(ebayItems[0]));
    }

    const ebayFewerKeywordsHtml = `
      <div class="s-item"><div class="s-item__title">RetroWidget Pro</div><span class="s-item__price">EUR 250,00</span></div>
      <div class="s-item"><div class="s-item__title">RetroWidget Pro Gerät</div><span class="s-item__price">290,00 €</span></div>
      <div class="srp-river-answer"><h3>Ergebnisse für weniger Suchbegriffe</h3></div>
      <div class="s-item"><div class="s-item__title">RetroWidget Zubehör</div><span class="s-item__price">50,00 €</span></div>
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
    if (bg.isEbayLoginRequired(ebayHtml, 'https://www.ebay.de/sch/i.html?_nkw=RetroWidget')) {
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
    global.browser = {
      runtime: {
        sendMessage: (msg, cb) => {
          if (msg.action === 'FETCH_DRAFT_IMAGES') {
            cb({
              ok: true,
              images: [
                { filename: 'lego_front.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' },
                { filename: 'lego_back.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' }
              ]
            });
          }
        }
      }
    };
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
    global.browser = {
      runtime: {
        sendMessage: (msg, cb) => {
          if (msg.action === 'FETCH_DRAFT_IMAGES') {
            cb({
              ok: true,
              images: [
                { filename: 'lego_front.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' },
                { filename: 'lego_back.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' }
              ]
            });
          }
        }
      }
    };
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


def test_extension_content_dom_autofill_and_security():
    node_script = """
    global.browser = {
      runtime: {
        sendMessage: (msg, cb) => {
          if (msg.action === 'FETCH_DRAFT_IMAGES') {
            cb({
              ok: true,
              images: [
                { filename: 'lego_front.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' },
                { filename: 'lego_back.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' }
              ]
            });
          }
        }
      }
    };
    const content = require('./extension/content.js');

    // 1. Verify setNativeValue event dispatching and tracking
    const eventsFired = [];
    const mockInput = {
      value: '',
      dispatchEvent: (evt) => { eventsFired.push(evt.type); }
    };
    content.setNativeValue(mockInput, 'Pro Modell 2026');
    if (mockInput.value !== 'Pro Modell 2026') {
      throw new Error('setNativeValue did not set string value');
    }
    if (!eventsFired.includes('input') || !eventsFired.includes('change')) {
      throw new Error('Required DOM events input/change not fired');
    }

    // 2. Verify setDescriptionValue iframe sanitization (prevent innerHTML injection)
    class MockNode {
      constructor(nodeType, nodeName, textContent = '') {
        this.nodeType = nodeType;
        this.nodeName = nodeName;
        this.textContent = textContent;
      }
    }
    class MockElement extends MockNode {
      constructor(nodeName) {
        super(1, nodeName);
        this.childNodes = [];
        this.events = [];
      }
      appendChild(child) { this.childNodes.push(child); }
      replaceChildren() { this.childNodes = []; }
      dispatchEvent(evt) { this.events.push(evt.type); }
    }

    const mockIframeBody = new MockElement('BODY');
    const mockIframeDoc = {
      querySelector: (sel) => mockIframeBody,
      createTextNode: (text) => new MockNode(3, '#text', text),
      createElement: (tag) => new MockElement(tag.toUpperCase())
    };

    const mockDocWithIframe = {
      querySelector: (sel) => null,
      querySelectorAll: (sel) => {
        if (sel.includes('iframe')) {
          return [{ contentDocument: mockIframeDoc }];
        }
        return [];
      }
    };

    const xssPayload = 'Line 1\\n<script>alert(1)<\\/script>\\n<img src=x onerror=alert(2)>';
    const iframeRes = content.setDescriptionValue(xssPayload, mockDocWithIframe);
    if (!iframeRes) throw new Error('setDescriptionValue failed on mock iframe');

    // Must create text nodes and BR elements, NEVER script/img element nodes
    if (mockIframeBody.childNodes.length !== 5) {
      throw new Error('Expected 5 nodes (3 text nodes, 2 BR), got: ' + mockIframeBody.childNodes.length);
    }
    for (let i = 0; i < mockIframeBody.childNodes.length; i++) {
      const node = mockIframeBody.childNodes[i];
      if (i % 2 === 0) {
        if (node.nodeType !== 3) {
          throw new Error('Node ' + i + ' should be text node, got type: ' + node.nodeType);
        }
      } else {
        if (node.nodeName !== 'BR') {
          throw new Error('Node ' + i + ' should be BR, got: ' + node.nodeName);
        }
      }
    }
    if (mockIframeBody.childNodes[2].textContent !== '<script>alert(1)<\\/script>') {
      throw new Error('Raw script tag must remain unexecuted textContent');
    }

    // 3. Verify fillRicardoPrices with auction and fixed prices
    const startInput = { value: '', dispatchEvent: () => {} };
    const buyNowInput = { value: '', dispatchEvent: () => {} };
    global.document = {
      getElementById: (id) => {
        if (id === 'SellingUI.start_price') return startInput;
        if (id === 'SellingUI.buy_now_price') return buyNowInput;
        return null;
      },
      querySelector: () => null,
      querySelectorAll: () => []
    };

    (async () => {
      await content.fillRicardoPrices({}, { startPrice: 19.95, buyNowPrice: 49.0 });
      if (startInput.value !== '19.95') {
        throw new Error('Expected startInput to be "19.95", got: ' + startInput.value);
      }
      if (buyNowInput.value !== '49') {
        throw new Error('Expected buyNowInput to be "49", got: ' + buyNowInput.value);
      }

      // 4. Verify host boundary checking against phishing/spoofing
      if (!content.isRicardo('www.ricardo.ch') || !content.isRicardo('seller.ricardo.ch')) {
        throw new Error('Valid ricardo subdomains rejected');
      }
      if (content.isRicardo('ricardo.ch.attacker.org') || content.isRicardo('fake-ricardo.ch')) {
        throw new Error('Deceptive ricardo domains accepted');
      }

      if (!content.isTutti('www.tutti.ch') || content.isTutti('tutti.ch.evil.com')) {
        throw new Error('Tutti domain validation failed');
      }

      if (!content.isEbayDE('www.ebay.de') || content.isEbayDE('ebay.de.attacker.com')) {
        throw new Error('eBay DE domain validation failed');
      }

      if (!content.isKleinanzeigen('www.kleinanzeigen.de') || content.isKleinanzeigen('kleinanzeigen.de.phishing.org')) {
        throw new Error('Kleinanzeigen domain validation failed');
      }
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"


def test_extension_unpaired_auth_handling():
    content_file = Path("extension/content.js")
    bg_file = Path("extension/background.js")
    content_text = content_file.read_text(encoding="utf-8")
    bg_text = bg_file.read_text(encoding="utf-8")

    assert "⚠️ Nicht gekoppelt: Einmalig 127.0.0.1:8000 im Browser öffnen" in content_text
    assert "unauthorized: isAuth" in bg_text

    node_script = """
    global.BACKEND_BASE = "http://127.0.0.1:8000";
    global.browser = {
      storage: {
        local: {
          get: () => Promise.resolve({})
        }
      },
      runtime: {
        onMessage: {
          addListener: (fn) => { global.__msgListener = fn; }
        }
      }
    };
    global.fetch = async (url) => {
      return {
        ok: false,
        status: 401,
        json: async () => ({ detail: "Unauthorized" })
      };
    };

    require('./extension/background.js');

    new Promise((resolve, reject) => {
      global.__msgListener({ action: "LIST_DRAFTS" }, {}, (res) => {
        if (!res) return reject(new Error("No response received"));
        if (res.ok) return reject(new Error("Expected ok: false on 401"));
        if (!res.unauthorized) return reject(new Error("Expected unauthorized: true on 401"));
        resolve();
      });
    }).catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Node auth handling test failed: {res.stderr}"


def test_content_handles_unauthorized_draft_list():
    node_script = """
    const mockSelect = { innerHTML: '', appendChild: (opt) => {} };
    global.document = {
      createElement: (tag) => ({ value: '', textContent: '' }),
      getElementById: (id) => {
        if (id === 'ai-ext-draft-select') return mockSelect;
        return null;
      }
    };

    // 1. Test unauthorized response
    global.browser = {
      runtime: {
        sendMessage: (msg, cb) => {
          if (msg.action === 'LIST_DRAFTS') {
            cb({ ok: false, unauthorized: true, error: 'HTTP 401' });
          }
        }
      }
    };

    const content = require('./extension/content.js');
    content.fetchDraftsList();

    if (!mockSelect.innerHTML.includes('Nicht gekoppelt')) {
      throw new Error('Expected draftSelect to contain actionable uncoupled hint, got: ' + mockSelect.innerHTML);
    }
    if (!mockSelect.innerHTML.includes('127.0.0.1:8000')) {
      throw new Error('Expected draftSelect to prompt 127.0.0.1:8000, got: ' + mockSelect.innerHTML);
    }

    // 2. Test successful response
    global.browser.runtime.sendMessage = (msg, cb) => {
      if (msg.action === 'LIST_DRAFTS') {
        cb({ ok: true, drafts: [{ id: 'd-1', identified_product: 'Test Item', status: 'ready' }] });
      }
    };
    content.fetchDraftsList();
    if (mockSelect.innerHTML.includes('Nicht gekoppelt')) {
      throw new Error('Unexpected uncoupled hint on successful response');
    }
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Content script auth UX test failed: {res.stderr}"


def test_ricardo_offer_type_and_shipping_preset():
    node_script = """
    const content = require('./extension/content.js');

    // 1. Ricardo offer_type mapping in getPlatformData
    const auctionDraft = {
      ricardo: { title: 'Item 1', offer_type: 'auction', start_price_chf: 1.0, buynow_price_chf: 20.0 }
    };
    const fixedDraft = {
      ricardo: { title: 'Item 2', offer_type: 'fixed_price', buynow_price_chf: 50.0 }
    };

    const d1 = content.getPlatformData(auctionDraft, 'ricardo');
    if (d1.priceType !== 'auction') throw new Error('Expected auction priceType, got: ' + d1.priceType);

    const d2 = content.getPlatformData(fixedDraft, 'ricardo');
    if (d2.priceType !== 'fixed_price') throw new Error('Expected fixed_price priceType, got: ' + d2.priceType);

    // 2. fillRicardoShipping pickup_allowed logic
    let clickedPickup = 0;
    const mockPickupSwitch = {
      checked: false,
      click: () => { clickedPickup++; mockPickupSwitch.checked = !mockPickupSwitch.checked; }
    };
    const mockShippingSwitch = {
      checked: true,
      click: () => {}
    };

    global.document = {
      querySelector: (sel) => {
        if (sel.includes('value="Pickup"')) return mockPickupSwitch;
        if (sel.includes('value="Shipping"')) return mockShippingSwitch;
        return null;
      },
      querySelectorAll: () => []
    };

    // When pickup_allowed is false, pickupSwitch should not be activated
    const noPickupDraft = {
      ricardo: { shipping_preset_id: 'b_post_2kg', pickup_allowed: false }
    };
    content.fillRicardoShipping(noPickupDraft).then(() => {
      if (mockPickupSwitch.checked) throw new Error('Pickup should not be checked when pickup_allowed is false');
    });
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Ricardo offer type / shipping test failed: {res.stderr}"


def test_price_token_overlap_matching_and_provenance():
    node_script = """
    const bg = require('./extension/background.js');

    // 1. Token overlap test
    const q = 'Bose QuietComfort 45';
    const cand1 = 'Bose QuietComfort 45 Wireless Noise Cancelling Kopfhörer';
    const cand2 = 'Bose Noise Cancelling 700 Kopfhörer';
    const cand3 = 'Logitech MX Master 3S';

    const s1 = bg.calculateTokenOverlap(q, cand1);
    const s2 = bg.calculateTokenOverlap(q, cand2);
    const s3 = bg.calculateTokenOverlap(q, cand3);

    if (s1 < 0.9) throw new Error('Expected s1 to be near 1.0, got: ' + s1);
    if (s2 >= s1) throw new Error('Expected cand1 to rank higher than cand2');
    if (s3 > 0.1) throw new Error('Expected cand3 to have near 0 overlap, got: ' + s3);

    // 2. selectBestMatchingItem
    const items = [
      { title: cand3, price: 99.0 },
      { title: cand2, price: 219.0 },
      { title: cand1, price: 189.0 }
    ];
    const best = bg.selectBestMatchingItem(items, q);
    if (!best || best.title !== cand1) {
      throw new Error('Expected best item to be cand1, got: ' + JSON.stringify(best));
    }

    // 3. computeSourceStats provenance metadata
    const stats = bg.computeSourceStats(
      { id: 'idealo', label: 'Idealo', currency: 'EUR' },
      [189.0],
      'https://www.idealo.de/test',
      'tab',
      0.94,
      { query: q, confidence: 0.95 }
    );
    if (!stats.captured_at) throw new Error('Missing captured_at timestamp in stats');
    if (stats.query !== q) throw new Error('Missing query in stats, got: ' + stats.query);
    if (stats.confidence !== 0.95) throw new Error('Missing confidence in stats, got: ' + stats.confidence);
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Token overlap / provenance test failed: {res.stderr}"


def test_scrape_all_price_sources_fault_tolerant():
    node_script = """
    const bg = require('./extension/background.js');

    // Mock scrapeSourceHybrid to succeed for ricardo and fail for ebay_de_sold
    const origScrapeSourceHybrid = bg.scrapeSourceHybrid;
    
    // We test scrapeAllPriceSources by filtering to two sources
    (async () => {
      // Temporarily override global or mock fetch if needed
      const res = await bg.scrapeAllPriceSources('Test Query', 0.94, ['ricardo', 'ebay_de_sold']);
      if (!res.ok) throw new Error('Expected res.ok to be true');
      if (!res.sources) throw new Error('Missing res.sources');
      if (!res.sources.ricardo) throw new Error('Missing ricardo in sources');
      if (!res.sources.ebay_de_sold) throw new Error('Missing ebay_de_sold in sources');
      // Even if network or tab scrape throws/times out in mock/node environment, neither causes total rejection
      console.log('Scrape result sources:', Object.keys(res.sources));
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"Fault-tolerant scrape test failed: {res.stderr}"




def test_extension_ebay_de_autofill_and_prelist_via_node():
    node_script = """
    global.browser = {
      runtime: {
        sendMessage: (msg, cb) => {
          if (msg.action === 'FETCH_DRAFT_IMAGES') {
            cb({
              ok: true,
              images: [
                { filename: 'lego_front.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' },
                { filename: 'lego_back.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' }
              ]
            });
          }
        }
      }
    };
    const content = require('./extension/content.js');

    // 1. Verify handleEbayPrelistStep1 (Step 1 keyword search)
    let nextBtnClicked = false;
    const mockPrelistDoc = {
      querySelector: (sel) => {
        if (sel.includes('search-textbox') || sel.includes('simplified-keyword')) {
          return {
            value: '',
            dispatchEvent: () => {},
          };
        }
        if (sel.includes('sell-search-simplified__next-action')) {
          return {
            disabled: true,
            removeAttribute: (attr) => {},
            click: () => { nextBtnClicked = true; }
          };
        }
        return null;
      }
    };
    (async () => {
      const resPrelist = await content.handleEbayPrelistStep1(
        { identified_product: 'LEGO Harry Potter Schloss Hogwarts' },
        { title: 'LEGO Harry Potter 76435' },
        mockPrelistDoc
      );
      if (!resPrelist || !nextBtnClicked) {
        throw new Error('handleEbayPrelistStep1 failed to fill keyword or click next button');
      }

      // 2. Verify handleEbayConditionDialog
      let continueBtnClicked = false;
      const mockRadios = [
        { name: 'condition', value: '1000', checked: false, dispatchEvent: () => {} },
        { name: 'condition', value: '1500', checked: false, dispatchEvent: () => {} },
        { name: 'condition', value: '3000', checked: false, dispatchEvent: () => {} },
      ];
      const mockConditionDoc = {
        querySelector: (sel) => {
          if (sel.includes('value="3000"')) return mockRadios[2];
          if (sel.includes('value="1000"')) return mockRadios[0];
          if (sel.includes('value="1500"')) return mockRadios[1];
          if (sel.includes('condition-dialog-radix__continue-btn')) {
            return {
              disabled: true,
              removeAttribute: () => {},
              click: () => { continueBtnClicked = true; }
            };
          }
          return null;
        }
      };
      const resCond = await content.handleEbayConditionDialog('gebraucht', mockConditionDoc);
      if (!resCond || !mockRadios[2].checked || !continueBtnClicked) {
        throw new Error('handleEbayConditionDialog failed to select condition or click continue');
      }

      // 3. Verify fillEbayDEPricesAndFormat
      let formatVal = '';
      let startPriceVal = '';
      let buyNowVal = '';
      const mockPriceDoc = {
        querySelector: (sel) => {
          if (sel.includes('format')) {
            return {
              value: '',
              dispatchEvent: () => {},
              parentElement: { querySelector: () => ({ textContent: '' }) }
            };
          }
          if (sel.includes('startPrice')) {
            return {
              value: '',
              dispatchEvent: () => {}
            };
          }
          if (sel.includes('price')) {
            return {
              value: '',
              dispatchEvent: () => {}
            };
          }
          return null;
        }
      };
      await content.fillEbayDEPricesAndFormat(
        {},
        { priceType: 'auction', startPrice: 15.50, buyNowPrice: 45.00 },
        mockPriceDoc
      );

      // 4. Verify fillEbayDEShipping
      let clickedButtonText = '';
      const mockShippingButtons = [
        { textContent: 'Versand und Abholung', getAttribute: () => null, click: () => { clickedButtonText = 'Versand und Abholung'; } },
        { textContent: 'Nur Abholung', getAttribute: () => null, click: () => { clickedButtonText = 'Nur Abholung'; } }
      ];
      const mockShippingDoc = {
        querySelectorAll: (sel) => mockShippingButtons
      };
      await content.fillEbayDEShipping(
        { ebay_de: { shipping_preset_id: 'pickup_only_de' } },
        mockShippingDoc
      );
      if (clickedButtonText !== 'Nur Abholung') {
        throw new Error('fillEbayDEShipping failed for pickup_only_de: got ' + clickedButtonText);
      }
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"eBay DE extension autofill test failed: {res.stderr}"


def test_extension_ebay_de_3step_workflow_via_node():
    node_script = """
    global.browser = {
      runtime: {
        sendMessage: (msg, cb) => {
          if (msg.action === 'FETCH_DRAFT_IMAGES') {
            cb({
              ok: true,
              images: [
                { filename: 'lego_front.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' },
                { filename: 'lego_back.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' }
              ]
            });
          }
        }
      }
    };
    const content = require('./extension/content.js');

    (async () => {
      // 1. Test selectEbayProductMatch with model number scoring
      let clickedProductIdx = -1;
      const mockProductButtons = [
        { textContent: 'LEGO Harry Potter: Schloss Hogwarts: die Große Halle (76435)', click: () => { clickedProductIdx = 0; } },
        { textContent: 'LEGO Harry Potter: Die große Halle von Hogwarts (75954)', click: () => { clickedProductIdx = 1; } },
        { textContent: 'LEGO Harry Potter: Schloss Hogwarts (71043)', click: () => { clickedProductIdx = 2; } },
      ];
      const mockCatalogDoc = {
        querySelectorAll: (sel) => {
          if (sel.includes('product-button')) return mockProductButtons;
          return [];
        }
      };

      const matchRes = content.selectEbayProductMatch(
        { identified_product: 'LEGO Harry Potter Schloss Hogwarts 76435' },
        { title: 'LEGO Harry Potter 76435' },
        mockCatalogDoc
      );
      if (!matchRes || !matchRes.isMatch || matchRes.button !== mockProductButtons[0]) {
        throw new Error('selectEbayProductMatch failed to match exact model 76435: ' + JSON.stringify(matchRes));
      }

      // 2. Test executeEbayStep1 (Keyword -> Catalog -> Condition Dialog)
      let prelistKeyword = '';
      let prelistNextClicked = false;
      let conditionRadioChecked = false;
      let conditionContinueClicked = false;

      const mockStep1Doc = {
        querySelector: (sel) => {
          if (sel.includes('search-textbox') || sel.includes('simplified-keyword')) {
            return {
              value: '',
              dispatchEvent: () => {},
            };
          }
          if (sel.includes('sell-search-simplified__next-action')) {
            return {
              disabled: true,
              removeAttribute: () => {},
              click: () => { prelistNextClicked = true; }
            };
          }
          if (sel.includes('value="3000"')) {
            return {
              name: 'condition',
              value: '3000',
              checked: false,
              click: () => { conditionRadioChecked = true; },
              dispatchEvent: () => {}
            };
          }
          if (sel.includes('condition-dialog-radix__continue-btn')) {
            return {
              disabled: true,
              removeAttribute: () => {},
              click: () => { conditionContinueClicked = true; }
            };
          }
          if (sel.includes('prelist-radix__next-action')) {
            return {
              click: () => {}
            };
          }
          return null;
        },
        querySelectorAll: (sel) => {
          if (sel.includes('product-button')) return mockProductButtons;
          return [];
        }
      };

      const step1Draft = {
        identified_product: 'LEGO Harry Potter Schloss Hogwarts 76435',
        ebay_de: {
          title: 'LEGO Harry Potter Schloss Hogwarts 76435 OVP',
          condition: 'gebraucht'
        }
      };

      const resStep1 = await content.executeEbayStep1(step1Draft, mockStep1Doc);
      if (!resStep1 || !resStep1.ok) {
        throw new Error('executeEbayStep1 failed: ' + JSON.stringify(resStep1));
      }
      if (!prelistNextClicked) {
        throw new Error('executeEbayStep1 did not click next after keyword search');
      }
      if (clickedProductIdx !== 0) {
        throw new Error('executeEbayStep1 did not click matching product button: got idx ' + clickedProductIdx);
      }
      if (!conditionRadioChecked || !conditionContinueClicked) {
        throw new Error('executeEbayStep1 did not select condition radio or continue button');
      }

      // 3. Test executeEbayStep2 with Standardbild preservation
      let injectedFiles = null;
      const mockFileInput = {
        id: 'fehelix-uploader',
        type: 'file',
        files: [],
        dispatchEvent: () => {},
        closest: () => null,
        parentElement: { dispatchEvent: () => {} }
      };

      const mockStandardbildBtn = {
        tagName: 'BUTTON',
        getAttribute: (attr) => attr === 'style' ? "background-image:url('https://i.ebayimg.com/images/g/XCEAAOSwtdtmcaNG/s-l1600.jpg')" : null,
        style: { backgroundImage: "url('https://i.ebayimg.com/images/g/XCEAAOSwtdtmcaNG/s-l1600.jpg')" },
        closest: () => null,
        querySelector: () => null
      };

      const mockStep2Doc = {
        querySelector: (sel) => {
          if (sel.includes('fehelix-uploader') || sel.includes('type="file"')) {
            return mockFileInput;
          }
          return null;
        },
        querySelectorAll: (sel) => {
          if (sel.includes('Standardbild') || sel.includes('pictureStock') || sel.includes('uploader-thumbnails-ux__image')) {
            return [mockStandardbildBtn];
          }
          return [];
        }
      };

      // Test extractEbayStockImageUrl
      const extractedStockUrl = content.extractEbayStockImageUrl(mockStep2Doc);
      if (extractedStockUrl !== 'https://i.ebayimg.com/images/g/XCEAAOSwtdtmcaNG/s-l1600.jpg') {
        throw new Error('extractEbayStockImageUrl failed: got ' + extractedStockUrl);
      }

      global.browser = {
        runtime: {
          sendMessage: (msg, cb) => {
            if (msg.action === 'FETCH_DRAFT_IMAGES') {
              cb({
                ok: true,
                images: [
                  { filename: 'lego_front.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' },
                  { filename: 'lego_back.jpg', mimeType: 'image/jpeg', dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg==' }
                ]
              });
            } else if (msg.action === 'FETCH_EXTERNAL_IMAGE') {
              cb({
                ok: true,
                filename: 'standardbild_katalog.jpg',
                mimeType: 'image/jpeg',
                dataUrl: 'data:image/jpeg;base64,/9j/4AAQSkZJRg=='
              });
            }
          }
        }
      };

      const resStep2 = await content.executeEbayStep2({ id: 'draft-123' }, mockStep2Doc);
      if (!resStep2 || !resStep2.ok || resStep2.count !== 3 || !resStep2.hasStockImage) {
        throw new Error('executeEbayStep2 failed to preserve Standardbild: ' + JSON.stringify(resStep2));
      }
      if (!resStep2.message.includes('Standardbild + 2 eigene Bilder')) {
        throw new Error('Unexpected executeEbayStep2 message: ' + resStep2.message);
      }

      // 4. Test executeEbayStep3 (Title, Description, Format & Prices, Shipping)
      let titleSet = '';
      let formatSet = '';
      let startPriceSet = '';
      let buynowPriceSet = '';
      let shippingSet = '';
      let descSet = '';

      const mockRteIframe = {
        id: 'se-rte-frame__summary',
        contentDocument: {
          querySelector: () => ({
            replaceChildren: () => {},
            appendChild: (child) => { descSet += (child.textContent || ''); },
            dispatchEvent: () => {}
          }),
          createTextNode: (t) => ({ textContent: t }),
          createElement: () => ({ textContent: " " })
        }
      };

      const mockShippingBtns = [
        { textContent: 'Versand und Abholung', getAttribute: () => null, click: () => { shippingSet = 'versand_und_abholung'; } }
      ];

      const mockStep3Doc = {
        querySelector: (sel) => {
          if (sel.includes('input[name="title"]')) {
            return {
              value: '',
              dispatchEvent: () => {}
            };
          }
          if (sel.includes('format')) {
            return {
              value: '',
              dispatchEvent: () => {},
              parentElement: { querySelector: () => ({ textContent: '' }) }
            };
          }
          if (sel.includes('startPrice')) {
            return {
              value: '',
              dispatchEvent: () => {}
            };
          }
          if (sel.includes('price')) {
            return {
              value: '',
              dispatchEvent: () => {}
            };
          }
          return null;
        },
        querySelectorAll: (sel) => {
          if (sel.includes('iframe#se-rte-frame__summary')) return [mockRteIframe];
          if (sel.includes('.summary__shipping button')) return mockShippingBtns;
          return [];
        }
      };

      const resStep3 = await content.executeEbayStep3(
        {
          ebay_de: {
            title: 'LEGO Harry Potter 76435 Neu OVP',
            description: 'Tolles Set in Originalverpackung.',
            offer_type: 'auction',
            start_price_eur: 49.99,
            buynow_price_eur: 119.00,
            shipping_preset_id: 'dhl_2kg'
          }
        },
        mockStep3Doc
      );

      if (!resStep3 || !resStep3.ok) {
        throw new Error('executeEbayStep3 failed: ' + JSON.stringify(resStep3));
      }
      if (shippingSet !== 'versand_und_abholung') {
        throw new Error('executeEbayStep3 failed to configure shipping: got ' + shippingSet);
      }
      if (!descSet.includes('Tolles Set in Originalverpackung')) {
        throw new Error('executeEbayStep3 failed to inject description into RTE iframe: got ' + descSet);
      }

      // 5. Test Smart Panel UI buttons: 3 steps on eBay DE vs 2 steps on Tutti/Ricardo
      let appendedPanels = [];
      global.document = {
        getElementById: () => null,
        createElement: (tag) => ({ id: '', className: '', innerHTML: '' }),
        body: {
          appendChild: (el) => { appendedPanels.push(el); }
        }
      };

      // Test eBay DE
      global.location = { hostname: 'www.ebay.de' };
      content.createSmartPanel();
      const ebayPanel = appendedPanels[appendedPanels.length - 1];
      if (!ebayPanel || !ebayPanel.innerHTML.includes('ai-ext-step1-btn') || !ebayPanel.innerHTML.includes('ai-ext-step2-btn') || !ebayPanel.innerHTML.includes('ai-ext-step3-btn')) {
        throw new Error('Expected 3 buttons for eBay DE Smart Panel, got: ' + ebayPanel?.innerHTML);
      }

      // Test Ricardo
      global.location = { hostname: 'www.ricardo.ch' };
      content.createSmartPanel();
      const ricardoPanel = appendedPanels[appendedPanels.length - 1];
      if (!ricardoPanel || !ricardoPanel.innerHTML.includes('ai-ext-step1-btn') || !ricardoPanel.innerHTML.includes('ai-ext-step2-btn') || ricardoPanel.innerHTML.includes('ai-ext-step3-btn')) {
        throw new Error('Expected 2 buttons (and no step3) for Ricardo Smart Panel, got: ' + ricardoPanel?.innerHTML);
      }

      // 6. Test sessionStorage automation across page navigation
      const sessionStore = {};
      global.sessionStorage = {
        getItem: (k) => sessionStore[k] || null,
        setItem: (k, v) => { sessionStore[k] = String(v); },
        removeItem: (k) => { delete sessionStore[k]; }
      };

      global.sessionStorage.setItem(content.EBAY_AUTO_KEY, JSON.stringify({
        draftId: 'draft-auto',
        startedAt: Date.now()
      }));

      // When executeEbayStep1 finishes with condition selected, it clears the auto key
      await content.executeEbayStep1(step1Draft, mockStep1Doc);
      if (global.sessionStorage.getItem(content.EBAY_AUTO_KEY)) {
        throw new Error('Expected EBAY_AUTO_KEY to be cleared after step 1 completes');
      }
    })().catch(err => {
      console.error(err);
      process.exit(1);
    });
    """
    res = subprocess.run(["node", "-e", node_script], check=False, capture_output=True, text=True)
    assert res.returncode == 0, f"eBay DE 3-step workflow test failed: {res.stderr}"






