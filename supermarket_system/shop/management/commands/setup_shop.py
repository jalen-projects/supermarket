"""First-run setup: create the owner's login and the basic reference data.

Run once after installing:  python manage.py setup_shop
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.models import Category, Unit
from shop.models import ShopSettings, User

UNITS = [
    ("Piece", "pc", False),
    ("Kilogram", "kg", True),
    ("Gram", "g", True),
    ("Litre", "L", True),
    ("Millilitre", "ml", True),
    ("Packet", "pkt", False),
    ("Box", "box", False),
    ("Crate", "crate", False),
    ("Carton", "ctn", False),
    ("Bunch", "bunch", False),
    ("Bale", "bale", False),
    ("Tray", "tray", False),
]

CATEGORIES = [
    ("Beverages", "Sodas, juices, water, energy drinks"),
    ("Cereals & grains", "Rice, maize flour, posho, beans"),
    ("Cooking essentials", "Cooking oil, salt, sugar, spices"),
    ("Bakery", "Bread, cakes, buns"),
    ("Dairy & eggs", "Milk, yoghurt, butter, eggs"),
    ("Snacks & confectionery", "Biscuits, sweets, crisps"),
    ("Soap & detergents", "Bar soap, washing powder, bleach"),
    ("Toiletries", "Toothpaste, tissue, sanitary items"),
    ("Household", "Brooms, basins, matches, candles"),
    ("Baby products", "Nappies, baby food, wipes"),
    ("Fresh produce", "Fruits and vegetables"),
    ("Meat & frozen", "Meat, chicken, fish, frozen goods"),
]


class Command(BaseCommand):
    help = "Set up the shop for the first time: owner login, units and categories."

    def add_arguments(self, parser):
        parser.add_argument("--company", default=None, help="The supermarket's name")
        parser.add_argument("--username", default="admin")
        parser.add_argument("--password", default=None)
        parser.add_argument("--name", default="Shop Owner", help="Owner's full name")

    @transaction.atomic
    def handle(self, *args, **options):
        settings_obj = ShopSettings.get()
        if options["company"]:
            settings_obj.company_name = options["company"]
            settings_obj.save()
            self.stdout.write(f"Shop name set to {settings_obj.company_name}")

        created_units = 0
        for name, abbr, decimals in UNITS:
            _, made = Unit.objects.get_or_create(
                name=name, defaults={"abbreviation": abbr, "allow_decimals": decimals})
            created_units += made
        self.stdout.write(f"Measurements: {created_units} added, "
                          f"{Unit.objects.count()} in total")

        created_cats = 0
        for name, description in CATEGORIES:
            _, made = Category.objects.get_or_create(
                name=name, defaults={"description": description})
            created_cats += made
        self.stdout.write(f"Categories: {created_cats} added, "
                          f"{Category.objects.count()} in total")

        username = options["username"]
        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING(
                f"User '{username}' already exists - password left unchanged."))
            return

        password = options["password"]
        if not password:
            password = "admin1234"
            self.stdout.write(self.style.WARNING(
                "No password given, so 'admin1234' was used. "
                "CHANGE IT under Users as soon as you sign in."))

        parts = options["name"].split(" ", 1)
        User.objects.create_superuser(
            username=username, password=password, role=User.Role.ADMIN,
            first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "")
        self.stdout.write(self.style.SUCCESS(
            f"Owner login created: username '{username}'."))
