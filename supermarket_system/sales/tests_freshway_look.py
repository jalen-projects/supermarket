"""FreshWay's own front door, and MAQAM's left exactly as it was.

The demonstration shop has its own sign-in page (a market stall with this
morning's produce board), its own opening animation, its own owner's-phone
header and its own band over the dashboard, all chosen by shop/brand.py.
The promise tested here is two-sided: with SMMS_BRAND=freshway those are
what is served, and with nothing set MAQAM gets his own screens, untouched,
and not one FreshWay file.
"""
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from inventory.models import Category, Product, Unit
from shop import brand
from shop.models import ShopSettings, User

FRESHWAY_FILES = ("css/freshway.css", "css/freshway-intro.css", "css/freshway-owner.css",
                  "css/freshway-dash.css", "css/freshway-app.css", "outfit-latin.woff2")


class FrontDoorTestCase(TestCase):
    def setUp(self):
        shop = ShopSettings.get()
        shop.company_name = "FreshWay Supermarket"
        shop.tagline = "Fresh every morning, fair every day"
        shop.save()
        self.owner = User.objects.create_user(
            username="owner", password="pw12345", role=User.Role.ADMIN, first_name="Sarah")
        produce = Category.objects.create(name="Fresh produce")
        drinks = Category.objects.create(name="Beverages")
        kg = Unit.objects.create(name="Kilogram", abbreviation="kg", allow_decimals=True)
        pc = Unit.objects.create(name="Piece", abbreviation="pc")
        Product.objects.create(name="Tomatoes", category=produce, unit=kg,
                               buying_price=Decimal("2417"), selling_price=Decimal("3500"))
        Product.objects.create(name="Pineapple", category=produce, unit=pc,
                               buying_price=Decimal("2800"), selling_price=Decimal("4000"))
        Product.objects.create(name="Withdrawn Yams", category=produce, unit=kg,
                               selling_price=Decimal("5000"), is_active=False)
        Product.objects.create(name="Soda 500ml", category=drinks, unit=pc,
                               selling_price=Decimal("1500"))

    def page(self, name):
        response = self.client.get(reverse(name))
        self.assertEqual(response.status_code, 200)
        return response, response.content.decode()


class MaqamUnchangedTests(FrontDoorTestCase):
    """Nothing set: MAQAM's screens, his templates, none of FreshWay's files."""

    def test_sign_in_page_is_maqams_own(self):
        response, page = self.page("login")
        self.assertTemplateUsed(response, "shop/login.html")
        self.assertTemplateUsed(response, "partials/app_intro.html")
        self.assertTemplateNotUsed(response, "shop/freshway/login.html")
        self.assertTemplateNotUsed(response, "partials/freshway/app_intro.html")
        # the receipt over the photograph, and the seed-to-trolley opening
        for part in ("css/login.css", "css/intro.css", 'class="si-receipt"', "shopper-1440",
                     'class="app-intro"', "ai-cart", "maqam-intro", "play-intro",
                     brand.BRANDS["maqam"]["mark_a1"]):
            self.assertIn(part, page)
        for part in FRESHWAY_FILES + ("fw-awning", "play-fw-intro", "On the stall today",
                                      "Tomatoes"):
            self.assertNotIn(part, page)
        self.assertNotIn("price_board", response.context)

    def test_owner_page_and_dashboard_are_maqams_own(self):
        self.client.force_login(self.owner)
        response, page = self.page("owner")
        self.assertTemplateUsed(response, "shop/owner.html")
        self.assertTemplateUsed(response, "partials/app_intro.html")
        self.assertIn('<header class="ow-head">', page)
        self.assertIn("Today so far", page)
        for part in FRESHWAY_FILES + ("fwo-head",):
            self.assertNotIn(part, page)

        response, page = self.page("dashboard")
        self.assertTemplateUsed(response, "partials/dash_band.html")
        self.assertIn("till-rolls", page)
        for part in FRESHWAY_FILES + ("fwd-band",):
            self.assertNotIn(part, page)

    def test_the_brand_has_no_screens_of_its_own(self):
        for name in ("shop/login.html", "shop/owner.html", "partials/dash_band.html"):
            self.assertEqual(brand.template(name), name)
        self.assertNotIn("app_css", brand.BRANDS["maqam"])


