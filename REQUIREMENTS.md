# Anforderungsdokument (Requirements Document)
## KI-gestützter Inserate-Generator für Tutti.ch & Ricardo.ch

* **Projekt:** Tutti & Ricardo Listing Assistant
* **Einsatzbereich:** Persönlicher Gebrauch (Single-User, lokaler Desktop-Betrieb, kein externes Deployment nötig)
* **Status:** Geschärft & Freigegeben
* **Datum:** 2026-10-31

---

## 1. Zielsetzung & Problemstellung

Beim regelmässigen Einstellen von Gebrauchtartikeln auf Schweizer Plattformen (**Tutti.ch** und **Ricardo.ch**) entstehen erhebliche Reibungspunkte:
* Unterschiedliche Plattformanforderungen (Ricardo mit striktem 60-Zeichen-Titel, Auktion vs. Sofortkauf, mehrstufiger Formular-Wizard; Tutti als klassische Kleinanzeige).
* Mühsames manuelles Copy-Pasten von Texten, Preisen und Auswählen von Dropdowns.
* Suboptimale Smartphone-Fotos (schlechte Ausleuchtung, unruhige Hintergründe, inkompatible Formate wie HEIC, verräterische EXIF/GPS-Metadaten).
* Schwierige Preisfindung: Wunschpreise auf Tutti/Ricardo reflektieren oft nicht den tatsächlichen Marktwert, und ein blinder Aufschlag auf deutsche Gebrauchtpreise ignoriert das oft tiefere Schweizer Neupreis-Niveau (z.B. bei Elektronik).

**Lösung:** Eine lokale Hybrid-Lösung aus einem **FastAPI/Python-Backend mit Web-Dashboard** (für Desktop-Upload, persistente Entwurfs-Verwaltung, Bildoptimierung, hybride Preisfindung und Textgenerierung) und einer **Firefox-Browsererweiterung (Manifest V3)** mit Smart-Panel zum schrittweisen Befüllen der Inserate-Formulare (inkl. Bild-Upload und 1-Klick-Copy-Fallbacks).

---

## 2. Systemarchitektur & Komponenten

```mermaid
flowchart TD
    User["Benutzer (Desktop)"] -->|Bilder & Notizen| Dashboard["Lokales Web-Dashboard (FastAPI + HTML/JS)"]
    
    subgraph Local_Backend ["Lokales Backend (127.0.0.1:8000)"]
        Dashboard --> ImgProc["Bild-Pipeline (Pillow/HEIF, EXIF-Strip, Auto-Enhance, opt. rembg/Blur)"]
        Dashboard --> DraftStore["Persistente Entwurfs-Verwaltung (Lokale JSON/SQLite + Bild-Ordner)"]
        Dashboard --> PriceEngine["Hybride Preis-Engine"]
        PriceEngine --> EbayParser["Direkter eBay-DE Sold-Parser (LH_Sold=1&LH_Complete=1)"]
        PriceEngine --> AI_Engine["Gemini API (konfigurierbar via .env, z.B. gemini-2.5-flash / 2.0-flash)"]
        AI_Engine --> Grounding["Google Search Grounding (CH-Neupreis via Digitec/Toppreise & Marktdaten)"]
    end

    subgraph Browser ["Firefox Browser"]
        BgScript["Extension Background Worker (umgeht CORS/CSP)"]
        ContentScript["Smart-Panel Content Script (tutti.ch / ricardo.ch)"]
        BgScript <-->|REST API (Entwürfe & Bilder)| DraftStore
        ContentScript <-->|browser.runtime.sendMessage| BgScript
        ContentScript -->|Schrittweise DOM-Injektion & File-Upload| PlatformForms["Tutti.ch / Ricardo.ch Wizards"]
    end
```

---

## 3. Funktionale Anforderungen (Features)

### 3.1 Eingabe & Persistente Entwurfs-Verwaltung
* **Desktop-Bilder-Upload:** Drag & Drop mehrerer Fotos direkt am PC (unterstützte Formate: JPG, PNG, WebP sowie automatische Konvertierung von iPhone-**HEIC**-Dateien via `pillow-heif`).
* **Persistente Entwurfs-Liste (Multi-Draft):**
  * Lokale Speicherung mehrerer Artikel-Entwürfe auf Vorrat (inkl. Status: *Entwurf*, *Bereit*, *Veröffentlicht*).
  * Jederzeitiges Nachbearbeiten: Weitere Fotos oder Notizen können nachträglich zu einem bestehenden Entwurf hinzugefügt und die KI-Analyse gezielt neu angestossen werden.
  * Alle generierten Felder (Titel, Beschreibung, Preise, Kategorien) sind im Dashboard vor der Übergabe an den Browser manuell editierbar.
* **Kurzbeschreibung / Stichworte:** Freitextfeld für grobe Angaben (z.B. *"Sony WH-1000XM4, ca. 2 Jahre alt, wenig gebraucht, OVP & Ladekabel dabei, Polster intakt"*).
* **Konfigurierbare Voreinstellungen (Presets):**
  * Bevorzugte Verkaufsart bei Ricardo (Auktion vs. Sofortkauf).
  * Konfigurierbare Schweizer Versand-Presets nach aktuellen Post-Tarifen (z.B. B-Post Paket bis 2 kg, B-Post bis 10 kg, Brief/Grossbrief, Abholung vor Ort).

