"""Starts the supermarket system and opens it in the browser.

This is what the desktop shortcut runs. It uses waitress rather than Django's
development server, because this one is left running all day in a real shop.

Nothing here touches the internet. The server listens on the shop's own
machine, and on the shop's local network so a second till can be added later
without reinstalling anything.
"""
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smms.settings")

PORT = int(os.environ.get("SMMS_PORT", "8000"))


def local_ip():
    """The address other computers on the shop's network would use."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def open_browser():
    time.sleep(1.5)
    webbrowser.open(f"http://127.0.0.1:{PORT}/")


def main():
    import django

    django.setup()

    from django.core.management import call_command

    # Apply any pending migrations quietly, so an update never leaves the
    # shopkeeper staring at an error they cannot read.
    call_command("migrate", interactive=False, verbosity=0)
    call_command("collectstatic", interactive=False, verbosity=0)

    from waitress import serve

    from smms.wsgi import application

    print("=" * 62)
    print("  SUPERMARKET MANAGEMENT SYSTEM")
    print("=" * 62)
    print(f"  On this computer:      http://127.0.0.1:{PORT}/")
    print(f"  From another till:     http://{local_ip()}:{PORT}/")
    print()
    print("  Keep this window open while the shop is trading.")
    print("  Closing it shuts the system down.")
    print("=" * 62)

    threading.Thread(target=open_browser, daemon=True).start()
    serve(application, host="0.0.0.0", port=PORT, threads=8, _quiet=True)


if __name__ == "__main__":
    main()
