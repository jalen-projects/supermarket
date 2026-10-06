"""Fills the DEMONSTRATION shop - FreshWay Supermarket, Nakawa - with a
believable month of trading, for showing the system to other shops.

    python manage.py seed_demo_shop            # safe to run again
    python manage.py seed_demo_shop --reset    # wipe the trading and start a fresh month

WHAT IT MAKES: about 150 products a Kampala supermarket really stocks, with
categories, units (loose goods sold by the kilo), unique barcodes, buying and
selling prices in UGX and suppliers; an opening stock take and four
deliveries, plus one delivery waiting to be received; stock close to its
expiry date, stock already past it, and shelves running low; regular and
credit customers; thirty days of sales by three cashiers in cash, mobile
money, card and credit, a few of them voided; and a cash-up for every drawer,
one of them short and one over. TODAY is left empty: the sales on it are the
ones whoever is testing rings up, so they can follow their own money from the
till to the cash-up and the reports without invented sales in the way.

RUNNING IT AGAIN changes nothing that is already there. It re-applies the
shop's name and logo and puts every demo login back to the demo password (a
visitor may have changed one), and it only creates the products, customers
and trading history if they are missing. --reset is the way to throw away
what visitors have rung up and start a fresh thirty days ending today.

IT REFUSES TO RUN ANYWHERE BUT THE DEMO (SMMS_DEMO=1). It invents sales, and
on a real shop's database invented sales would be indistinguishable from his
real takings.

The password for every demo login comes from DEMO_PASSWORD in the server's
settings file, never from this file: the repository is public.
"""
import os
import random
import shutil
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from inventory.models import (Category, Product, Purchase, PurchaseItem, StockBatch,
                              StockCount, StockCountLine, StockMovement, Supplier, Unit)
from sales.models import (Customer, HeldSale, InsufficientStock, Sale, SaleItem,
                          SaleItemBatch, Shift)
from sales.services import adjust_stock, apply_stock_count, receive_purchase, record_sale
from shop import audit
from shop.management.commands.setup_shop import CATEGORIES, UNITS
from shop.models import AuditEvent, ShopSettings, Till, TillGap, User

COMPANY = "FreshWay Supermarket"
TAGLINE = "Fresh every morning, fair every day"
ADDRESS = "Jinja Road, Nakawa, Kampala"
PHONE = "0414 000 000"
EMAIL = "hello@freshway.example"
FOOTER = "Thank you for shopping at FreshWay. See you tomorrow!"
LOGO_SOURCE = "brand/freshway/freshway-logo.png"   # inside static/
LOGO_TARGET = "shop/freshway-logo.png"             # inside media/

# username, first, last, role, Django-admin access, phone. Nobody gets the
# Django admin (/admin/) on a demo whose password is handed to strangers:
# the owner's role is what shows him costs and profit, not that switch.
PEOPLE = [
    ("owner", "Sarah", "Nakato", User.Role.ADMIN, False, "0700 100 201"),
    ("manager", "Ronald", "Ssebunya", User.Role.ADMIN, False, "0700 100 202"),
    ("grace", "Grace", "Namuli", User.Role.CASHIER, False, "0700 100 203"),
    ("brian", "Brian", "Okello", User.Role.CASHIER, False, "0700 100 204"),
    ("faith", "Faith", "Atim", User.Role.CASHIER, False, "0700 100 205"),
]
CASHIERS = ["grace", "brian", "faith"]

# name, contact, phone, what they bring (categories)
SUPPLIERS = [
    ("Crown Beverages Ltd", "Moses Kiwanuka", "0700 200 301", ["Beverages"]),
    ("Century Bottling Co.", "Annet Nansubuga", "0700 200 302", ["Beverages"]),
    ("Mukwano Industries", "Patrick Lubega", "0700 200 303",
     ["Cooking essentials", "Soap & detergents"]),
    ("Nakawa Fresh Produce Traders", "Mama Rose Achan", "0700 200 304",
     ["Fresh produce"]),
    ("Pearl Dairy Distributors", "Isaac Mugisha", "0700 200 305", ["Dairy & eggs"]),
    ("Hot Loaf Bakery", "Esther Nalubega", "0700 200 306", ["Bakery"]),
    ("Kampala General Wholesalers", "Hassan Kato", "0700 200 307",
     ["Cereals & grains", "Snacks & confectionery", "Toiletries", "Household",
      "Baby products"]),
    ("Fresh Cuts Butchery", "Joseph Ochieng", "0700 200 308", ["Meat & frozen"]),
]

# name, category, unit, buying, selling, shelf life (days, None = keeps),
# how fast it sells (1 slow ... 5 every few minutes).
# ADD NEW PRODUCTS AT THE END ONLY: a product's barcode comes from its place
# in this list (barcode_for), and the test guide prints some of them.
B, CG, CE, BK, DE, SN, SD, TO, HH, BB, FP, MF = (
    "Beverages", "Cereals & grains", "Cooking essentials", "Bakery", "Dairy & eggs",
    "Snacks & confectionery", "Soap & detergents", "Toiletries", "Household",
    "Baby products", "Fresh produce", "Meat & frozen")