### 3.2 Bildanalyse & Optimierung
* **Standard-Bildoptimierung (Default für authentischen Privatverkauf-Look):**
  * Das **Originalbild bleibt standardmässig erhalten**, um auf Ricardo/Tutti nicht wie ein unzulässiges Stock-/Katalogfoto oder Scam zu wirken.
  * Automatische Basis-Optimierung für jedes Bild: **EXIF/GPS-Metadaten-Entfernung**, automatische Belichtungs-/Kontrastkorrektur und HEIC-zu-JPG-Konvertierung.
* **Optionale Hintergrund-Bearbeitung (Pro Bild umschaltbar):**
  * Toggle pro Bild im Dashboard zwischen:
    1. **Original (optimiert)** *(Standard)*
    2. **Hintergrund weichzeichnen (Background Blur):** Hebt das Objekt hervor, erhält aber den authentischen Charakter eines echten Fotos.
    3. **Freistellen (`rembg`):** Lokale Freistellung auf neutralem Hintergrund (weiss / hellgrau), falls für bestimmte Artikel gewünscht.
* **Iterativer Qualitäts- und Vollständigkeits-Check:**
  * KI prüft, ob wesentliche Merkmale sichtbar sind (z.B. Typenschild, Modellnummer, Mängel, erwähntes Zubehör).
  * Gezielte Hinweise im Dashboard: *"Bitte fotografiere noch das Typenschild / die Seriennummer für bessere Verkaufschancen"*.
  * Der Nutzer kann daraufhin fehlende Fotos im Entwurf ergänzen und die Analyse aktualisieren.
* **Rechtlicher Hinweis (Compliance):**
  * Keine Verwendung fremder Urheberrechts-Bilder aus dem Web als Inseratefoto (Vermeidung von Sperrungen gemäss Ricardo/Tutti AGB). Web-Referenzen dienen ausschliesslich der Modellidentifikation und Spezifikationsabfrage.

### 3.3 Hybride Marktrecherche & Preisermittlung
Da Google Search Grounding allein beendete Auktionen auf Ricardo oder verkaufte eBay-Artikel (`LH_Sold=1`) im Suchindex oft nicht zuverlässig sieht, arbeitet das System **hybrid**:
* **1. Echte eBay-DE Transaktionsdaten (Backend-Parser):**
  * Direkter Abruf/Parsing tatsächlich verkaufter Artikel auf eBay Deutschland (`LH_Sold=1&LH_Complete=1`) im Backend zur Ermittlung realer Gebraucht-Transaktionspreise (Median / Preisspanne), inkl. automatischer Umrechnung EUR $\rightarrow$ CHF.
* **2. Schweizer Neupreis-Anker (Gemini Search Grounding):**
  * Abfrage des aktuellen Schweizer Strassen-/Neupreises (z.B. Digitec/Galaxus, Toppreise.ch) sowie sichtbarer CH-Marktangebote via Google Search Grounding.
  * **Keine pauschale +10–20 % Aufschlagsregel:** Stattdessen intelligente Abwägung zwischen eBay-DE-Verkaufspreis und Schweizer Neupreis-Niveau (da Elektronik in der Schweiz wegen 8.1 % MwSt. neu oft günstiger ist als in DE).
* **Preis-Strategie-Ausgabe & Prüflinks:**
  * Empfohlener Startpreis für Ricardo-Auktionen (attraktiv für Gebote, kein Ramsch).
  * Empfohlener Sofortkaufen-Preis (realistischer Marktwert unter Berücksichtigung der Ricardo-Erfolgsprovision).
  * Empfohlene Tutti-Verhandlungsbasis (VHB).
  * Direkte **1-Klick-Prüflinks** im Dashboard zu beendeten eBay-DE-Angeboten, Ricardo-Suche und Toppreise/Digitec zur schnellen visuellen Plausibilisierung.

### 3.4 Textgenerierung & Plattform-Spezifika

#### Ricardo.ch Anforderungen (angepasst an aktuelles Plattform-UI):
* **Titel:** Strikt maximal **60 Zeichen**, suchbegriffsoptimiert (Marke, Modell, Zustand), keine unzulässigen Füllwörter (kein separates Untertitel-Feld mehr, da von Ricardo abgeschafft).
* **Beschreibung:** Strukturierter Text (Zustand, Lieferumfang, technische Kerndaten, Garantiehinweis gemäss Schweizer Recht *"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme"*).
* **Universelle Pflichtfelder:** Fokus auf Zustand-Mapping, Preis (Startpreis / Sofortkauf) und Übergabe/Versand-Presets.

#### Tutti.ch Anforderungen:
* **Titel:** Ansprechend und klar verständlich (bis 80 Zeichen).
* **Kategorie-Empfehlung:** Vorschlag der am besten passenden Tutti-Kategorie.
* **Beschreibung:** Fliessender, seriöser Verkaufstext inklusive aller relevanten Details und Übergabe-/Zahlungshinweisen (z.B. Abholung / Versand / TWINT möglich).
* **Zustand:** Automatische Klassifizierung passend zu Tutti (Neu, Wie neu, Gebraucht, Defekt).

