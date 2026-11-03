# Anforderungsdokument (Requirements Document)
## KI-gestützter Inserate-Generator (OccAIsion)

* **Projekt:** OccAIsion (`occaision`)
* **Einsatzbereich:** Persönlicher Gebrauch (Single-User, lokaler Desktop-Betrieb, kein externes Deployment nötig)
* **Unterstützte Marktplätze:**
  * **Schweiz (CH):** Ricardo (`ricardo.ch`) & Tutti (`tutti.ch`)
  * **Deutschland (DE):** eBay Deutschland (`ebay.de`) & Kleinanzeigen (`kleinanzeigen.de`)
* **Status:** Geschärft & Freigegeben (Erweitert um DE-Plattformen)
* **Datum:** 2026-11-01

---

## 1. Zielsetzung & Problemstellung

Beim regelmässigen Einstellen von Gebrauchtartikeln auf Schweizer (**Ricardo.ch**, **Tutti.ch**) und deutschen Plattformen (**eBay.de**, **Kleinanzeigen.de**) entstehen erhebliche Reibungspunkte:
* **Unterschiedliche Plattformanforderungen:**
  * **Ricardo.ch:** Striktes 60-Zeichen-Titellimit, Auktion vs. Sofortkauf, mehrstufiger Formular-Wizard, Schweizer Rechtschreibung (`ss` statt `ß`), Preise in CHF.
  * **Tutti.ch:** Klassische Schweizer Kleinanzeige (bis 80 Zeichen Titel, VHB-Preis in CHF, TWINT/Abholung/Post-Versand).
  * **eBay.de:** Maximal 80 Zeichen Titel (suchbegriffsoptimiert), Auktion vs. Sofort-Kaufen, Preise in EUR, deutsche Standard-Rechtschreibung (inkl. `ß`), EU-/deutsches Privatverkaufsrecht (Ausschluss der Sachmängelhaftung).
  * **Kleinanzeigen.de:** Klassische deutsche Kleinanzeige (Titel bis 65–80 Zeichen, Festpreis oder Verhandlungsbasis/VB in EUR, „Direkt kaufen" / PayPal / Überweisung / Abholung, DHL/Hermes/Post-Versand).
* Mühsames manuelles Copy-Pasten von Texten, Preisen und Auswählen von Dropdowns über mehrere Länder- und Plattform-Wizards hinweg.
* Suboptimale Smartphone-Fotos (schlechte Ausleuchtung, unruhige Hintergründe, inkompatible Formate wie HEIC, verräterische EXIF/GPS-Metadaten).
* Schwierige länderübergreifende Preisfindung: Wunschpreise auf Kleinanzeigen/Tutti reflektieren oft nicht den tatsächlichen Marktwert, und zwischen dem deutschen Markt (EUR, 19 % MwSt.) und dem Schweizer Markt (CHF, 8.1 % MwSt., oft tieferes Neupreis-Niveau bei Elektronik) bestehen signifikante Preisunterschiede.

**Lösung:** Eine lokale Hybrid-Lösung (**OccAIsion**) aus einem **FastAPI/Python-Backend mit Web-Dashboard** (für Desktop-Upload, persistente Entwurfs-Verwaltung, Bildoptimierung, hybride CH/DE-Preisfindung und plattformspezifische Textgenerierung) und einer **Firefox-Browsererweiterung (Manifest V3)** mit Smart-Panel zum schrittweisen Befüllen der Inserate-Formulare auf allen vier Zielplattformen (inkl. Bild-Upload und 1-Klick-Copy-Fallbacks).

---

## 2. Systemarchitektur & Komponenten

```mermaid
flowchart TD
    User["Benutzer (Desktop)"] -->|1. Produktname, Kurzbeschreibung & Fotos| Dashboard["Lokales Web-Dashboard (OccAIsion - FastAPI + HTML/JS)"]
    
    subgraph Browser ["Firefox Browser & Extension"]
        DashBridge["Dashboard Content-Script Bridge (postMessage <-> runtime.sendMessage)"]
        BgScript["Extension Background Worker (Hybrid-Scraper: fetch + Tab-DOM-Fallback)"]
        ContentScript["Smart-Panel Content Script (ricardo.ch / tutti.ch / ebay.de / kleinanzeigen.de)"]
        PriceSites["6 Preisquellen (eBay DE Gebraucht/Beendet, Kleinanzeigen, Idealo, Ricardo, Toppreise, Digitec)"]
        
        Dashboard <-->|2. Optionale Preisrecherche| DashBridge
        DashBridge <--> BgScript
        BgScript -->|Abruf & Parsing im echten Browser| PriceSites
        ContentScript <-->|browser.runtime.sendMessage| BgScript
        ContentScript -->|Schrittweise DOM-Injektion & File-Upload| PlatformForms["Plattform-Wizards (CH & DE)"]
    end

    subgraph Local_Backend ["Lokales Backend (127.0.0.1:8000)"]
        Dashboard --> ImgProc["Bild-Pipeline (Pillow/HEIF, EXIF-Strip, Auto-Enhance, opt. rembg/Blur)"]
        Dashboard --> DraftStore["Persistente Entwurfs-Verwaltung (Lokale JSON + Bild-Ordner)"]
        Dashboard -->|3. KI-Analyse (inkl. Extension-Preise falls ermittelt)| AI_Engine["Gemini API (konfigurierbar via .env / UI)"]
        AI_Engine -->|Nur falls Schritt 2 übersprungen| FallbackPrice["Fallback: Backend eBay-Parser & opt. Google Search Grounding"]
        BgScript <-->|REST API (Entwürfe & Bilder)| DraftStore
    end
```

---

## 3. Funktionale Anforderungen (Features)

### 3.1 Eingabe & Persistente Entwurfs-Verwaltung
* **Desktop-Bilder-Upload:** Drag & Drop mehrerer Fotos direkt am PC (unterstützte Formate: JPG, PNG, WebP sowie automatische Konvertierung von iPhone-**HEIC**-Dateien via `pillow-heif`).
* **Persistente Entwurfs-Liste (Multi-Draft):**
  * Lokale Speicherung mehrerer Artikel-Entwürfe auf Vorrat (inkl. Status: *Entwurf*, *Bereit*, *Veröffentlicht*).
  * Jederzeitiges Nachbearbeiten: Weitere Fotos oder Notizen können nachträglich zu einem bestehenden Entwurf hinzugefügt und die KI-Analyse gezielt neu angestossen werden.
  * Alle generierten Felder (Titel, Beschreibung, Preise, Kategorien für CH- und DE-Plattformen) sind im Dashboard vor der Übergabe an den Browser manuell editierbar.
* **Aufgeteilte Eingabefelder (Produktname vs. Kurzbeschreibung):**
  * **Produktname / Modell:** Eigenes Eingabefeld für die genaue Modellbezeichnung (z.B. *"Sony WH-1000XM4"* oder *"HP Color LaserJet Pro MFP 4302fdw"*), das direkt als Suchbegriff für die Preisrecherche über die Firefox-Extension dient.
  * **Kurzbeschreibung / Zustand & Lieferumfang:** Separates Freitextfeld für Zustand, Alter, Mängel und Zubehör (z.B. *"ca. 2 Jahre alt, wenig gebraucht, OVP & Ladekabel dabei, Polster intakt"*).
* **Konfigurierbare Voreinstellungen (Presets für CH & DE):**
  * Bevorzugte Verkaufsart bei Auktionsplattformen (Auktion vs. Sofortkauf für Ricardo.ch und eBay.de) bzw. Preistyp bei Kleinanzeigen (Verhandlungsbasis/VB vs. Festpreis).
  * **Schweizer Versand-Presets (CHF):** Nach aktuellen Schweizer Post-Tarifen (z.B. B-Post Paket bis 2 kg, B-Post bis 10 kg, Grossbrief, Abholung vor Ort).
  * **Deutsche Versand-Presets (EUR):** Nach aktuellen Tarifen in Deutschland (z.B. DHL Paket bis 2 kg versichert, DHL Paket bis 5 kg, Hermes Päckchen/Paket, Deutsche Post Bücher-/Warensendung, Nur Abholung vor Ort).

### 3.2 Bildanalyse & Optimierung
* **Standard-Bildoptimierung (Default für authentischen Privatverkauf-Look):**
  * Das **Originalbild bleibt standardmässig erhalten**, um auf den Plattformen nicht wie ein unzulässiges Stock-/Katalogfoto oder Scam zu wirken.
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
  * Keine Verwendung fremder Urheberrechts-Bilder aus dem Web als Inseratefoto (Vermeidung von Sperrungen/Abmahnungen gemäss Plattform-AGB und Urheberrecht). Web-Referenzen dienen ausschliesslich der Modellidentifikation und Spezifikationsabfrage.

### 3.3 Mehrstufige Marktrecherche & Preisermittlung über Firefox-Extension (CH & DE)
Da Server-/Backend-Requests häufig durch Anti-Bot-Systeme (z.B. eBay Captchas, Cloudflare) blockiert werden und Google Search Grounding im Free Tier strengen Quota-Limits (`429 RESOURCE_EXHAUSTED`) unterliegt, arbeitet das System in einem **mehrstufigen Prozess**:

* **Schritt 1: Eingabe (Produktname & Kurzbeschreibung):**
  * Der Benutzer erfasst den **Produktnamen** sowie die **Kurzbeschreibung** (und lädt Fotos hoch).
* **Schritt 2 (Optional, manuell ausgelöst): Preisrecherche über die Firefox-Extension:**
  * Über den Button *"🔍 1. Preisrecherche über Extension (Optional)"* im Dashboard befragt die Firefox-Extension direkt im Browser des Nutzers **alle 6 Preisquellen** mittels **Hybrid-Scraping** (zuerst schneller `fetch()`, bei SPA/Bot-Schutz oder 0 Treffern automatischer Fallback auf einen temporären inaktiven Hintergrund-Tab mit DOM-Extraktion nach JS-Rendering):
    1. **eBay DE (Gebraucht und Beendet):** Verkaufte Gebraucht-Artikel (`LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000`) in EUR (inkl. Umrechnung in CHF).
    2. **Kleinanzeigen.de Suche:** Aktuelle Gebraucht-Angebote auf `kleinanzeigen.de` in EUR.
    3. **Idealo.de Neupreis:** Aktueller deutscher Strassen-/Neupreis auf `idealo.de` in EUR.
    4. **Ricardo.ch Suche:** Aktuelle Angebote auf `ricardo.ch` in CHF.
    5. **Toppreise.ch Neupreis:** Aktueller Schweizer Neupreisvergleich auf `toppreise.ch` in CHF.
    6. **Digitec/Galaxus Suche:** Aktueller Schweizer Neupreis auf `digitec.ch` in CHF.
  * Für jede Quelle werden **Median** (mit 10%-Outlier-Trimming ab 4 Treffern), **Preisspanne (Min–Max)** und **Anzahl Treffer** berechnet, im Dashboard angezeigt und im Entwurf gespeichert.
* **Schritt 3: KI-Analyse & Preisfindung (`⚡ 2. KI-Analyse starten`):**
  * **Fall A – Preise wurden in Schritt 2 über die Extension ermittelt:**
    * Alle 6 ermittelten Preisstatistiken werden strukturiert im Prompt an Gemini übergeben.
    * **Google Search Grounding wird für diesen Aufruf automatisch deaktiviert** (schont das API-Quota und verhindert 429-Fehler); die KI bestimmt die optimalen Plattformpreise und generiert die Inseratetexte direkt auf Basis der echten Marktdaten.
  * **Fall B – Schritt 2 wurde übersprungen (keine Extension-Preise vorhanden):**
    * Das System überlässt die Preisrecherche der KI (je nach Einstellung in `⚙️ Einstellungen` mit oder ohne Google Search Grounding sowie Backend-eBay-Fallback).
* **Preis-Strategie-Ausgabe & Prüflinks:**
  * **CH-Preise (in CHF):**
    * Empfohlener Startpreis für Ricardo-Auktionen (`ricardo_start_chf`).
    * Empfohlener Sofortkaufen-Preis für Ricardo (`ricardo_buynow_chf`).
    * Empfohlene Tutti-Verhandlungsbasis (`tutti_vhb_chf`).
  * **DE-Preise (in EUR):**
    * Empfohlener Startpreis für eBay.de-Auktionen (`ebay_start_eur`).
    * Empfohlener Sofort-Kaufen-Preis für eBay.de (`ebay_buynow_eur`).
    * Empfohlener Preis für Kleinanzeigen.de (`kleinanzeigen_vb_eur`).
  * **Direkte 1-Klick-Prüflinks** im Dashboard zu:
    * eBay.de Verkaufte Gebraucht-Artikel (`LH_Sold=1&LH_Complete=1&LH_ItemCondition=3000`)
    * Kleinanzeigen.de Suche
    * Idealo.de (DE-Neupreisvergleich)
    * Ricardo.ch Suche
    * Toppreise.ch & Digitec.ch (CH-Neupreisvergleich)

### 3.4 Textgenerierung & Plattform-Spezifika (Plattformabhängige Sprache & Rechtsklauseln)

#### A) Schweizer Plattformen (CHF, Schweizer Hochdeutsch mit `ss` statt `ß`, CH-Recht)
* **Ricardo.ch Anforderungen:**
  * **Titel:** Strikt maximal **60 Zeichen**, suchbegriffsoptimiert (Marke, Modell, Zustand), keine unzulässigen Füllwörter.
  * **Beschreibung:** Strukturierter Text in Schweizer Rechtschreibung (`ss` statt `ß`: Zustand, Lieferumfang, technische Kerndaten, Versand & Abholung) sowie Schweizer Gewährleistungsausschluss: *"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."*
  * **Pflichtfelder:** Zustand-Mapping, Angebotsart (Auktion / Sofortkauf), Preise in CHF, CH-Versand-Preset.
* **Tutti.ch Anforderungen:**
  * **Titel:** Ansprechend und klar verständlich (maximal **80 Zeichen**, `ss` statt `ß`).
  * **Kategorie-Empfehlung:** Vorschlag der am besten passenden Tutti-Kategorie.
  * **Beschreibung:** Fliessender, seriöser Verkaufstext in Schweizer Rechtschreibung inklusive Übergabe-/Zahlungshinweisen (Abholung / Post-Versand / TWINT) und Schweizer Gewährleistungsausschluss (*"Privatverkauf, ohne Gewährleistung/Garantie, keine Rücknahme."*).
  * **Zustand & Preis:** Automatische Klassifizierung (Neu, Wie neu, Gebraucht, Defekt) und VHB-Preis in CHF.

#### B) Deutsche Plattformen (EUR, Standard-Deutsch inkl. `ß`, DE/EU-Privatverkaufsrecht)
* **eBay.de Anforderungen:**
  * **Titel:** Strikt maximal **80 Zeichen**, SEO-/suchbegriffsoptimiert für die eBay-Kassensuche (Marke, Modell, wichtige Artikelmerkmale, Zustand).
  * **Kategorie-Empfehlung:** Passender eBay.de Kategorievorschlag.
  * **Beschreibung:** Strukturierter Verkaufstext in deutscher Standard-Rechtschreibung (inkl. `ß`: Zustand, Lieferumfang, Technische Daten, Versand via DHL/Hermes/Post & Zahlung) sowie rechtssicherer deutscher Privatverkaufs-Disclaimer nach BGB/EU-Recht: *"Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."*
  * **Pflichtfelder:** Zustand-Mapping, Angebotsformat (Auktion vs. Sofort-Kaufen), Startpreis & Sofort-Kaufen-Preis in EUR, DE-Versand-Preset.
* **Kleinanzeigen.de Anforderungen:**
  * **Titel:** Prägnant und suchfreundlich, maximal **65 Zeichen** (Kleinanzeigen.de begrenzt Titel im Web-Formular strikt auf 65 Zeichen).
  * **Kategorie-Empfehlung:** Vorschlag der passenden Kleinanzeigen.de-Kategorie (z.B. *"Audio & Hifi > Kopfhörer"*).
  * **Beschreibung:** Freundlicher, vertrauenserweckender Anzeigentext in deutscher Standard-Rechtschreibung (inkl. `ß`), Hinweis auf Abholung oder versicherten Versand (DHL/Hermes) sowie Bezahloptionen (Barzahlung bei Abholung, „Direkt kaufen", PayPal / Überweisung) und deutschem Sachmängelhaftungsausschluss: *"Der Verkauf erfolgt unter Ausschluss jeglicher Sachmängelhaftung. Keine Garantie oder Rücknahme, da Privatverkauf."*
  * **Zustand & Preis:** Zustand-Mapping, Preis in EUR sowie Preistyp (Verhandlungsbasis `VB` vs. Festpreis).

### 3.5 Firefox-Erweiterung (Smart-Panel & Auto-Fill Integration für CH & DE)
* **Neutrale Benennung:**
  * Die Erweiterung und das Dashboard tragen den plattformneutralen Namen **`OccAIsion`** (Paket-/Build-Slug `occaision`).
* **Architektur & CORS/CSP-Schutz:**
  * Firefox WebExtension (Manifest V3).
  * Sämtliche Requests an `http://127.0.0.1:8000/api/...` laufen zwingend über das **Background-Script (Service Worker)** der Erweiterung und werden per Message-Passing (`browser.runtime.sendMessage`) an das Content Script übergeben, um CORS-, Mixed-Content- und CSP-Blockaden von `ricardo.ch`, `tutti.ch`, `ebay.de` und `kleinanzeigen.de` zu umgehen.
* **Smart-Panel UI im Browser:**
  * Einklappbares Floating-Panel auf den Inserate-Erstellungsseiten von `ricardo.ch`, `tutti.ch`, `ebay.de` und `kleinanzeigen.de`.
  * **Automatische Plattform-Erkennung:** Erkennt anhand der aktuellen Domain (`ricardo.ch`, `tutti.ch`, `ebay.de`, `kleinanzeigen.de`), welche plattformspezifischen Texte, Preise (CHF vs. EUR) und Formular-Selektoren verwendet werden müssen.
  * **Entwurfs-Dropdown:** Auswahl des gewünschten Artikels direkt aus der lokalen Entwurfs-Liste.
  * **Schritt-für-Schritt Auto-Fill (Wizard-kompatibel):**
    * Unterstützt sowohl mehrstufige Formulare (Ricardo.ch, eBay.de) als auch einseitige Inserate-Formulare (Tutti.ch, Kleinanzeigen.de):
      * *Schritt 1: Bilder & Titel einfügen* (injiziert die optimierten Bilder in den Datei-Upload/Dropzone und trägt den plattformspezifischen Titel ein).
      * *Schritt 2: Beschreibung, Zustand & Preis einfügen* (befüllt das Beschreibungsfeld, inkl. allfälligem Rich-Text/`contenteditable`-Editor oder `iframe` bei eBay.de, wählt nach Möglichkeit den Zustand und trägt Start-/Sofortkauf-/VB-Preis in der jeweiligen Landeswährung ein).
  * **1-Klick-Copy-Buttons (Fallback):** Neben jedem Feld im Smart-Panel (Titel, Beschreibung, Preise, Kategorie) gibt es einen direkten Kopier-Button für die gerade aktive Plattform, falls eine Plattform ihre DOM-Selektoren kurzfristig ändert.
* **Technische Feld-Befüllung:**
  * Text- & Nummernfelder über native Value-Setter (`HTMLInputElement.prototype.value` / `HTMLTextAreaElement.prototype.value`) inkl. Dispatch von `input`-, `change`- und `blur`-Events für React/Marko/Next.js-State-Synchronisation (sowie Unterstützung für `contenteditable`-Editoren auf `ebay.de`).
  * **Automatischer Bild-Upload:** Abruf der optimierten Bilder über das Background-Script, Bündelung in einem Firefox-Xray-kompatiblen `DataTransfer`-Objekt und Übergabe an das `<input type="file">`-Element bzw. Dropzone-Event der jeweiligen Plattform.

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
  * Komplette Inseratsgenerierung für alle vier Plattformen (inkl. eBay-DE-Abfrage & Gemini Search Grounding) < 10–15 Sekunden (durch einen kombinierten KI-Aufruf mit auf max. 1024px skalierten Bildern).

---

## 5. Phasenplan zur Umsetzung

| Phase | Modul / Schritt | Ergebnis |
| :--- | :--- | :--- |
| **Phase 1** | **Backend, Persistenz & Bild-Pipeline** | FastAPI Backend, Multi-Draft-Speicher (CH & DE Datenmodelle, Versand-Presets) & Bildverarbeitung (HEIC, EXIF-Strip, Auto-Enhance, opt. `rembg` & Blur) |
| **Phase 2** | **Hybride Preis-Engine & KI-Logik** | eBay-DE Sold-Parser + Gemini Service (konfigurierbares Modell, 1024px-Upload, CH- & DE-Neupreis Grounding, Prompts & Validierung für Ricardo, Tutti, eBay.de & Kleinanzeigen.de) |
| **Phase 3** | **Web-Dashboard UI** | Neutrale lokale Weboberfläche (`OccAIsion`) für Entwurfs-Liste, Upload, Bild-Toggles, CH/DE-Plattform-Vorschaukarten & Prüflinks |
| **Phase 4** | **Firefox WebExtension (Smart-Panel)** | Neutral benanntes Add-on (`OccAIsion`) mit Background-Worker (CORS-frei), Plattform-Erkennung (`ricardo.ch`, `tutti.ch`, `ebay.de`, `kleinanzeigen.de`), Wizard-Auto-Fill & 1-Klick-Copy-Fallbacks |
| **Phase 5** | **Testing & Feinschliff** | End-to-End-Tests der Pipeline, API-Endpunkte, sprach-/rechtsspezifischen Safeguards und Extension-Injektion |
