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
   cd occaision
   ```

2. **Virtuelle Python-Umgebung erstellen & aktivieren:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Abhängigkeiten installieren:**
   ```bash
   pip install --upgrade pip
   # Für reguläre Ausführung:
   pip install -r requirements.txt

   # Für Entwicklung & Linting (inkl. ruff):
   pip install -r requirements-dev.txt
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

## 3. Test-Suite & Linting ausführen (TDD & Qualitätssicherung)

Das Projekt folgt einem strikten **Test-Driven Development (TDD)**-Ansatz. Die automatisierte Testsuite deckt 5 Bereiche ab:
* Bildverarbeitung & EXIF-Sanitization (`tests/test_phase1_image_and_storage.py`)
* Gemini AI Mocking, Safeguards & Preis-Parsing (`tests/test_phase2_pricing_and_ai.py`)
* FastAPI REST-Endpoints, Static Mount & Settings (`tests/test_phase3_api_and_ui.py`)
* Firefox MV3 Extension Syntax, DOM-Autofill & Scraper (`tests/test_phase4_extension.py`)
* Security Hardening, Token-Auth & Concurrency Revisions (`tests/test_hardening_security.py`)

### Schnellstart via Makefile:
```bash
# Gesamte Testsuite ausführen (nutzt automatisch .venv oder System-pytest)
make test

# Linter & JavaScript-Syntaxprüfung ausführen
make lint

# Firefox-Extension bauen & verifizieren
make test-extension
```

### Manuelle Ausführung:
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

## 4. Sicherheits- & Concurrency-Architektur

OccAIsion implementiert mehrschichtige Sicherheitsvorkehrungen:
1. **Loopback-Authentifizierung & CORS:**
   * Backend bindet in `docker-compose.yml` ausschließlich an `127.0.0.1:8000`.
   * Wildcard-CORS ist entfernt; nur Loopback (`127.0.0.1`, `localhost`) und WebExtensions (`moz-extension://`) sind autorisiert.
   * Beim Start generiert das Backend ein Pairing-Token in `data/auth_token.txt`.
   * Das Dashboard setzt automatisch ein `SameSite=Strict` Session-Cookie bei Zugriff via Loopback.
   * Die Firefox-Extension empfängt das Pairing-Token beim Aufruf des Dashboards und nutzt es für alle Hintergrund-API-Aufrufe (`Authorization: Bearer <token>`).
2. **XSS-Schutz & Content Security Policy (CSP):**
   * Alle dynamischen DOM-Elemente im Dashboard und der Extension nutzen `createElement()`, `textContent` und `replaceChildren()` statt unsicherem `innerHTML`.
   * Das Dashboard liefert einen restriktiven `Content-Security-Policy`-Header aus.
3. **Optimistische Concurrency & Datensicherheit:**
   * Jeder Entwurf besitzt ein monotones `revision`-Feld.
   * Gleichzeitige oder veraltete Schreibzugriffe werden mit `409 Conflict` abgewiesen (`RevisionConflictError`).
   * `/analyze` führt die KI-Generierung aus, ohne den Entwurf im Speicher zu blockieren, und mergt die Ergebnisse auf den aktuellen Live-Zustand. Gelöschte Entwürfe werden nicht wiederbelebt (`404 Not Found`).
   * Bei beschädigtem JSON in `drafts.json` wird automatisch ein Backup (`drafts.json.corrupt.<timestamp>`) angelegt, anstatt die Datei zu leeren (`StorageCorruptedError`).
4. **Dauerhafte Konfiguration:**
   * Dashboard-Einstellungen werden in `data/config.json` innerhalb des gemounteten Datenvolumens persistiert.
   * Rangfolge: Umgebungsvariablen > `data/config.json` > Standardwerte.
   * `GET /api/config` ist rein lesend und seiteneffektfrei.

---

## 5. Firefox-Extension bauen

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

## 6. Docker Image bauen

Um ein produktionsreifes Docker-Image lokal auf dem Host zu bauen:

```bash
# Image 'occaision:latest' bauen
bash scripts/build_docker.sh

# Oder mit spezifischem Tag:
bash scripts/build_docker.sh v1.0.0
```

---

## 7. GitHub Actions CI/CD & Release-Pipeline

Im Verzeichnis `.github/workflows/` sind zwei Pipelines eingerichtet:

### 1. `ci.yml` (Continuous Integration)
* **Trigger:** Jeder Push oder Pull Request auf den `main`-Branch.
* **Ablauf:** Führt `make lint` und `pytest -v` aus, verifiziert das Packaging der Firefox-Extension (`scripts/build_extension.sh`) und baut das Dockerfile zur Syntax- und Layer-Prüfung.

### 2. `release.yml` (Automated Build & GitHub Release)
* **Trigger:** 
  * Push eines Git-Tags nach dem Schema `v*` (z. B. `git tag v1.0.0 && git push origin v1.0.0`)
  * Manuell über die GitHub Actions Benutzeroberfläche (*"Run workflow"*).
* **Ablauf:**
  1. Führt `make lint` und die gesamte Pytest-Testsuite aus.
  2. Baut die Firefox-Extension als `dist/occaision.zip`.
  3. Baut das Docker-Image und pusht es zur GitHub Container Registry (`ghcr.io/<owner>/occaision:<tag>`).
  4. Exportiert ein eigenständiges Offline-Image-Archiv `dist/occaision-docker.tar.gz`.
  5. Erstellt automatisch ein offizielles **GitHub Release** mit Release Notes und hängt `dist/occaision.zip` sowie `dist/occaision-docker.tar.gz` als Assets zum Download an.

---

## 8. Projektstruktur

```
├── backend/
│   ├── main.py              # FastAPI-Server, REST-API & Statik-Mount
│   ├── config.py            # Pydantic Settings & Logging-Setup
│   ├── models.py            # Pydantic Datenmodelle (Draft, Pricing, Shipping)
│   ├── storage.py           # JSON-basierte Entwurfs- & Bildpersistenz mit Revisionssicherung
│   └── services/
│       ├── ai_service.py    # Google Gemini Multimodal-Analyse & Safeguards
│       └── image_service.py # EXIF-Stripping, Downscaling & Rembg-Pipeline
├── frontend/
│   ├── index.html           # Single-Page Web-Dashboard UI
│   ├── app.js               # Frontend-State-Management & REST-Client
│   └── styles.css           # Modernes Responsive Styling
├── extension/
│   ├── manifest.json        # Firefox Manifest V3 Konfiguration
│   ├── background.js        # Service Worker: Hybrid-Preis-Scraper & CORS-Proxy
│   ├── content.js           # Smart-Panel UI & 1-Klick-Autofill für Verkaufsplattformen
│   └── panel.css            # Styling für das injizierte Smart-Panel
├── tests/                   # Automatisierte Pytest-, Node- & Security-Tests
├── scripts/                 # Build- & Dev-Container-Hilfsskripte
├── Dockerfile               # Multi-Stage Produktions-Dockerfile
├── docker-compose.yml       # Docker Compose Setup
└── data/                    # Persistente Laufzeitdaten (Entwürfe & Bilder)
```
