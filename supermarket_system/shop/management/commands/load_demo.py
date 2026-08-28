"""Fills the system with a believable week of trading, for showing a client.

    python manage.py load_demo

Never run this on a real shop's database - it adds fake sales.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inventory.models import Category, Product, Purchase, PurchaseItem, Supplier, Unit
from sales.models import Customer, Sale
from sales.services import receive_purchase, record_sale
from shop.models import ShopSettings, User

# name, category, unit, buying, selling, barcode, shelf life in days
PRODUCTS = [
    ("Coca-Cola 500ml", "Beverages", "Piece", 1200, 1500, "5449000000996", 180),
    ("Novida 500ml", "Beverages", "Piece", 1200, 1500, "6009510800104", 150),
    ("Rwenzori Water 1L", "Beverages", "Piece", 1000, 1500, "6009510800111", 365),
    ("Azam Juice 500ml", "Beverages", "Piece", 1500, 2000, "6009510800128", 120),
    ("Rice (Super) ", "Cereals & grains", "Kilogram", 4200, 5000, None, None),
    ("Maize flour", "Cereals & grains", "Kilogram", 2500, 3200, None, 180),
    ("Beans", "Cereals & grains", "Kilogram", 3500, 4500, None, None),
    ("Fresh Dairy Milk 500ml", "Dairy & eggs", "Piece", 1800, 2200, "6009510800135", 7),
    ("Eggs", "Dairy & eggs", "Tray", 11000, 13000, None, 21),
    ("Blue Band 250g", "Cooking essentials", "Piece", 5500, 6500, "6009510800142", 240),
    ("Fresh Fri 1L", "Cooking essentials", "Piece", 7500, 8800, "6009510800159", 365),
    ("Kabras Sugar 1kg", "Cooking essentials", "Piece", 4500, 5200, "6009510800166", 540),
    ("Salt 1kg", "Cooking essentials", "Piece", 1000, 1500, "6009510800173", None),
    ("Bread (large)", "Bakery", "Piece", 4000, 5000, None, 4),
    ("Britannia Biscuits", "Snacks & confectionery", "Piece", 800, 1200, "6009510800180", 200),
    ("Omo 500g", "Soap & detergents", "Piece", 4800, 5800, "6009510800197", 730),
    ("Sunlight bar soap", "Soap & detergents", "Piece", 3200, 4000, "6009510800203", 730),
    ("Colgate 100ml", "Toiletries", "Piece", 3500, 4500, "6009510800210", 540),
    ("Tissue (4 rolls)", "Toiletries", "Packet", 5000, 6500, "6009510800227", None),
    ("Matches (10 boxes)", "Household", "Packet", 1500, 2000, None, None),
    ("Pampers small", "Baby products", "Packet", 22000, 26000, "6009510800234", 730),
    ("Tomatoes", "Fresh produce", "Kilogram", 2500, 3500, None, 5),
    ("Onions", "Fresh produce", "Kilogram", 3000, 4000, None, 14),
    ("Chicken (frozen)", "Meat & frozen", "Kilogram", 12000, 15000, None, 60),
]

CUSTOMERS = [
    ("Mama Nakato", "0772 000 111"),
    ("Ssalongo Kizza", "0701 234 567"),
    ("Hotel Sunrise", "0392 555 000"),
    ("Sarah Nabbosa", "0754 909 090"),
]

CASHIERS = [("moses", "Moses", "Okello"), ("aisha", "Aisha", "Namutebi")]


class Command(BaseCommand):
    help = "Load demonstration products, deliveries and a week of sales."

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(7)  # the same demo every time, so a walkthrough is repeatable

        shop = ShopSettings.get()
        if shop.company_name == "My Supermarket":
            shop.company_name = "Nakawa Super Store"
            shop.address = "Plot 12, Jinja Road, Kampala"
            shop.phone = "0772 000 000"
            shop.receipt_footer = "Thank you for shopping with us. Come again!"
            shop.save()

        owner = User.objects.filter(role=User.Role.ADMIN).first()
        if not owner:
            self.stderr.write("Run 'python manage.py setup_shop' first.")
            return

        cashiers = []
        for username, first, last in CASHIERS:
            user, made = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last,
                          "role": User.Role.CASHIER})
            if made:
                user.set_password("till1234")
                user.save()
            cashiers.append(user)
        self.stdout.write(f"Cashiers ready ({len(cashiers)}), password 'till1234'")

        supplier, _ = Supplier.objects.get_or_create(
            name="Kampala Wholesalers Ltd",
            defaults={"contact_person": "Mr. Mugisha", "phone": "0700 111 222",
                      "address": "Kikuubo, Kampala"})
        Supplier.objects.get_or_create(
            name="Fresh Dairy Distributors",
            defaults={"phone": "0700 333 444"})

        today = timezone.localdate()
        products = []
        for name, cat, unit, buy, sell, barcode, shelf in PRODUCTS:
            category = Category.objects.filter(name=cat).first()
            measure = Unit.objects.filter(name=unit).first()
            if not category or not measure:
                self.stderr.write("Run 'python manage.py setup_shop' first.")
                return
            product, _ = Product.objects.get_or_create(
                name=name.strip(),
                defaults={"category": category, "unit": measure, "barcode": barcode,
                          "buying_price": Decimal(buy), "selling_price": Decimal(sell),
                          "reorder_level": Decimal("10")})
            products.append((product, shelf))
        self.stdout.write(f"Products: {Product.objects.count()}")

        # One delivery ten days ago that stocked the shop.
        purchase = Purchase.objects.create(
            supplier=supplier, received_by=owner, date=today - timedelta(days=10),
            invoice_no="INV-4471", notes="Opening stock for the demonstration")
        for product, shelf in products:
            expiry = today + timedelta(days=shelf - 10) if shelf else None
            PurchaseItem.objects.create(
                purchase=purchase, product=product,
                quantity=Decimal(random.choice([40, 60, 80, 100])),
                buying_price=product.buying_price, expiry_date=expiry)
        receive_purchase(purchase, owner)
        self.stdout.write(f"Delivery {purchase.reference} received "
                          f"({purchase.item_count} lines)")

        # A small later delivery of perishables, some of which have now expired -
        # this is what makes the expiry reports show something real.
        perishables = Purchase.objects.create(
            supplier=supplier, received_by=owner, date=today - timedelta(days=6),
            invoice_no="INV-4502", notes="Perishables top-up")
        for name, days in [("Bread (large)", -1), ("Fresh Dairy Milk 500ml", 1),
                           ("Tomatoes", -2), ("Eggs", 9)]:
            product = Product.objects.get(name=name)
            PurchaseItem.objects.create(
                purchase=perishables, product=product, quantity=Decimal("20"),
                buying_price=product.buying_price, expiry_date=today + timedelta(days=days))
        receive_purchase(perishables, owner)
        self.stdout.write(f"Delivery {perishables.reference} received (perishables)")

        customers = [Customer.objects.get_or_create(name=n, defaults={"phone": p})[0]
                     for n, p in CUSTOMERS]

        # A week of trading. Weekends are busier, as they are in a real shop.
        sellable = [p for p, _ in products]
        made = 0
        for days_ago in range(7, 0, -1):
            day = timezone.now() - timedelta(days=days_ago)
            weekend = day.weekday() >= 5
            for _ in range(random.randint(12, 20) if weekend else random.randint(6, 12)):
                lines = []
                for product in random.sample(sellable, random.randint(1, 5)):
                    if product.sellable_quantity < 3:
                        continue
                    quantity = (Decimal(str(round(random.uniform(0.5, 3), 1)))
                                if product.unit.allow_decimals
                                else Decimal(random.randint(1, 3)))
                    lines.append({"product": product, "quantity": quantity,
                                  "unit_price": product.selling_price})
                if not lines:
                    continue
                try:
                    sale = record_sale(
                        user=random.choice(cashiers), lines=lines,
                        customer=random.choice(customers) if random.random() < 0.2 else None,
                        payment_method=random.choice(
                            [Sale.Payment.CASH, Sale.Payment.CASH, Sale.Payment.CASH,
                             Sale.Payment.MOBILE]),
                        amount_paid=Decimal("0"))
                except Exception:
                    continue
                # Back-date it so the reports have a week of history to draw.
                sale.created_at = day.replace(
                    hour=random.randint(8, 19), minute=random.randint(0, 59))
                sale.amount_paid = sale.total
                sale.save(update_fields=["created_at", "amount_paid"])
                made += 1

        self.stdout.write(self.style.SUCCESS(
            f"Demo ready: {made} sales over the last 7 days. "
            f"Sign in as admin, or as a cashier (moses / till1234)."))