PRODUCTS = [
    ("Coca-Cola 500ml", B, "Piece", 1150, 1500, 240, 5),
    ("Coca-Cola 1.5L", B, "Piece", 3300, 4000, 240, 3),
    ("Fanta Orange 500ml", B, "Piece", 1150, 1500, 240, 4),
    ("Sprite 500ml", B, "Piece", 1150, 1500, 240, 3),
    ("Stoney Tangawizi 500ml", B, "Piece", 1150, 1500, 240, 3),
    ("Pepsi 500ml", B, "Piece", 1100, 1500, 240, 3),
    ("Mirinda Fruity 500ml", B, "Piece", 1100, 1500, 240, 2),
    ("Mountain Dew 500ml", B, "Piece", 1100, 1500, 240, 2),
    ("Novida Pineapple 500ml", B, "Piece", 1150, 1500, 210, 2),
    ("Rwenzori Water 500ml", B, "Piece", 650, 1000, 365, 5),
    ("Rwenzori Water 1.5L", B, "Piece", 1500, 2000, 365, 4),
    ("Highland Water 5L", B, "Piece", 4200, 5500, 365, 2),
    ("Minute Maid Mango 400ml", B, "Piece", 2300, 3000, 180, 2),
    ("Splash Mango 1L", B, "Piece", 3800, 5000, 150, 2),
    ("Riham Cola 350ml", B, "Piece", 500, 700, 200, 3),
    ("Rockboom Energy 400ml", B, "Piece", 750, 1000, 200, 3),
    ("Sting Energy 400ml", B, "Piece", 1050, 1500, 200, 2),
    ("Nescafe Classic 50g", B, "Piece", 7200, 8500, 540, 2),
    ("Kericho Gold Tea Bags (100)", B, "Packet", 5800, 7000, 540, 2),
    ("Mukwano Tea Leaves 250g", B, "Packet", 2900, 3500, 540, 3),
    ("Milo 400g", B, "Piece", 13800, 16000, 365, 2),
    ("Drinking Chocolate 250g", B, "Piece", 5900, 7000, 365, 1),

    ("Super Rice (loose)", CG, "Kilogram", 3900, 4800, None, 5),
    ("Basmati Rice 5kg", CG, "Packet", 27500, 32000, None, 2),
    ("Pakistani Rice 2kg", CG, "Packet", 9400, 11000, None, 2),
    ("Maize Flour (posho, loose)", CG, "Kilogram", 2000, 2600, 150, 5),
    ("Akamai Maize Flour 2kg", CG, "Packet", 5200, 6200, 150, 3),
    ("Golden Wheat Flour 2kg", CG, "Packet", 7300, 8500, 240, 3),
    ("Nambale Beans (loose)", CG, "Kilogram", 4000, 5000, None, 4),
    ("Yellow Beans (loose)", CG, "Kilogram", 4600, 5500, None, 3),
    ("Red Groundnuts (loose)", CG, "Kilogram", 7800, 9500, 180, 3),
    ("Millet Flour (loose)", CG, "Kilogram", 3800, 4800, 120, 2),
    ("Sorghum Flour 1kg", CG, "Packet", 3500, 4300, 120, 1),
    ("Santa Lucia Spaghetti 500g", CG, "Packet", 3300, 4000, 540, 3),
    ("Macaroni 400g", CG, "Packet", 2800, 3500, 540, 2),
    ("Quaker Oats 500g", CG, "Piece", 8000, 9500, 365, 1),
    ("Weetabix 430g", CG, "Piece", 11200, 13000, 300, 1),
    ("Kellogg's Cornflakes 500g", CG, "Piece", 15500, 18000, 300, 1),
    ("Peas, dry (loose)", CG, "Kilogram", 5500, 6800, None, 1),

    ("Kakira Sugar 1kg", CE, "Packet", 4500, 5200, None, 5),
    ("Sugar (loose)", CE, "Kilogram", 4200, 4800, None, 4),
    ("Fresh Fri Cooking Oil 1L", CE, "Piece", 7600, 8800, 365, 4),
    ("Fresh Fri Cooking Oil 3L", CE, "Piece", 21800, 25000, 365, 2),
    ("Mukwano Vegetable Oil 2L", CE, "Piece", 14300, 16500, 365, 3),
    ("Golden Fry Oil 5L", CE, "Piece", 37000, 42000, 365, 1),
    ("Kimbo Cooking Fat 500g", CE, "Piece", 8100, 9500, 365, 2),
    ("Blue Band 250g", CE, "Piece", 5500, 6500, 240, 4),
    ("Blue Band 500g", CE, "Piece", 10300, 12000, 240, 2),
    ("Kensalt Iodated Salt 1kg", CE, "Packet", 1100, 1500, None, 4),
    ("Royco Mchuzi Mix 200g", CE, "Piece", 3800, 4500, 540, 3),
    ("Simba Curry Powder 100g", CE, "Piece", 2400, 3000, 540, 2),
    ("Tomato Paste 70g", CE, "Piece", 750, 1000, 540, 4),
    ("Peptang Tomato Sauce 400g", CE, "Piece", 4600, 5500, 365, 2),
    ("Baking Powder 100g", CE, "Piece", 1900, 2500, 540, 1),
    ("Instant Yeast 10g", CE, "Piece", 700, 1000, 365, 2),
    ("Tea Masala 50g", CE, "Piece", 1500, 2000, 540, 1),
    ("Honey 500g", CE, "Piece", 11500, 14000, None, 1),

    ("Hot Loaf White Bread 500g", BK, "Piece", 3700, 4500, 5, 5),
    ("Hot Loaf Brown Bread 600g", BK, "Piece", 4900, 6000, 5, 3),
    ("Chapati", BK, "Piece", 700, 1000, 2, 4),
    ("Mandazi", BK, "Piece", 300, 500, 2, 3),
    ("Queen Cakes (6)", BK, "Packet", 2300, 3000, 6, 2),
    ("Buns (4)", BK, "Packet", 2700, 3500, 4, 3),

    ("Fresh Dairy Milk 500ml", DE, "Piece", 1800, 2200, 7, 5),
    ("Fresh Dairy Milk 1L", DE, "Piece", 3400, 4000, 7, 3),
    ("Jesa Milk 500ml", DE, "Piece", 1650, 2000, 7, 4),
    ("Jesa Yoghurt 500ml", DE, "Piece", 3700, 4500, 14, 3),
    ("Yoghurt Cup 150ml", DE, "Piece", 1150, 1500, 14, 3),
    ("UHT Long Life Milk 1L", DE, "Piece", 3800, 4500, 180, 2),
    ("Fresh Dairy Butter 250g", DE, "Piece", 8100, 9500, 60, 1),
    ("Gouda Cheese 250g", DE, "Piece", 12900, 15000, 60, 1),
    ("Eggs (tray of 30)", DE, "Tray", 11800, 13500, 21, 4),
    ("Ghee 500g", DE, "Piece", 13700, 16000, 180, 1),

    ("Nice Biscuits 100g", SN, "Piece", 750, 1000, 240, 4),
    ("Glucose Biscuits 100g", SN, "Piece", 750, 1000, 240, 3),
    ("Marie Biscuits 200g", SN, "Piece", 1600, 2000, 240, 2),
    ("Butter Cookies 200g", SN, "Piece", 2900, 3500, 240, 2),
    ("Pringles Original 110g", SN, "Piece", 8100, 9500, 300, 1),
    ("Potato Crisps 50g", SN, "Piece", 1150, 1500, 120, 3),
    ("Cadbury Dairy Milk 80g", SN, "Piece", 5100, 6000, 300, 2),
    ("Orbit Chewing Gum", SN, "Piece", 350, 500, 365, 3),
    ("Roasted Peanuts (small packet)", SN, "Packet", 700, 1000, 90, 3),
    ("Popcorn (packet)", SN, "Packet", 350, 500, 60, 2),
    ("Lollipops (24)", SN, "Packet", 2400, 3000, 365, 1),
    ("Chocolate Cake Slice", SN, "Piece", 1900, 2500, 4, 2),

    ("Omo Washing Powder 500g", SD, "Packet", 4900, 5800, None, 4),
    ("Omo Washing Powder 1kg", SD, "Packet", 9400, 11000, None, 2),
    ("Nomi Detergent 500g", SD, "Packet", 3300, 4000, None, 3),
    ("Mukwano White Bar Soap 1kg", SD, "Piece", 4600, 5500, None, 4),
    ("Sunlight Bar Soap 800g", SD, "Piece", 5100, 6000, None, 2),
    ("Geisha Bathing Soap 125g", SD, "Piece", 2000, 2500, None, 3),
    ("Jik Bleach 750ml", SD, "Piece", 5500, 6500, None, 2),
    ("Harpic Toilet Cleaner 500ml", SD, "Piece", 7600, 9000, None, 1),
    ("Morning Fresh Dish Liquid 400ml", SD, "Piece", 5500, 6500, None, 2),
    ("Doom Insect Spray 300ml", SD, "Piece", 10300, 12000, None, 1),
    ("Steel Wool (pack of 3)", SD, "Packet", 800, 1000, None, 2),

    ("Colgate Toothpaste 100ml", TO, "Piece", 3800, 4500, 540, 3),
    ("Close-Up Toothpaste 100ml", TO, "Piece", 3300, 4000, 540, 2),
    ("Toothbrush (medium)", TO, "Piece", 1500, 2000, None, 2),
    ("Vaseline Petroleum Jelly 100ml", TO, "Piece", 4100, 5000, None, 2),
    ("Nivea Roll-On 50ml", TO, "Piece", 10300, 12000, None, 1),
    ("Always Pads (8)", TO, "Packet", 2900, 3500, None, 3),
    ("Softcare Pads (10)", TO, "Packet", 2400, 3000, None, 3),
    ("Toilet Tissue (single roll)", TO, "Piece", 750, 1000, None, 5),
    ("Toilet Tissue (10 rolls)", TO, "Packet", 11000, 13000, None, 2),
    ("Hand Sanitizer 500ml", TO, "Piece", 6800, 8000, 540, 1),
    ("Shampoo 400ml", TO, "Piece", 7600, 9000, None, 1),
    ("Disposable Razor", TO, "Piece", 700, 1000, None, 2),
    ("Body Lotion 400ml", TO, "Piece", 9400, 11000, None, 1),

    ("Matches (10 boxes)", HH, "Packet", 1600, 2000, None, 3),
    ("Candles (6)", HH, "Packet", 2400, 3000, None, 2),
    ("Charcoal (small sack)", HH, "Piece", 12000, 15000, None, 2),
    ("Plastic Basin 20L", HH, "Piece", 6500, 8000, None, 1),
    ("Soft Broom", HH, "Piece", 4100, 5000, None, 1),
    ("AA Batteries (4)", HH, "Packet", 3300, 4000, None, 2),
    ("Bin Bags (20)", HH, "Packet", 2800, 3500, None, 1),
    ("Aluminium Foil 10m", HH, "Piece", 6200, 7500, None, 1),
    ("Paraffin (loose)", HH, "Litre", 4300, 5000, None, 2),
    ("Mosquito Coils (10)", HH, "Packet", 2000, 2500, None, 2),
    ("Jerrycan 20L", HH, "Piece", 9400, 11000, None, 1),

    ("Pampers Baby-Dry Size 3 (52)", BB, "Packet", 39000, 45000, None, 1),
    ("Softcare Diapers Medium (40)", BB, "Packet", 24000, 28000, None, 2),
    ("Baby Wipes (80)", BB, "Packet", 6300, 7500, 540, 2),
    ("Cerelac Wheat 400g", BB, "Piece", 13800, 16000, 365, 1),
    ("NAN 1 Infant Formula 400g", BB, "Piece", 33000, 38000, 365, 1),
    ("Johnson's Baby Oil 200ml", BB, "Piece", 7600, 9000, None, 1),
    ("Baby Jelly 100ml", BB, "Piece", 3300, 4000, None, 1),

    ("Tomatoes", FP, "Kilogram", 2400, 3500, 6, 5),
    ("Red Onions", FP, "Kilogram", 2900, 4000, 20, 5),
    ("Irish Potatoes", FP, "Kilogram", 2100, 3000, 21, 4),
    ("Matooke (medium bunch)", FP, "Bunch", 12000, 16000, 6, 3),
    ("Bogoya (sweet bananas)", FP, "Kilogram", 2000, 3000, 5, 4),
    ("Pineapple", FP, "Piece", 2800, 4000, 7, 3),
    ("Watermelon", FP, "Piece", 6000, 8000, 10, 2),
    ("Oranges", FP, "Kilogram", 2900, 4000, 12, 3),
    ("Avocado", FP, "Piece", 600, 1000, 6, 4),
    ("Carrots", FP, "Kilogram", 2900, 4000, 14, 3),
    ("Cabbage", FP, "Piece", 1700, 2500, 10, 3),
    ("Green Pepper", FP, "Kilogram", 4400, 6000, 8, 2),
    ("Garlic", FP, "Kilogram", 12500, 16000, 45, 2),
    ("Ginger", FP, "Kilogram", 6000, 8000, 30, 2),
    ("Passion Fruit", FP, "Kilogram", 4400, 6000, 10, 3),
    ("Mangoes", FP, "Kilogram", 3600, 5000, 7, 3),
    ("Sukuma Wiki (bunch)", FP, "Bunch", 600, 1000, 3, 4),
    ("Dodo (bunch)", FP, "Bunch", 300, 500, 3, 3),
    ("Lemons", FP, "Kilogram", 4400, 6000, 14, 1),

    ("Beef (on the bone)", MF, "Kilogram", 15000, 18000, 4, 4),
    ("Goat Meat", MF, "Kilogram", 18500, 22000, 4, 2),
    ("Whole Chicken (frozen)", MF, "Kilogram", 12500, 15000, 90, 3),
    ("Chicken Wings (frozen)", MF, "Kilogram", 11000, 13500, 90, 1),
    ("Fresh Tilapia", MF, "Kilogram", 11500, 14000, 3, 2),
    ("Fresh Cuts Beef Sausages 500g", MF, "Packet", 10300, 12000, 45, 2),
    ("Minced Beef 500g", MF, "Packet", 8400, 10000, 3, 2),
    ("Fish Fingers 400g", MF, "Packet", 11200, 13000, 120, 1),
]

