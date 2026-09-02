#!/usr/bin/env python3
"""
Karten-Tracker als eigenstaendige Fenster-App.

Startet den Scanner unsichtbar im Hintergrund und zeigt das Overlay in
einem eigenen Programmfenster (kein CMD, kein Browser noetig).
Buttons im Fenster: "Neues Display" und "Alles zuruecksetzen".

OBS kann weiterhin parallel http://localhost:8765/booster-tracker.html
als Browser-Quelle nutzen (ohne Buttons).
"""

import threading
import time
import urllib.request

import webview  # pywebview

import stream_monitor_v4 as scanner

URL = f"http://localhost:{scanner.HTTP_PORT}/booster-tracker.html?app=1"


def run_scanner():
    try:
        scanner.main()
    except Exception as e:
        # Fehler in Datei neben der EXE schreiben (kein Konsolenfenster da)
        try:
            with open(scanner.BOOSTER_DIR / "fehler.log", "w", encoding="utf-8") as f:
                import traceback
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


def main():
    t = threading.Thread(target=run_scanner, daemon=True)
    t.start()
    wait_for_server()
    webview.create_window(
        "Karten-Tracker", URL,
        width=620, height=900,
        background_color="#101418",
    )
    webview.start()


if __name__ == "__main__":
    main()
