"""Bring the shop computer's data up to the online server.

    python manage.py import_shop_db /home/maqam/incoming.sqlite3 --check
    python manage.py import_shop_db /home/maqam/incoming.sqlite3

The file is a backup taken on the shop's own computer (Backup screen ->
"Take a backup now" -> download), copied up to the server. --check only reads
it and prints what is inside: how many products and receipts, the last sale,
and every login. Read that summary BEFORE the real run - it is the only chance
to notice that the file is last month's, or from the wrong computer.

Without --check it:
  1. refuses a file that is damaged, is not this system's database, or was
     made by NEWER code than the server is running;
  2. takes a backup of whatever the server holds now, so this can be undone;
  3. copies the file in through SQLite's own backup API (not a file copy -
     see shop/services.backup_database for why that matters under WAL);
  4. brings it up to date with migrate, and signs every old session out.

Stop the service first (DEPLOY-ONLINE.md does) so no till writes a sale into
the database while it is being replaced.
"""
import sqlite3
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from shop import services

REQUIRED_TABLES = {"django_migrations", "shop_user", "shop_shopsettings",
                   "inventory_product", "sales_sale"}


class Command(BaseCommand):
    help = "Replace the server's database with a backup from the shop computer."

    def add_arguments(self, parser):
        parser.add_argument("path", help="The .sqlite3 backup file from the shop computer.")
        parser.add_argument("--check", action="store_true",
                            help="Only read the file and print what is in it.")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.is_file():
            raise CommandError(f"There is no file at {path}.")

        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            self._validate(source)
            self._summarise(source)
            if options["check"]:
                self.stdout.write(self.style.SUCCESS(
                    "\nThe file is sound. Nothing has been changed. If the figures "
                    "above are what you expect, run the same command without --check."))
                return

            target = services.database_path()
            if target.exists():
                connection.close()
                safety = services.backup_database(reason="before-import")
                self.stdout.write(f"\nThe server's previous data is kept in {safety}")

            connection.close()
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()

        call_command("migrate", interactive=False, verbosity=0)
        with connection.cursor() as cursor:
            # Sessions from the shop's own network mean nothing here.
            cursor.execute("DELETE FROM django_session")
        self.stdout.write(self.style.SUCCESS(
            "\nImported. The online system now holds the shop's data. Run setup_maqam "
            "with --close-spare-admin next (see DEPLOY-ONLINE.md)."))

    # -- checks ---------------------------------------------------------
    def _validate(self, db):
        ok = db.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise CommandError(f"The file is damaged ({ok}). Take a fresh backup on the "
                               "shop computer and copy it again.")
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = REQUIRED_TABLES - tables
        if missing:
            raise CommandError("This is not the supermarket system's database "
                               f"(no {', '.join(sorted(missing))}).")

        known = set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
        applied = set(db.execute("SELECT app, name FROM django_migrations").fetchall())
        ours = {(app, name) for app, name in applied
                if app in {"shop", "inventory", "sales", "reports"}}
        newer = sorted(f"{a}.{n}" for a, n in ours - known)
        if newer:
            raise CommandError(
                "This file was made by NEWER code than the server is running "
                f"({', '.join(newer)}). Update the server first (git pull), then import.")

    def _summarise(self, db):
        def one(sql):
            return db.execute(sql).fetchone()[0]

        name = one("SELECT company_name FROM shop_shopsettings LIMIT 1") or "(no name)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{name}"))
        self.stdout.write(f"  Products:        {one('SELECT COUNT(*) FROM inventory_product')}"
                          f" ({one('SELECT COUNT(*) FROM inventory_product WHERE is_active=1')} for sale)")
        self.stdout.write(f"  Receipts:        {one('SELECT COUNT(*) FROM sales_sale')}")
        last = one("SELECT MAX(created_at) FROM sales_sale")
        self.stdout.write(f"  Last sale (UTC): {last or 'none yet'}")
        total = one("SELECT COALESCE(SUM(total),0) FROM sales_sale WHERE status='COMPLETED'")
        self.stdout.write(f"  All-time sales:  UGX {float(total):,.0f}")
        self.stdout.write("  Logins:")
        for username, role, active, superuser in db.execute(
                "SELECT username, role, is_active, is_superuser FROM shop_user ORDER BY username"):
            flag = "" if active else "  (switched off)"
            boss = " superuser" if superuser else ""
            self.stdout.write(f"    {username:<20} {role}{boss}{flag}")