# Shelves running low on purpose - the Low stock report has something to say.
LOW_STOCK = ["Golden Fry Oil 5L", "Kellogg's Cornflakes 500g", "Harpic Toilet Cleaner 500ml",
             "NAN 1 Infant Formula 400g", "Fish Fingers 400g", "Ghee 500g",
             "Plastic Basin 20L", "Drinking Chocolate 250g"]
# Close to their date when the month ends (days left).
NEAR_EXPIRY = {"Jesa Yoghurt 500ml": 3, "Fresh Dairy Butter 250g": 9, "Gouda Cheese 250g": 12,
               "UHT Long Life Milk 1L": 18, "Yoghurt Cup 150ml": 5, "Potato Crisps 50g": 20,
               "Fresh Cuts Beef Sausages 500g": 6}
# Already past their date and still on the shelf (days since).
EXPIRED = {"Peptang Tomato Sauce 400g": 4, "Instant Yeast 10g": 11, "Popcorn (packet)": 2,
           "Baby Wipes (80)": 7}

# name, phone, note, buys on credit
CUSTOMERS = [
    ("Mama Grace Restaurant", "0700 300 401", "Lunch-time restaurant on Kyambogo Road", True),
    ("Nakawa Mothers' Union Canteen", "0700 300 402", "Pays at the end of each month", True),
    ("St. Kizito Day Care", "0700 300 403", "School office - pays every Friday", True),
    ("Kato & Sons Hardware", "0700 300 404", "Staff tea and sugar on account", True),
    ("Jane Akello", "0700 300 405", "", False),
    ("Peter Mugisha", "0700 300 406", "", False),
    ("Aisha Nabukenya", "0700 300 407", "", False),
    ("Daniel Ouma", "0700 300 408", "", False),
    ("Florence Nambi", "0700 300 409", "Orders matooke on Fridays", False),
    ("Samuel Wasswa", "0700 300 410", "", False),
    ("Rebecca Tumusiime", "0700 300 411", "", False),
    ("Hotel Nakawa View", "0700 300 412", "Buys eggs and bread in bulk", False),
]

