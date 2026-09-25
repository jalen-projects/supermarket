"""Take a backup from the command line.

This is what Windows Task Scheduler runs, and what the desktop shortcut
BACKUP NOW.bat calls. Having it as a command rather than only a button means a
copy can be taken when nobody is logged in - at closing time, for instance.
"""
from django.core.management.base import BaseCommand

from shop import services


class Command(BaseCommand):
    help = "Take a safe copy of the shop's database, optionally onto a flash disk."

    def add_arguments(self, parser):
        parser.add_argument(
            "--to", dest="drive", default=None,
            help="Also copy it to this drive, e.g. --to E:")
        parser.add_argument(
            "--keep", type=int, default=services.KEEP_BACKUPS,
            help="How many backups to keep on this computer.")

    def handle(self, *args, **options):
        target = services.backup_database(reason="command")
        services.prune_backups(keep=options["keep"])
        self.stdout.write(self.style.SUCCESS(f"Backup saved: {target}"))

        drive = options["drive"]
        if drive:
            try:
                copied = services.copy_backup_to(drive, target)
            except (OSError, FileNotFoundError) as exc:
                self.stderr.write(self.style.ERROR(
                    f"Could not copy to {drive}: {exc}"))
                return
            self.stdout.write(self.style.SUCCESS(f"Copied to: {copied}"))
        else:
            self.stdout.write(
                "Now copy that file to a flash disk. A backup on this same "
                "computer does not survive a theft or a dead disk.")
