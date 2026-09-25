"""Keeping a copy of the shop's data.

A backup button that somebody has to remember to press is not a backup. It gets
pressed for the first week and never again, and the shop finds out on the day
the disk dies that the last copy is four months old.

So the system takes one by itself, once a day, and keeps nagging until a copy
has been put somewhere that is not this computer. A backup sitting on the same
disk as the database protects against a mistake, never against a theft, a
power surge, or a disk that simply stops.
"""
import shutil
import sqlite3
import string
from pathlib import Path

from django.conf import settings
from django.utils import timezone

KEEP_BACKUPS = 30


def backup_dir():
    path = Path(settings.BACKUP_DIR)
    path.mkdir(exist_ok=True)
    return path


def database_path():
    return Path(settings.DATABASES["default"]["NAME"])


def backup_database(reason="manual", source=None):
    """Take a consistent copy of the database while the shop keeps trading.

    NOT a file copy. The database runs in WAL mode so that one till saving a
    sale never freezes another, and in WAL mode the newest committed sales may
    still be sitting in db.sqlite3-wal rather than in db.sqlite3 itself.
    Copying the one file silently produces a backup missing the morning's
    takings, and nobody finds out until the day they need it. SQLite's own
    backup API copies everything, including what is still in the WAL.

    Do not "simplify" this to shutil.copy2. That bug has already been found
    and fixed once.
    """
    stamp = timezone.localtime().strftime("%Y-%m-%d_%H%M%S")
    target = backup_dir() / f"backup_{stamp}.sqlite3"

    source = sqlite3.connect(Path(source) if source else database_path())
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    prune_backups()
    return target


def list_backups():
    return sorted(backup_dir().glob("*.sqlite3"), reverse=True)


def latest_backup():
    backups = list_backups()
    return backups[0] if backups else None


def prune_backups(keep=KEEP_BACKUPS):
    """Keep the most recent ones. A shop PC has a small disk and a year of
    daily copies will quietly fill it, which breaks the till itself."""
    removed = []
    for old in list_backups()[keep:]:
        try:
            old.unlink()
            removed.append(old.name)
        except OSError:
            pass
    return removed


def last_backup_age_days():
    """Whole days since the last backup. None if there has never been one.

    Floored at zero deliberately. A file written a fraction of a second ago can
    carry a timestamp a hair AHEAD of the clock, and a negative timedelta floors
    to -1 in Python - so a backup just taken would announce itself as "-1 days
    ago" on the owner's screen.
    """
    latest = latest_backup()
    if latest is None:
        return None
    when = timezone.datetime.fromtimestamp(latest.stat().st_mtime)
    seconds = (timezone.datetime.now() - when).total_seconds()
    return max(0, int(seconds // 86400))


def auto_backup_if_due():
    """Take today's copy if it has not been taken yet.

    Called when the owner opens the dashboard rather than from a background
    thread: the shop's computer is switched off at night and on again in the
    morning, so "when somebody first uses it today" is both simpler and more
    reliable than any schedule.
    """
    today = timezone.localdate()
    latest = latest_backup()
    if latest is not None:
        when = timezone.datetime.fromtimestamp(latest.stat().st_mtime).date()
        if when >= today:
            return None
    return backup_database(reason="automatic")


# ---------------------------------------------------------------------------
# Getting a copy off this computer
# ---------------------------------------------------------------------------
def removable_drives():
    """Drive letters that look like a flash disk.

    Deliberately crude: anything that is not C: and can be written to. Asking
    Windows properly would mean a dependency the offline install does not have,
    and the person doing this is standing at the counter and knows perfectly
    well which letter their flash disk is.
    """
    drives = []
    for letter in string.ascii_uppercase:
        if letter == "C":
            continue
        root = Path(f"{letter}:/")
        try:
            if root.exists() and root.is_dir():
                drives.append(root)
        except OSError:
            continue
    return drives


def copy_backup_to(drive, backup=None):
    """Copy the newest backup onto a flash disk, into its own folder.

    A plain file copy is right here - the backup file is already a finished,
    consistent snapshot and nothing is writing to it.
    """
    backup = Path(backup) if backup else latest_backup()
    if backup is None:
        raise FileNotFoundError("There is no backup to copy yet.")

    folder = Path(drive) / "MAQAM BACKUPS"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / backup.name
    shutil.copy2(backup, target)
    return target
