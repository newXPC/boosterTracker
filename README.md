# BoosterTracker

Automatische Pokémon-Kartenerkennung für Whatnot-Streams (Set: **Ewige Rivalen / SV10**).
Karten werden per Webcam erkannt (ORB-Feature-Matching + RANSAC, kein OCR) und live
auf einer HTML-Seite mit Cardmarket-Preisen angezeigt.

## Die zwei Scanner

| Script | Zweck | Ausgabe |
|---|---|---|
| `stream_monitor_v4.py` | **Live im Stream**: zeigt nur Hits (ex, Full Art, IR, SAR, Gold oder ≥ 1 €) | `booster-tracker.html` |
| `commons_scanner.py` | **Nach dem Stream**: Commons-Stapel durchzählen, Duplikate erlaubt | `booster-tracker-alle.html` (Liste + Gesamtwert) |

## Setup (einmalig)

1. **Python 3.10+** installieren (getestet mit 3.12)

2. Repo klonen und Abhängigkeiten installieren:

   ```
   git clone https://github.com/newXPC/boosterTracker
   cd boosterTracker
   pip install opencv-python opencv-contrib-python mss pillow numpy requests
   ```

   *(EasyOCR/PyTorch werden NICHT benötigt — die alten OCR-Scripte sind nur Archiv.)*

3. Referenzbilder liegen schon im Repo (`sv10_cards_images/`, 244 Karten).
   Falls sie fehlen: `python generate_sv10_hashes.py` lädt sie neu herunter.

## Kamera-Setup

- Handy als Webcam (z. B. **Camo**) oder normale Webcam
- Das Kamerabild muss als **Fenster in der Bildschirmmitte** sichtbar sein
- Karte frontal vor die Kamera halten, gute Beleuchtung — Finger auf der Karte sind okay

**Wichtig:** Der Scanner screenshottet die **Mitte des Hauptmonitors**
(`take_screenshot()` in `stream_monitor_v4.py`). Wenn das Kamerafenster woanders
liegt, die Prozentwerte in der `region` anpassen:

```python
region = {
    'top':    int(monitor['height'] * 0.15),  # Abstand oben
    'left':   int(monitor['width']  * 0.32),  # Abstand links
    'width':  int(monitor['width']  * 0.36),  # Breite
    'height': int(monitor['height'] * 0.7),   # Höhe
}
```

## Benutzung

**Stream-Scanner** (nur Hits):

```
python stream_monitor_v4.py
```

`booster-tracker.html` in OBS als Browser-Quelle (lokale Datei) einbinden
oder auf dem Tablet öffnen. Die Seite aktualisiert sich jede Sekunde selbst.

**Commons-Scanner** (Stapel zählen):

```
python commons_scanner.py
```

Karte zeigen → wird gezählt → wegnehmen → nächste. Dieselbe Karte wird erneut
gezählt, sobald sie einmal aus dem Bild war. `booster-tracker-alle.html` zeigt
die komplette Liste mit Gesamtwert. Strg+C beendet und druckt die Zusammenfassung.

## Anderes Set als Ewige Rivalen?

1. In `generate_sv10_hashes.py` die Set-ID ändern (z. B. `sv09`) und laufen lassen
2. `sv10-preise.json` mit den Preisen des Sets neu aufbauen (api.pokemontcg.io,
   Feld `cardmarket.prices`)
3. Deutsche Namen kommen von `api.tcgdex.net/v2/de/sets/<set-id>`

## Troubleshooting

- **Karte wird nicht erkannt**: `DEBUG = True` in `stream_monitor_v4.py` zeigt pro
  Scan die Kandidaten-Votes und RANSAC-Inlier. Karte ruhiger/näher halten,
  Beleuchtung verbessern.
- **Falsches Fenster wird gescannt**: Capture-Region anpassen (siehe oben).
  Zum Prüfen `debug_v3.py` ausführen — speichert den erfassten Bereich als Bild.
- **Seite aktualisiert nicht**: Browser-Quelle in OBS einmal neu laden
  (das Update-Script pollt die Datei jede Sekunde per `fetch`).
