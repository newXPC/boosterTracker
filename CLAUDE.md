# BoosterTracker — Projektkontext für Claude

Automatische Pokémon-Kartenerkennung für Whatnot-Streams (Set: Ewige Rivalen / SV10).
Eine Webcam zeigt Karten, der Scanner erkennt sie per Bildvergleich und aktualisiert
Live-Overlays für OBS. Details für Menschen: README.md.

## Architektur (aktueller Stand)

- **`stream_monitor_v4.py`** — DER Haupt-Scanner. Erkennung: ORB-Features →
  FLANN-LSH-Voting gegen alle 244 Referenzkarten → RANSAC-Homographie-Verifikation.
  KEIN OCR (Kartennummern sind zu klein für Kameras — alle OCR-Ansätze sind
  gescheitert). Startet auch den HTTP-Server (Port 8765) für die Overlays.
- **`commons_scanner.py`** — Stapel-Zählmodus nach dem Stream (Duplikate erlaubt,
  Gate-Logik: Karte muss zwischen zwei Zählungen aus dem Bild). Importiert alles
  aus stream_monitor_v4.
- **Overlays** (alle vom HTTP-Server ausgeliefert, in OBS als Browser-Quelle per URL):
  - `booster-tracker.html` — Haupt-Overlay: Zähler (ex/IR/FA/Gold/SAR),
    "Heute gezogen"-Ticker, Karten-Karussell (nur IR/FA/Gold/SAR!), Hit-Liste
  - `booster-tracker-alle.html` — Tabelle aller Karten + Gesamtwert (Commons-Scanner)
  - `alert.html` — Vollbild-Hit-Animation (pollt Tracker-Seite, feuert bei neuer
    Karussell-Karte; SAR/Hyper oder ≥50€ = Konfetti + Fanfare)
  - `frame.html` — goldener Leuchtrahmen ums Kamerabild
- **`start_stream.bat`** — Reset beider Seiten + Scanner-Start in einem Doppelklick
- **Daten**: `sv10-preise.json` (244 Karten, Cardmarket-Preise, `name_de` = deutsche
  Namen von tcgdex), `sv10_cards_images/` (Referenzbilder von api.pokemontcg.io)
- **Archiv/veraltet**: `cards_ocr.py`, `stream_monitor.py`, `_v2`, `_v3`,
  `stream_monitor_vision.py`, alle `debug_*.py` — nicht weiterentwickeln

## Wichtige Konfiguration (Konstanten oben in stream_monitor_v4.py)

- `MONITOR` — mss-Monitor-Index mit dem Kamerafenster (1 = Hauptmonitor).
  Bei mehreren Monitoren MUSS der Offset (`monitor['left']/['top']`) in der
  Region eingerechnet sein — ist im Code bereits korrekt.
- Capture-Region: Prozentwerte in `take_screenshot()` — erfasst die BILDSCHIRMMITTE
  (dort zeigt Camo/die Kamera die Karte). Bei anderem Fensterlayout anpassen.
- `MIN_INLIERS = 15` — sofortige Erkennung; `PERSIST_MIN_INLIERS/PERSIST_SCANS` —
  Holo-/Full-Art-Karten reflektieren und liefern weniger Inlier, werden über
  Konsistenz mehrerer Scans akzeptiert. Bei Erkennungsproblemen: `DEBUG = True`
  zeigt Votes + Inlier pro Scan.
- ENTER im Scanner-Terminal = aktuelles Display archivieren, nächstes starten.

## Bekannte Stolperfallen (alle schon einmal passiert!)

1. **OBS-Browserquelle MUSS `http://localhost:8765/...` nutzen, NIE die lokale
   Datei**: fetch() scheitert auf file:// → die Seite fällt auf einen
   2s-Voll-Reload zurück → Karussell/Animationen resetten ständig.
2. **OBS/Spiel im exklusiven Vollbild blockiert Screenshots** — Camo/Kamerabild
   als normales Fenster oder Vollbild-Projektor zeigen.
3. **Cardmarket NIEMALS im Browser automatisieren** (Cloudflare-Botschutz,
   hat App-Abstürze verursacht). Preise kommen aus sv10-preise.json
   (api.pokemontcg.io), deutsche Namen von api.tcgdex.net.
4. Beleuchtung ist der größte Hebel für die Erkennungsrate. Finger auf der
   Karte sind okay (deshalb ORB statt Konturen-Freistellung).
5. Windows-Konsole + Unicode (✓, Emojis) → UnicodeEncodeError. In Scripten
   ASCII verwenden oder PYTHONIOENCODING=utf-8.
6. `update_html`/`update_html_all` arbeiten mit Regex-Ersetzung auf den
   HTML-Dateien — bei Layout-Änderungen die Marker (`<div class="counters">`,
   `<p class="display-label">`, `<p class="stream-total">`, `<tbody>`,
   `<footer>`) nicht entfernen und Ersetzungen idempotent halten.

## Anderes Set einrichten

1. `generate_sv10_hashes.py`: Set-ID ändern (Pokemon TCG API, z. B. `sv09`),
   lädt Referenzbilder herunter
2. Preistabelle neu aufbauen (api.pokemontcg.io, Feld `cardmarket.prices`,
   gleiche Struktur wie sv10-preise.json inkl. `number`, `name`, `rarity`, `avg7`)
3. Deutsche Namen: `https://api.tcgdex.net/v2/de/sets/<set-id>` → Feld `name_de`
