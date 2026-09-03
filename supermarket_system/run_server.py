"""Starts the supermarket system and opens it in the browser.

This is what the desktop shortcut runs. It uses waitress rather than Django's
development server, because this one is left running all day in a real shop.

Nothing here touches the internet. The server listens on the shop's own
machine, and on the shop's local network, so a second or third till is just
another computer opening a browser at the address printed below - nothing is
installed on those machines and they share this one set of books.
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


def local_ips():
    """Every address other computers on the shop's network could use.

    A shop PC is often on a cable and wi-fi at the same time, and only one of
    those is the network the second till is on. Printing just one address sends
    somebody chasing the wrong number.
    """
    found = []

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            found.append(s.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass

    return found or ["127.0.0.1"]


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

    addresses = local_ips()

    print("=" * 66)
    print("  SUPERMARKET MANAGEMENT SYSTEM")
    print("=" * 66)
    print(f"  On this computer:    http://127.0.0.1:{PORT}/")
    print()
    print("  From another till, type this into the browser's address bar:")
    for i, ip in enumerate(addresses):
        marker = "  <-- try this one first" if i == 0 and len(addresses) > 1 else ""
        print(f"                       http://{ip}:{PORT}/{marker}")
    print()
    print("  If another till cannot open it, run ALLOW OTHER TILLS.bat on")
    print("  THIS computer once, as administrator. Windows Firewall blocks it")
    print("  until you do.")
    print()
    print("  Keep this window open while the shop is trading.")
    print("  Closing it shuts the system down - on every till.")
    print("=" * 66)

    # More threads than before: each till holds a connection, and a browser
    # opens several at once for the page and its stylesheet. Eight was fine for
    # a single machine and gets tight the moment a second and third till and
    # the office are all open.
    threading.Thread(target=open_browser, daemon=True).start()
    serve(application, host="0.0.0.0", port=PORT, threads=16, _quiet=True)


if __name__ == "__main__":
    main()
