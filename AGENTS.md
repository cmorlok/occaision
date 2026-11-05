# OccAIsion Development Guidelines

Context: [`DEVELOPMENT.md`](DEVELOPMENT.md) (setup, builds, testing), [`REQUIREMENTS.md`](REQUIREMENTS.md) (features, user flows), [`IMPLEMENTATION_PLAN.md`](IMPLEMENTATION_PLAN.md) (data models, scraping schema).

## Project Identity & Neutral Branding (Strict Invariant)

- Canonical project name: **`OccAIsion`** (slug: `occaision`, artifact: `dist/occaision.zip`, container: `occaision`).
- Maintain neutral user-facing branding: exclude third-party marketplace names (Tutti, Ricardo, eBay, Kleinanzeigen, Idealo, Toppreise, Digitec, Galaxus) from UI text, manifest metadata, package names, and build artifacts. Confine them strictly to internal scrapers, URL routes, and DOM selectors.

## Architecture & Extension Boundaries

- Route all content-script backend requests through `extension/background.js` message proxy (`browser.runtime.sendMessage`). Host page CSP/CORS blocks direct `fetch` to `127.0.0.1:8000` from `content.js`.
- Preserve Node.js test compatibility: maintain the `module.exports` conditional export block at the bottom of `extension/background.js` for `tests/test_phase4_extension.py`.

## Data Sanitization & Localization Invariants

- Strip EXIF/GPS metadata on image upload. Clamp AI-bound images to <= 1024x1024 px (`create_ai_input_variant`).
- Swiss vs German orthography: Swiss fields (`tutti_*`, `ricardo_*`, general) must replace `ß` with `ss` and use `SWISS_LEGAL_DISCLAIMER`. German fields (`ebay_de_*`, `kleinanzeigen_*`) retain `ß` and use `GERMAN_LEGAL_DISCLAIMER`.

## Testing & Integrity Invariants

- Isolate all tests with `tmp_path` or `monkeypatch`. Never write to `./data/` during tests or invoke live external APIs.
- Keep test integrity intact: fix production code rather than weakening assertions, relaxing bounds, or skipping failed tests.
