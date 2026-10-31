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
    assert "background" in manifest
    assert "scripts" in manifest["background"]
    assert "background.js" in manifest["background"]["scripts"]
    
    host_perms = manifest.get("host_permissions", [])
    assert any("127.0.0.1:8000" in p for p in host_perms)
    assert any("ricardo.ch" in p for p in host_perms)
    assert any("tutti.ch" in p for p in host_perms)
    
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
