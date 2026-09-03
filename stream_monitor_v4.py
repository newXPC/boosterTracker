#!/usr/bin/env python3
"""
Booster Tracker v4 - ORB-Feature-Matching + RANSAC-Verifikation.

Robuste Kartenerkennung OHNE Freistellen der Karte:
  1. Screenshot der Camo-Region
  2. ORB-Features im Frame berechnen (markante Bildpunkte)
  3. Gegen vorberechnete Features aller 244 SV10-Karten matchen
  4. Top-Kandidaten geometrisch verifizieren (RANSAC-Homographie)
  5. >= MIN_INLIERS Inlier -> Karte erkannt -> HTML-Update

Funktioniert auch wenn Finger die Karte teilweise verdecken.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import mss

try:
    import msvcrt  # Windows: Tastatur-Abfrage ohne Blockieren
except ImportError:
    msvcrt = None

try:
    import ctypes
    import win32gui
    import win32ui
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # echte Pixel bei Skalierung
    WIN32_AVAILABLE = True
except Exception:
    WIN32_AVAILABLE = False

import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from functools import partial

# Als EXE (PyInstaller) liegen die Daten neben der EXE, nicht im Bundle
if getattr(sys, 'frozen', False):
    BOOSTER_DIR = Path(sys.executable).parent
else:
    BOOSTER_DIR = Path(__file__).parent
PRICE_DB = BOOSTER_DIR / "sv10-preise.json"
CARDS_DIR = BOOSTER_DIR / "sv10_cards_images"
HTML_FILE = BOOSTER_DIR / "booster-tracker.html"
HTML_ALL_FILE = BOOSTER_DIR / "booster-tracker-alle.html"
SCREENSHOT_DIR = BOOSTER_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

MONITOR = 1                # mss-Monitor-Index mit dem Camo-Fenster
                           # (1 = Hauptmonitor, 2 = zweiter Monitor, ...)
REGION_PCT = {             # Capture-Bereich in Prozent des Monitors
    'top': 0.40, 'left': 0.36, 'width': 0.24, 'height': 0.42,
}
RESET_ON_START = False     # True: Seiten beim Start auf null setzen (EXE-Modus)
WINDOW_TITLE = ""          # Fenstertitel (Teil reicht) -> Fensteraufnahme statt
                           # Bildschirmbereich (wie Teams-Fensterfreigabe)
SET_ID = "sv10"            # aktives Set (siehe sets.json); per App-UI umschaltbar
RAW_BASE = "https://raw.githubusercontent.com/newXPC/boosterTracker/master/"
SET_SWITCH_REQUEST = []    # [set_id] -> Hauptloop laedt das Set live nach
SHOW_ALL_CARDS = False     # True: auch Commons/Bulk in der Liste anzeigen
SIMPLE_OVERLAY = False     # True: schlichte Liste statt Karussell+Hitliste
NORMAL_INTERVAL = 0.1      # Pause zwischen Scans
FRAME_FEATURES = 3000      # ORB-Features im Frame (hoch, weil Hintergrund/Terminal
                           # viele Features frisst)
MIN_VOTES = 5              # Vorfilter: FLANN-Votes pro Karte
TOP_CANDIDATES = 5         # So viele Kandidaten werden RANSAC-verifiziert
MIN_INLIERS = 15           # RANSAC-Inlier fuer sofortige sichere Erkennung
PERSIST_MIN_INLIERS = 6    # Schwaechere Treffer akzeptieren, wenn...
PERSIST_SCANS = 5          # ...dieselbe Karte so oft in Folge gewinnt
                           # (hilft bei Holo/Full-Art-Karten mit Reflexionen)
MATCH_CONFIRMATIONS = 1    # RANSAC ist sicher genug -> 1 Treffer reicht
RESCAN_COOLDOWN = 3.0      # Sek. nach Erkennung, bevor dieselbe Stelle neu prueft
DEBUG = True               # Pro Scan eine Diagnosezeile ausgeben
MIN_PRICE_FOR_DISPLAY = 1.0  # Karten ohne Hit-Rarity erst ab diesem Preis anzeigen
MAX_CARDS_DISPLAY = 10     # Wie viele Karten auf der Stream-Seite sichtbar sind

ENERGY_KEYWORDS = ['energie', 'energy']

HTTP_PORT = 8765           # Mini-Webserver fuer OBS/Tablet (statt file://)


# Steuer-Signale aus der App-Oberflaeche (Buttons statt Enter-Taste)
NEW_DISPLAY_EVENT = threading.Event()
RESET_EVENT = threading.Event()

VERSION = "1.5"
UPDATE_INFO_URL = ("https://raw.githubusercontent.com/newXPC/boosterTracker/"
                   "master/version.json")
_update_info = {"remote": None, "zip": None}


def check_update_background():
    """Holt die aktuelle Versionsinfo von GitHub (leise, nicht blockierend)."""
    def _check():
        try:
            import urllib.request
            with urllib.request.urlopen(UPDATE_INFO_URL, timeout=8) as r:
                info = json.load(r)
            _update_info["remote"] = info.get("version")
            _update_info["zip"] = info.get("app_zip")
        except Exception:
            pass
    threading.Thread(target=_check, daemon=True).start()


def run_self_update():
    """Laedt das neue ZIP, tauscht die Dateien per Batch aus, startet neu.

    Die eigene config.json wird gesichert und wiederhergestellt.
    Nur im EXE-Modus sinnvoll (Python-Nutzer machen git pull).
    """
    import subprocess
    import tempfile
    import urllib.request
    import zipfile

    zip_url = _update_info.get("zip")
    if not zip_url or not getattr(sys, "frozen", False):
        return False

    tmp = Path(tempfile.mkdtemp(prefix="tracker_update_"))
    zpath = tmp / "update.zip"
    urllib.request.urlretrieve(zip_url, zpath)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(tmp / "new")
    inner = next(d for d in (tmp / "new").iterdir() if d.is_dir())

    exe = Path(sys.executable)
    install = exe.parent
    bat = tmp / "update.bat"
    # WICHTIG: kein `timeout` (braucht eine Konsole) -> ping als Schlaf-Ersatz.
    # xcopy mit Wiederhol-Schleife, falls die alte EXE noch kurz gesperrt ist.
    # Alles wird in update.log protokolliert (Diagnose bei Problemen).
    bat.write_text(f'''@echo off
set LOG="{install}\\update.log"
echo Update gestartet %date% %time% > %LOG%
ping -n 4 127.0.0.1 >nul
copy /Y "{install}\\config.json" "{tmp}\\config.backup" >> %LOG% 2>&1
set TRIES=0
:copyloop
set /a TRIES+=1
xcopy /E /Y /Q "{inner}\\*" "{install}\\" >> %LOG% 2>&1
if errorlevel 1 (
  if %TRIES% LSS 10 (
    ping -n 3 127.0.0.1 >nul
    goto copyloop
  )
)
copy /Y "{tmp}\\config.backup" "{install}\\config.json" >> %LOG% 2>&1
echo Kopieren fertig nach %TRIES% Versuch(en) >> %LOG%
start "" "{exe}"
echo Neustart ausgeloest %time% >> %LOG%
''', encoding="utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(1)
    os._exit(0)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass  # kein Request-Spam in der Konsole

    def do_GET(self):
        if self.path == '/api/windows':
            body = json.dumps({
                "current": WINDOW_TITLE,
                "windows": list_windows(),
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/api/sets':
            body = json.dumps({
                "current": SET_ID,
                "sets": load_sets_index(),
            }).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/api/version':
            update_ok = (getattr(sys, 'frozen', False)
                         and _update_info["remote"] is not None
                         and _update_info["remote"] != VERSION
                         and _update_info["zip"])
            body = json.dumps({
                "version": VERSION,
                "remote": _update_info["remote"],
                "update": bool(update_ok),
            }).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/new-display':
            NEW_DISPLAY_EVENT.set()
            self.send_response(204); self.end_headers()
        elif self.path == '/api/reset':
            RESET_EVENT.set()
            self.send_response(204); self.end_headers()
        elif self.path == '/api/update':
            self.send_response(204); self.end_headers()
            threading.Thread(target=run_self_update, daemon=True).start()
        elif self.path == '/api/set-set':
            length = int(self.headers.get('Content-Length', 0))
            try:
                data = json.loads(self.rfile.read(length) or b'{}')
                new_id = str(data.get('id') or "")
                if new_id:
                    SET_SWITCH_REQUEST.append(new_id)
                    cfg_path = BOOSTER_DIR / "config.json"
                    cfg = {}
                    if cfg_path.exists():
                        with open(cfg_path, encoding='utf-8') as f:
                            cfg = json.load(f)
                    cfg['set'] = new_id
                    with open(cfg_path, 'w', encoding='utf-8') as f:
                        json.dump(cfg, f, indent=2, ensure_ascii=False)
                self.send_response(204)
            except Exception:
                self.send_response(400)
            self.end_headers()
        elif self.path == '/api/set-window':
            global WINDOW_TITLE
            length = int(self.headers.get('Content-Length', 0))
            try:
                data = json.loads(self.rfile.read(length) or b'{}')
                WINDOW_TITLE = str(data.get('title') or "")
                # dauerhaft in config.json speichern
                cfg_path = BOOSTER_DIR / "config.json"
                cfg = {}
                if cfg_path.exists():
                    with open(cfg_path, encoding='utf-8') as f:
                        cfg = json.load(f)
                cfg['fenster'] = WINDOW_TITLE
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
                print(f"Bildquelle: "
                      f"{'Fenster: ' + WINDOW_TITLE if WINDOW_TITLE else 'Bildschirmbereich'}")
                self.send_response(204)
            except Exception:
                self.send_response(400)
            self.end_headers()
        else:
            self.send_response(404); self.end_headers()


def start_http_server():
    """Serviert den BoosterTracker-Ordner per HTTP.

    Grund: OBS blockiert fetch() auf file:// -> die Seite faellt in einen
    2s-Voll-Reload zurueck und das Karussell resettet staendig. Ueber
    http://localhost laeuft das sanfte Update und die Rotation bleibt fluessig.
    """
    handler = partial(_QuietHandler, directory=str(BOOSTER_DIR))
    try:
        server = ThreadingHTTPServer(('0.0.0.0', HTTP_PORT), handler)
    except OSError:
        return False  # Port belegt -> Server laeuft schon (anderer Scanner)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return True


def load_config():
    """Optionale config.json neben Script/EXE liest einfache Einstellungen."""
    global MONITOR, REGION_PCT, RESET_ON_START, DEBUG
    global SHOW_ALL_CARDS, SIMPLE_OVERLAY, WINDOW_TITLE, SET_ID
    cfg_path = BOOSTER_DIR / "config.json"
    if not cfg_path.exists():
        return
    try:
        with open(cfg_path, encoding='utf-8') as f:
            cfg = json.load(f)
        MONITOR = int(cfg.get('monitor', MONITOR))
        REGION_PCT.update(cfg.get('region_prozent', {}))
        RESET_ON_START = bool(cfg.get('reset_beim_start', RESET_ON_START))
        DEBUG = bool(cfg.get('debug', DEBUG))
        SHOW_ALL_CARDS = bool(cfg.get('alle_karten_anzeigen', SHOW_ALL_CARDS))
        SIMPLE_OVERLAY = bool(cfg.get('einfaches_overlay', SIMPLE_OVERLAY))
        WINDOW_TITLE = str(cfg.get('fenster', WINDOW_TITLE) or "")
        SET_ID = str(cfg.get('set', SET_ID) or "sv10")
        print(f"config.json geladen (Monitor {MONITOR}, Set {SET_ID})")
    except Exception as e:
        print(f"WARNUNG: config.json fehlerhaft ({e}) - nutze Standardwerte")


def load_sets_index():
    """sets.json lokal lesen, sonst von GitHub holen."""
    local = BOOSTER_DIR / "sets.json"
    try:
        with open(local, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        pass
    try:
        import urllib.request
        with urllib.request.urlopen(RAW_BASE + "sets.json", timeout=10) as r:
            data = json.load(r)
        local.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding='utf-8')
        return data
    except Exception:
        return [{"id": "sv10", "name": "Ewige Rivalen", "total": 182}]


def load_set_data(set_id):
    """Set-Datenpaket (Namen, Preise, ORB-Features) laden.

    Lokal aus sets/<id>/app_data.json; fehlt es, einmalig von GitHub
    herunterladen und neben der EXE ablegen.
    """
    path = BOOSTER_DIR / "sets" / set_id / "app_data.json"
    if not path.exists():
        print(f"Set {set_id} nicht lokal - lade von GitHub...")
        import urllib.request
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"{RAW_BASE}sets/{set_id}/app_data.json"
        with urllib.request.urlopen(url, timeout=60) as r:
            path.write_bytes(r.read())
        print("  heruntergeladen")
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def load_price_db():
    """Preis-/Namensdaten des aktiven Sets im render-kompatiblen Format."""
    sets = load_sets_index()
    info = next((s for s in sets if s['id'] == SET_ID), {})
    raw = load_set_data(SET_ID)
    db = {}
    for num, e in raw.items():
        db[num] = {
            'number': num,
            'name': e.get('name', '?'),
            'name_de': e.get('name', '?'),
            'rarity': e.get('rarity', '?'),
            'avg7': e.get('avg7'),
            'set_id': SET_ID,
            'set_name': info.get('name', SET_ID),
            'set_total': info.get('total') or '?',
            'estimate': bool(info.get('estimate')),
        }
    return db


def is_energy_card(card_name):
    name = card_name.lower()
    return any(k in name for k in ENERGY_KEYWORDS)


def build_reference_features():
    """Referenz-Features des aktiven Sets aus dem Datenpaket laden und in
    einen FLANN-LSH-Index packen (keine Bildberechnung noetig).

    Returns: (refs, flann, owner)
      refs:  {num: (kps als Nx2-Array, descriptors als Nx32-Array)}
      flann: trainierter FLANN-Matcher
      owner: Array, das jeden Index-Deskriptor seiner Karte zuordnet
    """
    import base64

    raw = load_set_data(SET_ID)
    refs = {}
    all_des = []
    owner = []   # owner[i] = Kartennummer des i-ten Deskriptor-Blocks

    for num, e in raw.items():
        n = e.get('n', 0)
        if n < 50:
            continue
        des = np.frombuffer(base64.b64decode(e['des']),
                            dtype=np.uint8).reshape(n, 32)
        kps = np.array(e['kps'], dtype=np.float32).reshape(n, 2)
        refs[num] = (kps, des)
        all_des.append(des)
        owner.extend([num] * n)

    # FLANN mit LSH-Index (fuer binaere ORB-Deskriptoren)
    index_params = dict(algorithm=6, table_number=8, key_size=16, multi_probe_level=1)
    flann = cv2.FlannBasedMatcher(index_params, dict(checks=32))
    flann.add([np.vstack(all_des)])
    flann.train()

    return refs, flann, np.array(owner)


def list_windows():
    """Sichtbare Fenster auflisten (fuer die Quellen-Auswahl in der App)."""
    if not WIN32_AVAILABLE:
        return []
    out = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if (title and len(title) > 2
                    and 'Booster-Tracker' not in title      # eigenes Fenster!
                    and 'KartenTracker' not in title        # eigene Prozesse
                    and title not in ('Program Manager', 'Einstellungen')):
                out.append(title)
        return True
    win32gui.EnumWindows(cb, None)
    return out


def _find_window(title_part):
    needle = title_part.lower()
    found = []
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if t and needle in t.lower() and 'Booster-Tracker' not in t:
                found.append(hwnd)
        return True
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def capture_window(title_part):
    """Ein bestimmtes Fenster aufnehmen (auch wenn es verdeckt ist).

    Returns: Graustufen-Array mit CLAHE oder None wenn Fenster fehlt.
    """
    if not WIN32_AVAILABLE:
        return None
    hwnd = _find_window(title_part)
    if not hwnd:
        return None
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w, h = right - left, bottom - top
        if w < 80 or h < 80:
            return None
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, w, h)
        save_dc.SelectObject(bmp)
        # 3 = PW_CLIENTONLY | PW_RENDERFULLCONTENT (auch GPU-Fenster wie Camo)
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
        bits = bmp.GetBitmapBits(True)
        img = np.frombuffer(bits, dtype=np.uint8).reshape((h, w, 4))
        win32gui.DeleteObject(bmp.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)
    except Exception:
        return None


def take_screenshot():
    """Bildquelle holen: gewaehltes Fenster ODER Camo-Bildschirmbereich."""
    if WINDOW_TITLE:
        frame = capture_window(WINDOW_TITLE)
        if frame is not None:
            return frame
        # Fenster nicht gefunden -> Fallback auf Bildschirmbereich
    with mss.MSS() as sct:
        monitor = sct.monitors[MONITOR]
        # Nur die Bildschirmmitte: da zeigt Camo die Karte.
        # Terminal/andere Fenster am Rand werden ignoriert.
        region = {
            'top': monitor['top'] + int(monitor['height'] * REGION_PCT['top']),
            'left': monitor['left'] + int(monitor['width'] * REGION_PCT['left']),
            'width': int(monitor['width'] * REGION_PCT['width']),
            'height': int(monitor['height'] * REGION_PCT['height']),
        }
        shot = sct.grab(region)
        img = np.array(shot)
        gray = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        # CLAHE: verbessert Kontrast bei Reflexionen (Holo-/Full-Art-Karten)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        return clahe.apply(gray)


def identify_card(frame_gray, refs, orb, flann, owner, bf):
    """Frame per FLANN-Voting + RANSAC gegen alle Referenzkarten matchen.

    Returns: (card_number, inliers) oder (None, 0)
    """
    kp_f, des_f = orb.detectAndCompute(frame_gray, None)
    if des_f is None or len(kp_f) < 50:
        return None, 0, None

    # Stufe 1: FLANN-knnMatch gegen den Gesamtindex, Voting pro Karte
    knn = flann.knnMatch(des_f, k=2)
    votes = {}
    for pair in knn:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < 0.75 * n.distance:  # Lowe ratio test
            num = owner[m.trainIdx]
            votes[num] = votes.get(num, 0) + 1

    candidates = sorted(votes.items(), key=lambda kv: kv[1], reverse=True)
    if DEBUG and candidates:
        top3 = ', '.join(f'{n}:{v}' for n, v in candidates[:3])
        print(f'    [debug] votes: {top3}')
    candidates = [(num, v) for num, v in candidates[:TOP_CANDIDATES] if v >= MIN_VOTES]
    if not candidates:
        return None, 0, None

    # Stufe 2: RANSAC-Verifikation der Top-Kandidaten (praezises BF-Matching)
    best_num, best_inliers = None, 0
    for num, _ in candidates:
        kp_r, des_r = refs[num]  # kp_r: Nx2-Koordinaten-Array
        matches = bf.match(des_f, des_r)
        good = [m for m in matches if m.distance < 50]
        if len(good) < 8:
            continue
        src = np.float32([kp_f[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp_r[m.trainIdx] for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
        inliers = int(mask.sum()) if mask is not None else 0
        if inliers > best_inliers:
            best_num, best_inliers = num, inliers

    if DEBUG and best_num:
        status = 'OK' if best_inliers >= MIN_INLIERS else 'schwach'
        print(f'    [debug] RANSAC: {best_num} -> {best_inliers} Inlier ({status})')

    accepted = best_num if best_inliers >= MIN_INLIERS else None
    candidate = best_num if best_inliers >= PERSIST_MIN_INLIERS else None
    return accepted, best_inliers, candidate


def get_rarity_type(rarity_str):
    r = str(rarity_str).lower()
    # Japanische Raritaets-Codes
    jp = str(rarity_str).strip().upper()
    if jp in ('RR',):
        return 'ex'
    if jp in ('AR',):
        return 'IR'
    if jp in ('SR',):
        return 'FA'
    if jp in ('SAR',):
        return 'SAR'
    if jp in ('UR',):
        return 'Gold'
    if 'special' in r and 'illustration' in r:
        return 'SAR'
    if 'illustration' in r:
        return 'IR'
    if 'full art' in r or 'ultra' in r:
        return 'FA'
    if 'gold' in r or 'hyper' in r or 'secret' in r:
        return 'Gold'
    if 'double rare' in r or r.strip() == 'ex':
        return 'ex'
    return None


def render_cards(cards_list, limit=10, highlight_latest=True):
    """Kartenliste als HTML-Bloecke rendern."""
    out = ""
    for i, card in enumerate(cards_list[:limit]):
        latest_class = " latest" if (i == 0 and highlight_latest) else ""
        rarity = card.get('rarity', 'Unknown')
        price = card.get('avg7', 'N/A')
        display_name = card.get('name_de') or card['name']
        set_id = card.get('set_id', 'sv10')
        set_name = card.get('set_name', 'Ewige Rivalen')
        set_total = card.get('set_total', 182)
        est = ' (Sch&auml;tzwert)' if card.get('estimate') else ''
        # sv10-Bilder liegen im alten Ordner, andere Sets unter sets/<id>/images
        img_src = (f"sv10_cards_images/{card['number']}.png" if set_id == 'sv10'
                   else f"sets/{set_id}/images/{card['number']}.png")
        out += f"""<div class="card{latest_class}">
  <img class="thumb" src="{img_src}" alt="" onerror="this.style.display='none'">
  <div class="info">
    <p class="name">{display_name}</p>
    <p class="set">{set_name} &middot; {card['number']}/{set_total}</p>
    <div class="row">
      <span class="chip">{rarity}</span>
      <span class="price">~{price} &euro;{est}</span>
    </div>
  </div>