@override_settings(SHOP_BRAND="freshway", DEMO=True)
class FreshWayFrontDoorTests(FrontDoorTestCase):
    def test_sign_in_page_is_the_market_stall(self):
        response, page = self.page("login")
        self.assertTemplateUsed(response, "shop/freshway/login.html")
        self.assertTemplateUsed(response, "partials/freshway/app_intro.html")
        self.assertTemplateNotUsed(response, "shop/login.html")
        self.assertTemplateNotUsed(response, "partials/app_intro.html")
        for part in ("css/freshway.css", "css/freshway-intro.css", "fw-awning", "play-fw-intro",
                     "freshway-intro", "fw-crate", "Fresh every morning, fair every day",
                     brand.BRANDS["freshway"]["mark_a1"], "demonstration shop"):
            self.assertIn(part, page)
        # none of MAQAM's front door
        for part in ("css/login.css", "css/intro.css", "si-receipt", "shopper-1440", "ai-cart"):
            self.assertNotIn(part, page)
        self.assertNotIn("MAQAM", page.upper())
        # the form still posts the same fields to the same place
        for part in ('name="username"', 'name="password"', 'id="signin-form"', 'name="next"'):
            self.assertIn(part, page)

    def test_the_board_shows_todays_shelf_prices_and_nothing_else(self):
        response, page = self.page("login")
        self.assertIn("On the stall today", page)
        self.assertIn("Tomatoes", page)
        self.assertIn("3,500", page)
        self.assertIn("Pineapple", page)
        self.assertNotIn("2,417", page)            # never what the shop paid
        self.assertNotIn("Withdrawn Yams", page)   # not on sale
        self.assertNotIn("Soda 500ml", page)       # not produce

    def test_signing_in_still_works(self):
        response = self.client.post(reverse("login"), {"username": "owner", "password": "pw12345"})
        self.assertEqual(response.status_code, 302)
        self.client.logout()
        response = self.client.post(reverse("login"), {"username": "owner", "password": "wrong"})
        self.assertContains(response, 'class="fw-error"')

    def test_no_produce_means_no_board(self):
        Product.objects.filter(category__name="Fresh produce").update(is_active=False)
        response, page = self.page("login")
        self.assertNotIn("On the stall today", page)
        self.assertIn("fw-awning", page)

    def test_owner_page_and_dashboard_wear_the_stall(self):
        self.client.force_login(self.owner)
        response, page = self.page("owner")
        self.assertTemplateUsed(response, "shop/freshway/owner.html")
        self.assertTemplateUsed(response, "partials/owner_body.html")
        for part in ("fwo-head", "css/freshway-owner.css", "Good ", "Sarah", "Today so far",
                     "The full audit trail"):
            self.assertIn(part, page)
        self.assertNotIn("css/intro.css", page)

        response, page = self.page("dashboard")
        self.assertTemplateUsed(response, "partials/freshway/dash_band.html")
        for part in ("fwd-band", "css/freshway-dash.css", "css/freshway-app.css", "Tomatoes"):
            self.assertIn(part, page)
        self.assertNotIn("till-rolls", page)


# ---------------------------------------------------------------------------
# Moving pictures (7 Oct 2026): the market behind the stall and the three
# loops recorded from the demo shop. FreshWay only; never in MAQAM's way.
# ---------------------------------------------------------------------------
import re  # noqa: E402
from pathlib import Path  # noqa: E402

from django.conf import settings  # noqa: E402
from django.template.loader import get_template  # noqa: E402

FOOTAGE = Path(settings.BASE_DIR) / "static" / "brand" / "freshway" / "footage"
# file: the most it may weigh, for a shop on Ugandan mobile data
FOOTAGE_BUDGET = {
    "market.mp4": 2_500_000, "market-poster.webp": 200_000, "market-phone.webp": 200_000,
    "clip-till.mp4": 1_000_000, "clip-till.webp": 200_000,
    "clip-owner.mp4": 1_000_000, "clip-owner.webp": 200_000,
    "clip-stock.mp4": 1_000_000, "clip-stock.webp": 200_000,
}
MEDIA_MARKS = ("<video", "brand/freshway/footage", "fw-scene", "fw-reel", "IntersectionObserver")


