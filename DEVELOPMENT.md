# Entwicklungs- & Build-Dokumentation (`DEVELOPMENT.md`)

Dieses Dokument beschreibt die lokale Entwicklungsumgebung, Testausführung und Build-Prozesse für **OccAIsion**.

---

## 1. Lokale Entwicklungsumgebung (ohne Docker)

### Voraussetzungen
* Python 3.11+
* Node.js 18+ (wird für Extension-Syntax- und DOM-Tests benötigt)
* `git`

### Schritt-für-Schritt-Setup

1. **Repository klonen und ins Verzeichnis wechseln:**
   ```bash
   git clone <repo-url>
   cd seller
   ```

2. **Virtuelle Python-Umgebung erstellen & aktivieren:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Abhängigkeiten installieren:**
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Umgebungsvariablen konfigurieren:**
   Kopiere die Vorlage `.env.example` nach `.env`:
   ```bash
   cp .env.example .env
   ```
   Trage in `.env` deinen `GEMINI_API_KEY` ein.

5. **Lokalen Backend-Server starten:**
   ```bash
   uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
   ```
   * Dashboard im Browser: [http://127.0.0.1:8000](http://127.0.0.1:8000)
   * API-Dokumentation (Swagger UI): [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 2. Arbeiten im VS Code Dev Container

Das Projekt enthält eine vollständige Dev-Container-Konfiguration (`.devcontainer/`):
1. Öffne das Projekt in VS Code.
2. Drücke `F1` (oder `Ctrl+Shift+P` / `Cmd+Shift+P`) und wähle **Dev Containers: Reopen in Container**.
3. Der Container wird automatisch gebaut; Python-Umgebung, Node.js und Tools stehen sofort bereit.
4. Host-Wrapper für agy:
   ```bash
   ./scripts/agy-container.sh
   ```

---

## 3. Test-Suite ausführen (TDD & Qualitätssicherung)

Das Projekt folgt einem strikten **Test-Driven Development (TDD)**-Ansatz. Die Testsuite umfasst 22 Unit- und Integrationstests (Image-Processing, Gemini AI Mocking, REST-Endpoints, MV3 Extension Node-DOM-Tests).

```bash
# Gesamte Testsuite ausführen
pytest -v

# Mit detaillierter Ausgabe und stdout
pytest -vv -s

# Nur Extension-Tests ausführen
pytest -v tests/test_phase4_extension.py
```

Vor jedem Commit muss `pytest -v` mit **0 Fehlern** durchlaufen.

---

## 4. Firefox-Extension bauen

Das Build-Skript bündelt `manifest.json`, `background.js`, `content.js` und `panel.css` in ein distributionsfertiges ZIP-Archiv:

```bash
bash scripts/build_extension.sh
```

* **Output:** `dist/occaision.zip`
* **Test in Firefox:**
  1. Öffne `about:debugging#/runtime/this-firefox`
  2. Klicke auf **"Temporäres Add-on laden..."**
  3. Wähle entweder `extension/manifest.json` (für Live-Reload bei Code-Änderungen) oder `dist/occaision.zip`.

---

## 5. Docker Image bauen

Um ein produktionsreifes Docker-Image lokal auf dem Host zu bauen:

```bash
# Image 'occaision:latest' bauen
bash scripts/build_docker.sh

# Oder mit spezifischem Tag:
bash scripts/build_docker.sh v1.0.0
```

---

## 6. GitHub Actions CI/CD & Release-Pipeline

Im Verzeichnis `.github/workflows/` sind zwei Pipelines eingerichtet:

### 1. `ci.yml` (Continuous Integration)
* **Trigger:** Jeder Pull Request auf den `main`-Branch.
* **Ablauf:** Führt `pytest -v` aus, verifiziert das Packaging der Firefox-Extension (`scripts/build_extension.sh`) und baut das Dockerfile zur Syntax- und Layer-Prüfung.

### 2. `release.yml` (Automated Build & GitHub Release)
* **Trigger:** 
  * Push eines Git-Tags nach dem Schema `v*` (z. B. `git tag v1.0.0 && git push origin v1.0.0`)
  * Manuell über die GitHub Actions Benutzeroberfläche (*"Run workflow"*).
* **Ablauf:**
  1. Führt alle 22 Tests aus.
  2. Baut die Firefox-Extension als `dist/occaision.zip`.
  3. Baut das Docker-Image und pusht es zur GitHub Container Registry (`ghcr.io/<owner>/occaision:<tag>`).
  4. Exportiert ein eigenständiges Offline-Image-Archiv `dist/occaision-docker.tar.gz`.
  5. Erstellt automatisch ein offizielles **GitHub Release** mit Release Notes und hängt `dist/occaision.zip` sowie `dist/occaision-docker.tar.gz` als Assets zum Download an.

---

## 7. Projektstruktur

```
├── backend/
│   ├── main.py              # FastAPI-Server, REST-API & Statik-Mount
│   ├── config.py            # Pydantic Settings & Logging-Setup
│   ├── models.py            # Pydantic Datenmodelle (Draft, Pricing, Shipping)
│   ├── storage.py           # JSON-basierte Entwurfs- & Bildpersistenz
│   └── services/
│       ├── ai_service.py    # Google Gemini Multimodal-Analyse & Safeguards
│       ├── image_service.py # EXIF-Stripping, Downscaling & Rembg-Pipeline
│       └── ebay_service.py  # Backend-Fallback-Scraper für eBay DE Sold
├── frontend/
│   ├── index.html           # Single-Page Web-Dashboard UI
│   ├── app.js               # Frontend-State-Management & REST-Client
│   └── styles.css           # Modernes Responsive Styling
├── extension/
│   ├── manifest.json        # Firefox Manifest V3 Konfiguration
│   ├── background.js        # Service Worker: Hybrid-Preis-Scraper & CORS-Proxy
│   ├── content.js           # Smart-Panel UI & 1-Klick-Autofill für Verkaufsplattformen
│   └── panel.css            # Styling für das injizierte Smart-Panel
├── tests/                   # 22 automatisierte Pytest- & Node-Tests
├── scripts/                 # Build- & Dev-Container-Hilfsskripte
├── Dockerfile               # Multi-Stage Produktions-Dockerfile
├── docker-compose.yml       # Docker Compose Setup
└── data/                    # Persistente Laufzeitdaten (Entwürfe & Bilder)
```