</div>
"""
    return out


def build_archive_section(display_num, cards_list, counters):
    """Abgeschlossenes Display als zusammenklappbaren Abschnitt rendern."""
    total = sum(c.get('avg7') or 0 for c in cards_list
                if isinstance(c.get('avg7'), (int, float)))
    total_str = f"{total:.2f}".replace('.', ',')
    stats = ' &middot; '.join(f"{v}&times;{k}" for k, v in counters.items() if v > 0) or "keine Hits"
    cards_html = render_cards(cards_list, limit=100, highlight_latest=False)
    return f"""<details class="display-old">
  <summary>
    <span class="d-name">Display {display_num}</span>
    <span class="d-stats">{len(cards_list)} Hits &middot; {stats} &middot; ~{total_str} &euro;</span>
  </summary>
{cards_html}</details>
"""


def update_html(cards_list, counters, display_num=1, archived_html="",
                stream_total=0.0):
    if not HTML_FILE.exists():
        return

    if SIMPLE_OVERLAY:
        # Schlichte Liste: neueste Karte gross oben, Rest normal darunter
        cards_html = render_cards(cards_list, limit=30)
        if not cards_html:
            cards_html = '<p class="empty">Noch keine Karten erkannt</p>\n'
    else:
        # Karussell + Hit-Alert: nur Premium-Hits (IR/FA/Gold/SAR, KEIN ex).
        # ex-Karten erscheinen nur in der Liste unten und im Zaehler.
        premium = [c for c in cards_list
                   if get_rarity_type(c.get('rarity', '')) in ('IR', 'FA', 'Gold', 'SAR')]
        carousel_inner = render_cards(premium, limit=MAX_CARDS_DISPLAY)
        if not carousel_inner:
            carousel_inner = '<p class="empty">Noch keine Top-Hits in diesem Display</p>\n'
        if cards_list:
            # Unter dem Karussell: alle Hits als feste Liste (zum Zeigen/Scrollen)
            hitlist = ('<div id="hitlist">\n'
                       + render_cards(cards_list, limit=MAX_CARDS_DISPLAY,
                                      highlight_latest=False)
                       + '</div>\n')
        else:
            hitlist = ''
        # Karussell-Container: die Seite rotiert die Karten selbst durch
        cards_html = f'<div id="carousel">\n{carousel_inner}</div>\n{hitlist}'

    counters_html = f"""<div class="counter c-ex"><div class="num">{counters['ex']}</div><div class="lbl">ex</div></div>
  <div class="counter c-ir"><div class="num">{counters['IR']}</div><div class="lbl">IR</div></div>
  <div class="counter c-fa"><div class="num">{counters['FA']}</div><div class="lbl">FA</div></div>
  <div class="counter c-gold"><div class="num">{counters['Gold']}</div><div class="lbl">Gold</div></div>
  <div class="counter c-sar"><div class="num">{counters['SAR']}</div><div class="lbl">SAR</div></div>"""

    with open(HTML_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    # Kopfzeile: Name des aktiven Sets
    sets = load_sets_index()
    set_name = next((s['name'] for s in sets if s['id'] == SET_ID), SET_ID)
    html = re.sub(
        r'<span class="live-dot">.*?</span>',
        f'<span class="live-dot">{set_name} &middot; bereit</span>',
        html, flags=re.DOTALL
    )

    html = re.sub(
        r'<div class="counters">.*?</div>\n</div>|<div class="counters">.*?</div>',
        f'<div class="counters">\n  {counters_html}\n</div>',
        html, count=1, flags=re.DOTALL
    )
    total_str = f"{stream_total:.2f}".replace('.', ',')
    html = re.sub(
        r'<p class="stream-total">.*?</p>',
        f'<p class="stream-total">Heute gezogen: <b>{total_str} &euro;</b></p>',
        html, flags=re.DOTALL
    )
    html = re.sub(
        r'<p class="display-label">.*?(?=<footer>)',
        f'<p class="display-label">Display {display_num} &middot; aktuell</p>\n\n'
        f'{cards_html}\n{archived_html}',
        html, flags=re.DOTALL
    )

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def update_html_all(cards_all):
    """Zweite Seite: komplette Liste ALLER gezogenen Karten (inkl. Commons)."""
    if not HTML_ALL_FILE.exists():
        return

    total = 0.0
    rows = ""
    for card in cards_all:  # neueste zuerst
        name = card.get('name_de') or card['name']
        rarity = card.get('rarity', '?')
        price = card.get('avg7')
        hit_class = ' class="hit"' if get_rarity_type(rarity) else ''
        if isinstance(price, (int, float)):
            total += price
            price_str = f"{price:.2f}".replace('.', ',') + " &euro;"
        else:
            price_str = "?"
        rows += (f'<tr{hit_class}><td class="num">{card["number"]}/182</td>'
                 f'<td>{name}</td><td>{rarity}</td>'
                 f'<td class="price">{price_str}</td></tr>\n')

    if not rows:
        rows = '<tr><td colspan="4" class="empty">Noch keine Karten erkannt</td></tr>'

    total_str = f"{total:.2f}".replace('.', ',')

    with open(HTML_ALL_FILE, 'r', encoding='utf-8') as f:
        html = f.read()

    html = re.sub(
        r'<div class="stats">.*?(?=<table)',
        f'''<div class="stats">
  <div class="stat"><div class="num">{len(cards_all)}</div><div class="lbl">Karten</div></div>
  <div class="stat"><div class="num">{total_str} &euro;</div><div class="lbl">Gesamtwert</div></div>
</div>

''',
        html, flags=re.DOTALL
    )
    html = re.sub(
        r'<tbody>.*?</tbody>',
        f'<tbody>\n{rows}</tbody>',
        html, flags=re.DOTALL
    )

    with open(HTML_ALL_FILE, 'w', encoding='utf-8') as f:
        f.write(html)


def main():
    print("=" * 60)
    print("BOOSTER TRACKER v4 - ORB + RANSAC")
    print("=" * 60)

    load_config()
    global SET_ID
    check_update_background()
    if RESET_ON_START:
        update_html([], {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}, 1, '', 0.0)
        update_html_all([])
        print("Seiten auf null gesetzt")

    start_http_server()
    print(f"Tracker-Seite:  http://localhost:{HTTP_PORT}/booster-tracker.html")
    print(f"Alle Karten:    http://localhost:{HTTP_PORT}/booster-tracker-alle.html")
    print(">> Diese URL in OBS als Browser-Quelle eintragen (statt lokale Datei!) <<")

    price_db = load_price_db()
    print(f"Preisdatenbank: {len(price_db)} Karten")

    print("Berechne Referenz-Features und FLANN-Index (einmalig)...")
    refs, flann, owner = build_reference_features()
    print(f"Referenz-Features: {len(refs)} Karten")
    print("Warte auf Karten...")
    print(">> ENTER druecken = neues Display starten (dieses Fenster muss Fokus haben) <<\n")

    orb = cv2.ORB_create(nfeatures=FRAME_FEATURES)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)

    cards_list = []
    counters = {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}
    seen_cards = set()

    display_num = 1
    archived_html = ""
    stream_total = 0.0  # Wert ALLER erkannten Karten (auch Bulk), ganzer Stream

    pending_num = None
    pending_count = 0
    last_detect_time = 0
    weak_num = None
    weak_count = 0

    try:
        while True:
            ts = datetime.now().strftime("%H:%M:%S")

            # ENTER im Terminal ODER App-Button = neues Display starten
            enter_pressed = False
            try:
                if msvcrt and msvcrt.kbhit() and msvcrt.getwch() == '\r':
                    enter_pressed = True
            except Exception:
                pass  # keine Konsole (App-Modus)
            if enter_pressed or NEW_DISPLAY_EVENT.is_set():
                NEW_DISPLAY_EVENT.clear()
                archived_html = build_archive_section(
                    display_num, cards_list, counters) + archived_html
                display_num += 1
                cards_list = []
                counters = {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}
                seen_cards = set()
                pending_num, pending_count = None, 0
                weak_num, weak_count = None, 0
                update_html(cards_list, counters, display_num, archived_html,
                            stream_total)
                print(f"\n[{ts}] ===== NEUES DISPLAY: Display {display_num} =====\n")

            # App-Button "Reset": alles auf null
            if RESET_EVENT.is_set():
                RESET_EVENT.clear()
                display_num = 1
                archived_html = ""
                stream_total = 0.0
                cards_list = []
                counters = {'ex': 0, 'IR': 0, 'FA': 0, 'Gold': 0, 'SAR': 0}
                seen_cards = set()
                pending_num, pending_count = None, 0
                weak_num, weak_count = None, 0
                update_html(cards_list, counters, 1, '', 0.0)
                update_html_all([])
                print(f"\n[{ts}] ===== RESET =====\n")

            # App-Auswahl: anderes Set laden (live, ohne Neustart)
            if SET_SWITCH_REQUEST:
                new_id = SET_SWITCH_REQUEST.pop()
                SET_SWITCH_REQUEST.clear()
                if new_id != SET_ID:
                    SET_ID = new_id
                    print(f"\n[{ts}] Wechsle Set auf {new_id}...")
                    try:
                        price_db = load_price_db()
                        refs, flann, owner = build_reference_features()
                        pending_num, pending_count = None, 0
                        weak_num, weak_count = None, 0
                        seen_cards = set()
                        update_html(cards_list, counters, display_num,
                                    archived_html, stream_total)
                        print(f"[{ts}] Set aktiv: {new_id} "
                              f"({len(refs)} Karten)\n")
                    except Exception as e:
                        print(f"[{ts}] Set-Wechsel fehlgeschlagen: {e}\n")

            frame = take_screenshot()

            num, inliers, candidate = identify_card(frame, refs, orb, flann, owner, bf)

            # Beharrlichkeit: schwacher Kandidat gewinnt PERSIST_SCANS mal in
            # Folge (Holo-Reflexionen) -> trotzdem akzeptieren
            if num is None and candidate is not None:
                if candidate == weak_num:
                    weak_count += 1
                else:
                    weak_num, weak_count = candidate, 1
                if weak_count >= PERSIST_SCANS:
                    num = candidate
                    weak_num, weak_count = None, 0  # zuruecksetzen gegen Log-Spam
                    if DEBUG:
                        print(f'    [debug] {candidate} akzeptiert nach '
                              f'{PERSIST_SCANS} konsistenten Scans')
            elif candidate is None:
                weak_num, weak_count = None, 0

            if num:
                if num == pending_num:
                    pending_count += 1
                else:
                    pending_num, pending_count = num, 1

                if pending_count == MATCH_CONFIRMATIONS:
                    if num in seen_cards:
                        # Schon gezaehlt -> nur kurz melden, nicht doppeln
                        if time.time() - last_detect_time > RESCAN_COOLDOWN:
                            print(f"[{ts}] {num} bereits erfasst (skip)")
                            last_detect_time = time.time()
                    else:
                        card_data = price_db.get(num)
                        if card_data:
                            name = card_data.get('name_de') or card_data.get('name', '?')
                            if is_energy_card(name):
                                print(f"[{ts}] Energie -> skip ({name})")
                                seen_cards.add(num)
                            else:
                                seen_cards.add(num)
                                rt = get_rarity_type(card_data.get('rarity', ''))
                                price = card_data.get('avg7') or 0
                                if isinstance(price, (int, float)):
                                    stream_total += price

                                # Nur Hits anzeigen: ex/FA/IR/SAR/Gold oder teuer
                                # (oder alles, wenn per Config gewuenscht)
                                is_hit = SHOW_ALL_CARDS or rt is not None or (
                                    isinstance(price, (int, float))
                                    and price >= MIN_PRICE_FOR_DISPLAY
                                )
                                if is_hit:
                                    cards_list.insert(0, card_data)
                                    if rt:
                                        counters[rt] += 1
                                    update_html(cards_list, counters,
                                                display_num, archived_html,
                                                stream_total)
                                    print(f"[{ts}] HIT: {num} {name} "
                                          f"(~{price} EUR, {inliers} Inlier)")
                                else:
                                    # Ticker trotzdem aktualisieren
                                    update_html(cards_list, counters,
                                                display_num, archived_html,
                                                stream_total)
                                    print(f"[{ts}] Bulk -> nicht angezeigt: "
                                          f"{num} {name} (~{price} EUR)")
                                last_detect_time = time.time()
            else:
                pending_num, pending_count = None, 0

            time.sleep(NORMAL_INTERVAL)

    except KeyboardInterrupt:
        print(f"\nGestoppt. {len(seen_cards)} Karten erkannt.")
        print(f"SAR: {counters['SAR']}, IR: {counters['IR']}, FA: {counters['FA']}, "
              f"Gold: {counters['Gold']}, ex: {counters['ex']}")


if __name__ == '__main__':
    main()
