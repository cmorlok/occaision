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
    assert manifest.get("name") == "Seller Assistant"
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

    matches = manifest["content_scripts"][0].get("matches", [])
    assert any("127.0.0.1" in m for m in matches)
    assert any("localhost" in m for m in matches)
    assert any("ricardo.ch" in m for m in matches)
    assert any("tutti.ch" in m for m in matches)
    assert any("ebay.de" in m for m in matches)
    assert any("kleinanzeigen.de" in m for m in matches)
    
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

    # 6. 6-source hybrid price scraper & dashboard bridge
    assert "SCRAPE_ALL_PRICE_SOURCES" in bg_js_code
    assert "scrapeSourceHybrid" in bg_js_code
    assert "LH_ItemCondition=3000" in bg_js_code
    assert "isLocalDashboard" in content_js_code
    assert "SELLER_ASSISTANT_SCRAPE_PRICES" in content_js_code


def test_extension_price_parser_and_stats_via_node():
    node_script = """
    const bg = require('./extension/background.js');
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
    """
    res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True)
    assert res.returncode == 0, f"Node test failed: {res.stderr}"

