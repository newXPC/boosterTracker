#!/usr/bin/env python3
"""
Karten-Tracker als eigenstaendige Fenster-App.

Startet den Scanner unsichtbar im Hintergrund und zeigt das Overlay in
einem eigenen Programmfenster (Edge/Chrome App-Modus - auf jedem
Windows 10/11 vorhanden, keine Zusatzkomponenten).

Fenster schliessen beendet auch den Scanner.
"""

import subprocess
import threading
import time
import traceback
import urllib.request
import webbrowser
from pathlib import Path

import stream_monitor_v4 as scanner

URL = f"http://localhost:{scanner.HTTP_PORT}/booster-tracker.html?app=1"


def run_scanner():
    try:
        scanner.main()
    except Exception:
        try:
            with open(scanner.BOOSTER_DIR / "fehler.log", "w", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass


def wait_for_server(timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(URL, timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def find_browser():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None


def main():
    t = threading.Thread(target=run_scanner, daemon=True)
    t.start()
    wait_for_server()

    browser = find_browser()
    if browser:
        # Pro Start ein FRISCHES Profilverzeichnis: erzwingt einen eigenen
        # Edge-Prozess (kein Singleton-Handoff), der zuverlaessig blockiert,
        # bis das Fenster geschlossen wird (= App-Lebensdauer).
        import os as _os
        import shutil
        base = scanner.BOOSTER_DIR / ".appwindow"
        # alte Profile aufraeumen
        for old in scanner.BOOSTER_DIR.glob(".appwindow*"):
            shutil.rmtree(old, ignore_errors=True)
        profile = Path(f"{base}-{_os.getpid()}")
        subprocess.run([
            browser,
            f"--app={URL}",
            f"--user-data-dir={profile}",
            "--window-size=620,900",
            "--no-first-run",
            "--no-default-browser-check",
        ])
        shutil.rmtree(profile, ignore_errors=True)
    else:
        # Fallback: normaler Browser-Tab, App laeuft bis Strg+C
        webbrowser.open(URL)
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