### 3.5 Firefox-Erweiterung (Smart-Panel & Auto-Fill Integration)
* **Architektur & CORS/CSP-Schutz:**
  * Firefox WebExtension (Manifest V3).
  * Sämtliche Requests an `http://127.0.0.1:8000/api/...` laufen zwingend über das **Background-Script (Service Worker)** der Erweiterung und werden per Message-Passing (`browser.runtime.sendMessage`) an das Content Script übergeben, um CORS-, Mixed-Content- und CSP-Blockaden von `ricardo.ch` und `tutti.ch` zu umgehen.
* **Smart-Panel UI im Browser:**
  * Einklappbares Floating-Panel auf den Inserate-Erstellungsseiten von `tutti.ch` und `ricardo.ch`.
  * **Entwurfs-Dropdown:** Auswahl des gewünschten Artikels direkt aus der lokalen Entwurfs-Liste.
  * **Schritt-für-Schritt Auto-Fill (Wizard-kompatibel):**
    * Unterstützt die mehrstufigen React/Next.js-Formulare (z.B. *Schritt 1: Bilder & Titel injizieren* $\rightarrow$ Plattform schlägt Kategorie vor $\rightarrow$ *Schritt 2: Beschreibung, Zustand & Preise injizieren*).
  * **1-Klick-Copy-Buttons (Fallback):** Neben jedem Feld im Smart-Panel (Titel, Beschreibung, Startpreis, Sofortkaufpreis) gibt es einen direkten Kopier-Button, falls die Plattform ihre DOM-Selektoren kurzfristig ändert.
* **Technische Feld-Befüllung:**
  * Text- & Nummernfelder über native Value-Setter (`HTMLInputElement.prototype.value`) inkl. Dispatch von `input`-, `change`- und `blur`-Events für React-State-Synchronisation.
  * **Automatischer Bild-Upload:** Abruf der optimierten Bilder über das Background-Script als `Blob`/`File`, Bündelung in einem `DataTransfer`-Objekt und Übergabe an das `<input type="file">`-Element bzw. Dropzone-Event der Plattform.

---

## 4. Nicht-funktionale Anforderungen

* **Betrieb & Kosten:**
  * Nutzung des kostenlosen Google AI Studio Tiers (Gemini API mit Search Grounding).
  * Das verwendete Gemini-Modell (z.B. `gemini-2.5-flash` oder `gemini-2.0-flash`) ist über eine lokale `.env`-Datei frei konfigurierbar.
  * Vollständig lokaler Betrieb auf `127.0.0.1:8000` (kein Cloud-Hosting nötig).
* **Datenschutz & Privatsphäre (Schutz im Free Tier):**
  * Bilder und Entwürfe verbleiben lokal auf dem Rechner gespeichert.
  * Vor dem Versand an die Google Gemini API werden Bilder lokal **von allen EXIF-/GPS-Metadaten bereinigt**, auf maximal **1024px Kantenlänge** herunterskaliert und auf Wunsch vorab freigestellt, um private Hintergrunddetails und Bandbreite zu minimieren.
* **Leistung & Geschwindigkeit:**
  * Standard-Bildoptimierung (HEIC-Konvertierung, Resize, EXIF-Strip, Auto-Kontrast) < 1 Sekunde pro Bild.
  * Optionale Bildfreistellung via `rembg` < 3 Sekunden pro Bild auf gängiger Hardware.
  * Komplette Inseratsgenerierung (inkl. eBay-DE-Abfrage & Gemini Search Grounding) < 10–15 Sekunden (durch vorheriges Downscaling der API-Bilder auf max. 1024px beschleunigt).

---

## 5. Phasenplan zur Umsetzung

| Phase | Modul / Schritt | Ergebnis |
| :--- | :--- | :--- |
| **Phase 1** | **Backend, Persistenz & Bild-Pipeline** | FastAPI Backend, Multi-Draft-Speicher (SQLite/JSON) & Bildverarbeitung (HEIC, EXIF-Strip, Auto-Enhance, opt. `rembg` & Blur) |
| **Phase 2** | **Hybride Preis-Engine & KI-Logik** | eBay-DE Sold-Parser + Gemini Service (konfigurierbares Modell, 1024px-Upload, CH-Neupreis Grounding, Ricardo/Tutti-Prompts) |
| **Phase 3** | **Web-Dashboard UI** | Lokale Weboberfläche für Entwurfs-Liste, Upload, Bild-Toggles, iterative Nachbearbeitung & Prüflinks |
| **Phase 4** | **Firefox WebExtension (Smart-Panel)** | Add-on mit Background-Worker (CORS-frei), Entwurfs-Auswahl, Wizard-Auto-Fill & 1-Klick-Copy-Fallbacks |
| **Phase 5** | **Testing & Feinschliff** | End-to-End-Tests der Pipeline, API-Endpunkte und Extension-Injektion |
