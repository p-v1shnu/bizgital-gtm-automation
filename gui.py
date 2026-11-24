#!/usr/bin/env python3
"""Open the local web UI for GTM container provisioning.

Usage:
    python gui.py
    python gui.py --port 9000 --no-browser

The server listens on 127.0.0.1 only. Close the window (or press Ctrl+C) to
stop it.
"""

import argparse
import sys
import threading
import webbrowser

from gtm_provisioner.webapp import DEFAULT_PORT, create_server


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local web UI for provision_gtm.py")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = parser.parse_args(argv)

    # Thai text must not crash the launcher when the console or a redirected
    # stream is not UTF-8 (e.g. cp1252).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    server, _ = create_server(args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"เปิดหน้าเว็บที่ {url}", flush=True)
    print("กด Ctrl+C หรือปิดหน้าต่างนี้เพื่อหยุดโปรแกรม", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nหยุดโปรแกรมแล้ว")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
