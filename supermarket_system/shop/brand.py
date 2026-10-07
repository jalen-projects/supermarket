"""Everything about a shop that is DRAWN rather than typed in.

The shop's name, address, phone, receipt footer and uploaded logo live in the
database (Shop details) and the owner can change them. What cannot be typed
into a form - the mark drawn on the sign-in page and in the opening
animation, the phone-app icons, the names this shop's data is kept under in
the browser - lives here, one entry per shop, chosen by SMMS_BRAND on the
server (settings.SHOP_BRAND).

Two shops run this code on the same server: MAQAM FOOD CITY SUPERMARKET
(maqam.campusnect.com) and the FreshWay demonstration shop
(supermarket.campusnect.com). An unknown or missing name means MAQAM, so his
shop PC and his server, which set nothing, are exactly as they were.

THE MARK is two stroked paths and one filled shape, always. The sign-in page
draws the two strokes on and grows the filled shape in, and the opening
animation does the same in white and orange, so a new shop's mark must keep
that shape: `a1` and `a2` are path data for the strokes, `bar` for the fill,
all in a 512 x 512 box centred near (256, 262).

ITS OWN FRONT DOOR. A shop may also have its own sign-in page, opening
animation and owner's-phone header, so that a visitor who has seen one shop
does not meet the same page with a new name. `templates` maps a screen to
that shop's own template; a screen not listed (and every screen of a shop
with no `templates`) is the shared one. MAQAM lists none, so his screens are
exactly what they always were.
"""
from django.conf import settings

BRANDS = {
    "maqam": {
        "key": "maqam",
        # An M whose shoulders are two market arches, on a counter.
        "mark_a1": "M150 326 V190 A53 53 0 0 1 256 190 V326",
        "mark_a2": "M256 190 A53 53 0 0 1 362 190 V326",
        "mark_bar": "M151 366 H361 A11 11 0 0 1 361 388 H151 A11 11 0 0 1 151 366 Z",
        "static_dir": "brand/",
        "favicon": "favicon.svg",
        "logo": "brand/maqam-logo.png",
        "backup_folder": "MAQAM BACKUPS",
    },
    "freshway": {
        # The demonstration shop - FreshWay Supermarket, Nakawa. Fictional.
        "key": "freshway",
        # An F drawn as one shoot that rises and turns into its top bar, with
        # an orange on the end of its middle bar.
        "mark_a1": "M170 388 V216 A80 80 0 0 1 250 136 H340",
        "mark_a2": "M170 264 H262",
        "mark_bar": "M296 264 A36 36 0 1 0 368 264 A36 36 0 1 0 296 264 Z",
        "static_dir": "brand/freshway/",
        "favicon": "brand/freshway/favicon.svg",
        "logo": "brand/freshway/freshway-logo.png",
        "backup_folder": "FRESHWAY BACKUPS",
        # The market-stall front door: a striped awning, today's produce
        # prices on a board, and an opening where the shutter rolls up.
        "templates": {
            "shop/login.html": "shop/freshway/login.html",
            "shop/owner.html": "shop/freshway/owner.html",
            "partials/dash_band.html": "partials/freshway/dash_band.html",
        },
        # Colours only, over app.css on every working screen: the sidebar in
        # the stall's green. No size or position changes, the till included.
        "app_css": "css/freshway-app.css",
        # The sign-in page shows this category's shelf prices, read from the
        # products themselves (never typed into the page).
        "price_board": "Fresh produce",
    },
}

DEFAULT = "maqam"


def current():
    """The brand this copy of the system is running as."""
    return BRANDS.get(getattr(settings, "SHOP_BRAND", DEFAULT), BRANDS[DEFAULT])


def template(name):
    """This shop's own version of a screen, or the shared one."""
    return current().get("templates", {}).get(name, name)


def icon(name):
    """The static path of one of this shop's phone-app icons, e.g. app-192.png."""
    return current()["static_dir"] + name