VOID_REASONS = ["Customer changed her mind at the counter",
                "Rang up the wrong size - sold again on a new receipt",
                "Scanned twice by mistake"]

OPENING_FLOAT = Decimal("50000")


def ean13(body12):
    """A 13-digit barcode with a correct check digit, so a real scanner (or
    the import screen) treats it exactly like one printed on a packet."""
    digits = [int(c) for c in body12]
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits))
    return body12 + str((10 - total % 10) % 10)


def barcode_for(index, unit_name):
    # 20-29 is the range GS1 leaves to shops for their own codes, so these
    # can never be mistaken for a manufacturer's barcode. 21... for goods
    # sold by weight, 20... for everything else.
    prefix = "21" if unit_name in ("Kilogram", "Litre") else "20"
    return ean13(f"{prefix}{6000000000 + index:010d}")


class Command(BaseCommand):
    help = "Fill the FreshWay demonstration shop with products, people and a month of trading."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true",
                            help="Delete all trading, stock and customers and start a fresh month.")
        parser.add_argument("--days", type=int, default=30,
                            help="How many days of past trading to invent (default 30).")
        parser.add_argument("--seed", type=int, default=2026,
                            help="The same number gives the same month every time.")

    def handle(self, *args, **options):
        if not getattr(settings, "DEMO", False):
            raise CommandError(
                "This invents sales and customers, so it only runs on the demonstration "
                "shop (SMMS_DEMO=1 in its settings file). Nothing was changed.")
        password = os.environ.get("DEMO_PASSWORD", "").strip()
        if not password:
            if getattr(settings, "ONLINE", False):
                raise CommandError(
                    "DEMO_PASSWORD is not set in the settings file. It is the password "
                    "for every demo login. Nothing was changed.")
            password = "demo1234"   # a test or a laptop, never the internet
        self.rng = random.Random(options["seed"])
        self.days = max(1, min(options["days"], 90))

        with transaction.atomic():
            if options["reset"]:
                self._wipe()
            self._shop()
            self._reference_data()
            self.people = self._people(password)
            self._suppliers()
            self._products()
            self._customers()
            if Sale.objects.exists() or StockBatch.objects.exists():
                self.stdout.write(
                    "The shop already has stock and trading - left exactly as it is. "
                    "Use --reset to start a fresh month.")
            else:
                self._history()

        self.stdout.write(self.style.SUCCESS(
            f"{COMPANY} is ready: {Product.objects.count()} products, "
            f"{Sale.objects.count()} receipts, {Shift.objects.count()} drawers, "
            f"{Customer.objects.count()} customers. Every demo login uses DEMO_PASSWORD."))

    # ------------------------------------------------------------------
    # The parts that are re-applied every run
    # ------------------------------------------------------------------
    def _wipe(self):
        """Everything a visitor can have changed, in the order the database's
        own protections allow. Logins and the shop's settings stay."""
        SaleItemBatch.objects.all().delete()
        SaleItem.objects.all().delete()
        Sale.objects.all().delete()
        Shift.objects.all().delete()
        HeldSale.objects.all().delete()
        StockCountLine.objects.all().delete()
        StockCount.objects.all().delete()
        StockMovement.objects.all().delete()
        StockBatch.objects.all().delete()
        PurchaseItem.objects.all().delete()
        Purchase.objects.all().delete()
        Product.objects.all().delete()
        Customer.objects.all().delete()
        AuditEvent.objects.all().delete()
        TillGap.objects.all().delete()
        Till.objects.all().delete()
        self.stdout.write("Wiped the demo's trading, stock and customers.")

    def _shop(self):
        shop = ShopSettings.get()
        shop.company_name = COMPANY
        shop.tagline = TAGLINE
        shop.address = ADDRESS
        shop.phone = PHONE
        shop.email = EMAIL
        shop.currency = "UGX"
        shop.vat_percent = Decimal("0")
        shop.receipt_footer = FOOTER
        shop.receipt_width = "80mm"
        shop.default_reorder_level = 5
        shop.expiry_warning_days = 30
        shop.opens_at = time(7, 0)
        shop.closes_at = time(22, 0)
        shop.hosting_paid_until = None   # nobody is paying for a demo
        source = settings.BASE_DIR / "static" / LOGO_SOURCE
        if source.exists():
            target = settings.MEDIA_ROOT / LOGO_TARGET
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            shop.logo = LOGO_TARGET
        shop.save()

    def _reference_data(self):
        for name, abbr, decimals in UNITS:
            Unit.objects.get_or_create(
                name=name, defaults={"abbreviation": abbr, "allow_decimals": decimals})
        for name, description in CATEGORIES:
            Category.objects.get_or_create(name=name, defaults={"description": description})

    def _people(self, password):
        people = {}
        for username, first, last, role, superuser, phone in PEOPLE:
            user, _ = User.objects.get_or_create(username=username)
            user.first_name, user.last_name = first, last
            user.role = role
            user.phone = phone
            user.email = ""
            user.is_active = True
            user.is_staff = user.is_superuser = superuser
            # Back to the demo password every run: a visitor who changed it
            # would otherwise lock the next visitor out.
            user.set_password(password)
            user.has_taken_tour = True
            user.save()
            people[username] = user
        # Never the installer's admin/admin1234 on a public address.
        User.objects.filter(username="admin").exclude(
            username__in=people).update(is_active=False)
        return people

    def _suppliers(self):
        self.suppliers = {}
        for name, contact, phone, cats in SUPPLIERS:
            supplier, _ = Supplier.objects.get_or_create(
                name=name, defaults={"contact_person": contact, "phone": phone,
                                     "address": "Kampala"})
            for cat in cats:
                self.suppliers.setdefault(cat, []).append(supplier)

    def _products(self):
        units = {u.name: u for u in Unit.objects.all()}
        cats = {c.name: c for c in Category.objects.all()}
        self.catalogue = []
        for i, (name, cat, unit, buy, sell, life, speed) in enumerate(PRODUCTS, start=1):
            product, made = Product.objects.get_or_create(
                barcode=barcode_for(i, unit),
                defaults={"name": name, "category": cats[cat], "unit": units[unit],
                          "buying_price": Decimal(buy), "selling_price": Decimal(sell),
                          "reorder_level": Decimal(10 if name in LOW_STOCK else
                                                   {5: 20, 4: 15, 3: 10}.get(speed, 5))})
            self.catalogue.append((product, life, speed))

    def _customers(self):
        self.credit_customers, self.named_customers = [], []
        for name, phone, note, credit in CUSTOMERS:
            customer, _ = Customer.objects.get_or_create(
                name=name, defaults={"phone": phone, "notes": note,
                                     "address": "Nakawa, Kampala"})
            (self.credit_customers if credit else self.named_customers).append(customer)

    # ------------------------------------------------------------------
    # The month of trading - only on an empty shop
    # ------------------------------------------------------------------
    def _history(self):
        today = timezone.localdate()
        self.first_day = today - timedelta(days=self.days)
        manager = self.people["manager"]

        self._opening_stock(manager)
        delivery_days = [self.first_day + timedelta(days=d)
                         for d in range(6, self.days, 7)]
        for day in range(self.days):
            date = self.first_day + timedelta(days=day)
            if date in delivery_days:
                self._delivery(date, manager)
            self._trade_day(date, close_drawers=True)
        self._stock_take(today - timedelta(days=min(5, self.days)), manager)
        self._expiry_situations(today)
        self._pending_delivery(today, manager)

    def _at(self, date, hour, minute=0):
        return timezone.make_aware(datetime.combine(date, time(hour, minute)))

    def _opening_stock(self, manager):
        """The shelves on the day the system went in: one stock take, as a
        shop moving onto the system really does it."""
        rows = []
        for product, life, speed in self.catalogue:
            if product.name in LOW_STOCK:
                qty = 6
            else:
                qty = {5: 160, 4: 110, 3: 70, 2: 40, 1: 20}[speed] * max(1, self.days) // 30 + 12
            rows.append({"product": product, "counted": Decimal(qty),
                         "buying_price": product.buying_price,
                         "expiry_date": self._expiry(self.first_day, life)})
        count = apply_stock_count(rows=rows, user=manager, scope="Opening stock - whole shop",
                                  note="Counted the night before the system went in.",
                                  date=self.first_day - timedelta(days=1))
        self._backdate_refs([count.reference], self._at(self.first_day - timedelta(days=1), 20))
        StockBatch.objects.update(received_on=self.first_day - timedelta(days=1))

    def _delivery(self, date, manager):
        """Two suppliers a week, in turn, each bringing the fast movers in
        its own categories."""
        if not hasattr(self, "_rota"):
            self._rota = list(Supplier.objects.order_by("name"))
        for _ in range(2):
            supplier = self._rota.pop(0)
            self._rota.append(supplier)
            cats = {c for c, sups in self.suppliers.items() if supplier in sups}
            lines = [(p, life, speed) for p, life, speed in self.catalogue
                     if p.category.name in cats and p.name not in LOW_STOCK and speed >= 2]
            if not lines:
                continue
            purchase = Purchase.objects.create(
                supplier=supplier, invoice_no=f"INV-{self.rng.randint(10000, 99999)}",
                date=date, received_by=manager)
            for product, life, speed in lines:
                PurchaseItem.objects.create(
                    purchase=purchase, product=product, quantity=Decimal(speed * 12),
                    buying_price=product.buying_price,
                    expiry_date=self._expiry(date, life))
            receive_purchase(purchase, manager)
            self._backdate_refs([purchase.reference], self._at(date, 9, 30))

    def _expiry(self, received, life):
        """Bread, fruit and meat are sold by sight and not dated here; the
        rest carry a date that outlasts the invented month, so the only
        stock near or past its date is the stock put there on purpose."""
        if not life or life <= 7:
            return None
        return received + timedelta(days=max(life, self.days + 45))

    def _pending_delivery(self, today, manager):
        """A delivery at the back door that nobody has checked in yet - the
        'receive a delivery' step of the test guide."""
        supplier = Supplier.objects.get(name="Crown Beverages Ltd")
        purchase = Purchase.objects.create(
            supplier=supplier, invoice_no="CB-77812", date=today, received_by=manager,
            notes="Delivered at 8 a.m. - check the crates against the invoice, then receive.")
        for product, life, speed in self.catalogue:
            if product.category.name == "Beverages" and speed >= 3:
                PurchaseItem.objects.create(
                    purchase=purchase, product=product, quantity=Decimal(24),
                    buying_price=product.buying_price,
                    expiry_date=self._expiry(today, life))

    def _basket(self):
        weights = [speed ** 2 for _, _, speed in self.catalogue]
        picks = self.rng.choices(self.catalogue, weights=weights,
                                 k=self.rng.choice([1, 1, 2, 2, 3, 3, 4, 5, 6]))
        lines, seen = [], set()
        for product, _, _ in picks:
            if product.id in seen:
                continue
            seen.add(product.id)
            if product.unit.allow_decimals:
                qty = Decimal(self.rng.choice(["0.5", "1", "1", "1.5", "2", "2.5", "3"]))
            else:
                qty = Decimal(self.rng.choice([1, 1, 1, 1, 2, 2, 3, 6]))
            lines.append({"product": product, "quantity": qty,
                          "unit_price": product.selling_price})
        return lines

    def _trade_day(self, date, close_drawers):
        """A morning and an evening drawer, the third cashier covering two
        days a week."""
        now = timezone.localtime()
        rota = list(CASHIERS)
        self.rng.shuffle(rota)
        shifts = [(rota[0], 7, 14), (rota[1], 14, 22)]
        if date.weekday() in (4, 5):   # Friday and Saturday are busier
            shifts.append((rota[2], 10, 18))
        for username, start, end in shifts:
            opened = self._at(date, start, self.rng.choice([0, 5, 10, 15]))
            if opened >= now:
                continue
            user = self.people[username]
            shift = Shift.objects.create(user=user, opened_at=opened,
                                         opening_float=OPENING_FLOAT)
            busy = 2 if date.weekday() in (4, 5) else 1
            n = self.rng.randint(9, 15) * busy
            span = (end - start) * 60
            for k in range(n):
                at = opened + timedelta(minutes=span * (k + self.rng.random()) / n)
                if at >= now:
                    break
                self._one_sale(user, at, keep_number=(date == now.date()))
            if close_drawers:
                self._close_drawer(shift, self._at(date, end, self.rng.randint(5, 25)))

    def _one_sale(self, user, at, keep_number):
        lines = self._basket()
        if not lines:
            return
        roll = self.rng.random()
        customer = None
        if roll < 0.07 and self.credit_customers:
            method, customer = Sale.Payment.CREDIT, self.rng.choice(self.credit_customers)
        elif roll < 0.37:
            method = Sale.Payment.MOBILE
        elif roll < 0.45:
            method = Sale.Payment.CARD
        else:
            method = Sale.Payment.CASH
        if customer is None and self.rng.random() < 0.12:
            customer = self.rng.choice(self.named_customers)
        total = sum((l["quantity"] * l["unit_price"] for l in lines), Decimal("0"))
        discount = Decimal("500") if total > 30000 and self.rng.random() < 0.2 else Decimal("0")
        due = total - discount
        if method == Sale.Payment.CREDIT:
            paid = Decimal("0")
        elif method == Sale.Payment.CASH:
            # Customers hand over notes; the change is the till's problem.
            paid = due if self.rng.random() < 0.4 else (due / 1000).to_integral_value(
                rounding="ROUND_CEILING") * 1000
        else:
            paid = due
        try:
            sale = record_sale(user=user, lines=lines, customer=customer, discount=discount,
                               payment_method=method, amount_paid=paid)
        except (InsufficientStock, ValueError):
            return
        old = sale.receipt_no
        if not keep_number:
            sale.receipt_no = self._receipt_no(at.date())
        sale.created_at = at
        sale.save(update_fields=["receipt_no", "created_at"])
        StockMovement.objects.filter(reference=old).update(
            reference=sale.receipt_no, created_at=at)
        if self.rng.random() < 0.012:
            manager = self.people["manager"]
            reason = self.rng.choice(VOID_REASONS)
            sale.void(manager, reason)
            later = at + timedelta(minutes=self.rng.randint(2, 20))
            Sale.objects.filter(pk=sale.pk).update(voided_at=later)
            StockMovement.objects.filter(reference=sale.receipt_no,
                                         kind=StockMovement.Kind.RETURN).update(created_at=later)
            event = audit.record(
                AuditEvent.Action.SALE_VOIDED,
                f"Voided {sale.receipt_no} ({sale.total:,.0f}), sold by {user.display_name}",
                user=manager, reference=sale.receipt_no, changes=f"Reason: {reason}")
            if event:
                AuditEvent.objects.filter(pk=event.pk).update(at=later)

    def _receipt_no(self, date):
        prefix = f"R{date:%y%m%d}"
        last = (Sale.objects.filter(receipt_no__startswith=prefix)
                .order_by("-receipt_no").values_list("receipt_no", flat=True).first())
        seq = int(last[len(prefix):]) + 1 if last else 1
        return f"{prefix}{seq:04d}"

    def _close_drawer(self, shift, at):
        """Most drawers balance to the shilling. One in a while is a little
        out; the biggest shortage and the one drawer over are the owner's
        two stories when he opens the cash-up report."""
        expected = shift.expected_cash
        r = self.rng.random()
        if not hasattr(self, "_short_done"):
            variance, self._short_done = Decimal("-15000"), True
            note = "Could not find the missing 15,000. Told the manager."
        elif not hasattr(self, "_over_done") and shift.sale_count > 5:
            variance, self._over_done = Decimal("2000"), True
            note = "2,000 over - a customer left without his change?"
        elif r < 0.12:
            variance, note = Decimal(self.rng.choice([-500, -1000, -200])), ""
        else:
            variance, note = Decimal("0"), ""
        Shift.objects.filter(pk=shift.pk).update(
            counted_cash=expected + variance, closed_at=at, closed_by=shift.user,
            note=note, status=Shift.Status.CLOSED)
        state = ("balanced" if variance == 0 else
                 f"SHORT {-variance:,.0f}" if variance < 0 else f"over {variance:,.0f}")
        event = audit.record(
            AuditEvent.Action.DRAWER_HANDED_OVER,
            f"{shift.user.display_name} handed over the drawer - {state}",
            user=shift.user, reference=f"shift-{shift.pk}",
            changes=f"Expected cash: {expected:,.0f}\nCounted cash: {expected + variance:,.0f}")
        if event:
            AuditEvent.objects.filter(pk=event.pk).update(at=at)

    def _stock_take(self, date, manager):
        """A count of the drinks shelf that found two bottles missing."""
        rows = []
        for product, _, _ in self.catalogue:
            if product.category.name != "Beverages":
                continue
            have = product.stock_available
            if have <= 2:
                continue
            short = Decimal(2) if product.name in ("Coca-Cola 500ml", "Sting Energy 400ml") \
                else Decimal(0)
            rows.append({"product": product, "counted": have - short})
        if rows:
            count = apply_stock_count(rows=rows, user=manager, scope="Beverages",
                                      note="Two bottles short - check the crate by the door.",
                                      date=date)
            self._backdate_refs([count.reference], self._at(date, 21, 30))

    def _expiry_situations(self, today):
        """Stock about to expire, and stock already past its date, put on the
        shelf now so the month's sales did not use it up first."""
        by_name = {p.name: p for p, _, _ in self.catalogue}
        manager = self.people["manager"]
        for name, days in NEAR_EXPIRY.items():
            product = by_name[name]
            adjust_stock(product=product, quantity=Decimal(8), kind=StockMovement.Kind.ADJUST,
                         reason="Found in the store room", user=manager,
                         expiry_date=today + timedelta(days=days))
        for name, days in EXPIRED.items():
            product = by_name[name]
            adjust_stock(product=product, quantity=Decimal(5), kind=StockMovement.Kind.ADJUST,
                         reason="Found in the store room", user=manager,
                         expiry_date=today - timedelta(days=days))

    def _backdate_refs(self, references, at):
        StockMovement.objects.filter(reference__in=references).update(created_at=at)
        StockCount.objects.filter(reference__in=references).update(created_at=at)
        Purchase.objects.filter(reference__in=references).update(created_at=at)