class MaqamHasNoMovingPicturesTests(FrontDoorTestCase):
    """MAQAM's pages are what they were: not a video, not a still, not a
    script of FreshWay's. Nothing set means none of this."""

    def test_his_pages_carry_none_of_it(self):
        response, page = self.page("login")
        for part in MEDIA_MARKS:
            self.assertNotIn(part, page)
        self.client.force_login(self.owner)
        for name in ("owner", "dashboard"):
            response, page = self.page(name)
            for part in MEDIA_MARKS:
                self.assertNotIn(part, page)

    def test_no_template_of_his_names_the_footage(self):
        # Only FreshWay's own sign-in page may point at the footage.
        root = Path(settings.BASE_DIR) / "templates"
        for path in root.rglob("*.html"):
            if path.as_posix().endswith("shop/freshway/login.html"):
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("footage", text, path)
            self.assertNotIn("<video", text, path)

    def test_his_sign_in_template_is_the_one_he_had(self):
        self.assertEqual(get_template(brand.template("shop/login.html")).origin.template_name,
                         "shop/login.html")


@override_settings(SHOP_BRAND="freshway", DEMO=True)
class FreshWayMovingPicturesTests(FrontDoorTestCase):
    def test_the_market_is_a_still_first_and_a_video_only_later(self):
        response, page = self.page("login")
        scene = page[page.index('class="fw-scene"'):page.index('class="fw-awning"')]
        self.assertIn("market-poster.webp", scene)
        self.assertIn("market-phone.webp", scene)
        video = re.search(r"<video[^>]*>", scene).group(0)
        # the parser never fetches it: no src, no autoplay, nothing preloaded
        self.assertIn('preload="none"', video)
        self.assertIn("data-src=", video)
        self.assertNotRegex(video, r"\ssrc=")
        self.assertNotIn("autoplay", video)
        for attr in ("muted", "loop", "playsinline"):
            self.assertIn(attr, video)

    def test_video_waits_for_the_page_and_respects_the_connection(self):
        response, page = self.page("login")
        script = page[page.index("Moving pictures"):]
        for part in ("addEventListener('load'", "prefers-reduced-motion: reduce", "saveData",
                     "2g", "IntersectionObserver", ".pause()", "min-width: 861px"):
            self.assertIn(part, script)
        # the form comes before every picture in the page
        self.assertLess(page.index('id="signin-form"'), page.index('class="fw-scene"'))

    def test_the_loops_are_below_the_form_lazy_and_sized(self):
        response, page = self.page("login")
        reel = page[page.index('class="fw-reel"'):]
        self.assertGreater(page.index('class="fw-reel"'), page.index("</main>"))
        for clip in ("clip-till", "clip-owner", "clip-stock"):
            img = re.search(r'<img src="[^"]*%s\.webp"[^>]*>' % clip, reel).group(0)
            for attr in ('loading="lazy"', "width=", "height=", "alt="):
                self.assertIn(attr, img)
            self.assertIn('data-src="/static/brand/freshway/footage/%s.mp4"' % clip, reel)
        self.assertEqual(reel.count("<video"), 3)
        self.assertNotIn("autoplay", reel)

    @override_settings(DEMO=False)
    def test_a_real_freshway_has_no_demo_reel(self):
        response, page = self.page("login")
        self.assertNotIn("fw-reel", page)
        self.assertIn("fw-scene", page)

    def test_every_picture_is_ours_light_and_credited(self):
        response, page = self.page("login")
        named = set(re.findall(r"brand/freshway/footage/([\w.-]+)", page))
        self.assertEqual(named, set(FOOTAGE_BUDGET))
        credits = (FOOTAGE / "CREDITS.md").read_text(encoding="utf-8")
        for name, most in FOOTAGE_BUDGET.items():
            size = (FOOTAGE / name).stat().st_size
            self.assertLessEqual(size, most, name)
            self.assertIn(name, credits)
        # served from the shop itself, never from someone else's server
        for src in re.findall(r'(?:src|srcset|data-src)="([^"]+)"', page):
            self.assertFalse(src.startswith(("http:", "https:", "//")), src)
