"""
Django settings for the Supermarket Management System (SMMS).

This system is designed to run OFFLINE on the shop's own computer.
Nothing is sent to the internet. All data lives in db.sqlite3 next to this file.

There is one exception, and it is deliberately opt-in: setting SMMS_ONLINE=1
hardens the same code for the internet: first the throwaway demo he browsed
from his phone (DEMO.md), and since October 2026 the shop itself, live at
maqam.campusnect.com (DEPLOY-ONLINE.md). A copy installed on a shop computer
never sets it, so nothing below changes there.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path):
    """KEY=value lines from the online server's private settings file.

    The service and the five-minute cron job both start through this, so they
    can never disagree about a setting - and a password full of $ and # signs
    is read as written, which sourcing the file in a shell would not do.
    Anything already in the real environment wins.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key, value)


if os.environ.get("SMMS_ENV_FILE"):
    _load_env_file(os.environ["SMMS_ENV_FILE"])

# Are we the public demo rather than the shop's own machine?
ONLINE = os.environ.get("SMMS_ONLINE", "0") == "1"

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Generated once and kept on the shop's machine. It never leaves the building.
# The demo host has no permanent disk, so there it comes from the environment
# instead - otherwise every restart would invalidate everyone's session.
if os.environ.get("SMMS_SECRET_KEY"):
    SECRET_KEY = os.environ["SMMS_SECRET_KEY"]
else:
    SECRET_KEY_FILE = BASE_DIR / ".secret_key"
    if SECRET_KEY_FILE.exists():
        SECRET_KEY = SECRET_KEY_FILE.read_text().strip()
    else:
        from django.core.management.utils import get_random_secret_key

        SECRET_KEY = get_random_secret_key()
        SECRET_KEY_FILE.write_text(SECRET_KEY)

# Set SMMS_DEBUG=1 while developing.
DEBUG = os.environ.get("SMMS_DEBUG", "0") == "1"

# Offline / LAN only. "*" is safe here because the server is never exposed
# to the internet - it is bound to the shop's own machine or its local network.
ALLOWED_HOSTS = ["*"]

if ONLINE:
    # Facing the internet, so name the one hostname we answer to. Render
    # supplies it; SMMS_HOSTNAME covers any other host or a custom domain.
    _hosts = [h for h in (os.environ.get("RENDER_EXTERNAL_HOSTNAME"),
                          os.environ.get("SMMS_HOSTNAME")) if h]
    if _hosts:
        ALLOWED_HOSTS = _hosts
        CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in _hosts]

    # The app speaks plain HTTP to the platform's proxy, which terminates TLS.
    # Without this Django thinks every request is insecure and the secure
    # cookies below would never be sent back.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.humanize",
    "django.contrib.staticfiles",
    "shop",
    "inventory",
    "sales",
    "reports",
    "sms",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Serves the CSS, JavaScript and logo. Without this the shop's screens
    # load with no styling at all once DEBUG is off.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "smms.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "shop.context_processors.shop_settings",
            ],
        },
    },
]

WSGI_APPLICATION = "smms.wsgi.application"

# ---------------------------------------------------------------------------
# Database - a single SQLite file. Backing up the shop = copying this file.
#
# More than one till can use this system at the same time. They do NOT each
# keep their own copy: one computer runs the server and holds the only
# database, and the other computers reach it over the shop's own network with
# a browser. Everything below is what makes that safe.
#
#   journal_mode=WAL   Readers no longer block the writer and the writer no
#                      longer blocks readers. Without it, one cashier saving a
#                      sale freezes every other screen in the shop for the
#                      length of the write. This is the single most important
#                      line for a second till.
#   synchronous=NORMAL Under WAL this is still crash-safe for the database.
#                      Full fsync on every commit makes a cheap shop PC crawl.
#   transaction_mode   IMMEDIATE takes the write lock at the start of a
#                      transaction rather than half way through, which is what
#                      turns "database is locked" errors into a short wait.
#   timeout            How long a till waits for the lock before giving up.
#                      20 seconds is far longer than any write here takes.
#
# WAL keeps db.sqlite3-wal and db.sqlite3-shm alongside the database. The
# backup screen already copies through Django rather than the raw file, so it
# is not affected - but if anyone ever copies the file by hand, they must copy
# all three or take the copy while the system is stopped.
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {
            "timeout": 20,
            "transaction_mode": "IMMEDIATE",
            "init_command": (
                "PRAGMA journal_mode=WAL;"
                "PRAGMA synchronous=NORMAL;"
                "PRAGMA busy_timeout=20000;"
                "PRAGMA foreign_keys=ON;"
            ),
        },
    }
}

AUTH_USER_MODEL = "shop.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 4}},
]

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

# ---------------------------------------------------------------------------
# Localisation - Uganda
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Kampala"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ONLINE, EVERY STYLE AND SCRIPT IS NAMED BY ITS CONTENT (app.3f9c1a2b.css),
# so a phone may keep it for a year without ever asking again - the server
# is an ocean away from the shop and every question costs ~0.4 s - and the
# day it changes it has a new name, so nobody is left looking at the old
# design. Offline, on the shop PC, the plain names stay: there is no ocean.
if ONLINE:
    STORAGES["staticfiles"] = {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}
    # A file missing from the manifest falls back to its plain name rather
    # than taking the page down.
    WHITENOISE_MANIFEST_STRICT = False

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Where automatic backups of db.sqlite3 are written.
BACKUP_DIR = BASE_DIR / "backups"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Session lasts the working day; a cashier stays logged in through their shift.
SESSION_COOKIE_AGE = 60 * 60 * 12
# Deliberately off. Re-saving the session on every request means a database
# WRITE on every page view, and with three tills open that is the busiest
# writer in the shop - all of it to extend a cookie that already lasts longer
# than a shift. Sessions still save whenever something in them changes.
SESSION_SAVE_EVERY_REQUEST = False

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ---------------------------------------------------------------------------
# Email - online only
# ---------------------------------------------------------------------------
# The shop's own computer has no mail server and nothing to say to anyone, so
# with no EMAIL_HOST set every message is quietly dropped. Online, the server
# emails the owner when the tills go silent and with each night's summary.
# The SMTP values are the same ones CampusNect's own server already uses -
# DEPLOY-ONLINE.md copies them across rather than inventing a second account.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True").lower() in ("1", "true", "yes")
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
    else "django.core.mail.backends.dummy.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get(
    "SMMS_FROM_EMAIL",
    f"Shop system <{EMAIL_HOST_USER}>" if EMAIL_HOST_USER else "shop@localhost")

# Who hears about silent tills and gets the nightly summary. Comma-separated,
# and kept in the server's environment rather than in this public repository.
OWNER_ALERT_EMAILS = [e.strip() for e in
                      os.environ.get("MAQAM_ALERT_EMAIL", "").split(",") if e.strip()]

# The address written into the alert emails' links.
PUBLIC_HOSTNAME = os.environ.get("SMMS_HOSTNAME", "")


# ---------------------------------------------------------------------------
# SMS - the shop's own EGO channel (see sms/). ONLINE ONLY.
# ---------------------------------------------------------------------------
# All of it from the server's environment: this repository is public, and the
# channel's API key would let anybody text in the shop's name on its credit.
# Offline, on the shop PC, there is no SMS at all and signing in is exactly as
# it always was.
SMS_USERNAME = os.environ.get("MAQAM_SMS_USERNAME", "").strip()
SMS_KEY = os.environ.get("MAQAM_SMS_KEY", "").strip()
SMS_SENDER = os.environ.get("MAQAM_SMS_SENDER", "").strip()
# Until this is 1 every message is recorded and costed, and nothing leaves.
SMS_LIVE = os.environ.get("MAQAM_SMS_LIVE", "0") == "1"
SMS_CONFIGURED = ONLINE and bool(SMS_USERNAME and SMS_KEY and SMS_SENDER)
# What one page costs the shop, in UGX - the same as St Lucia and Team.
SMS_PRICE = int(os.environ.get("MAQAM_SMS_PRICE", "45") or 45)
# The owner's phone(s) for the till alerts, comma-separated.
OWNER_ALERT_PHONES = [p.strip() for p in
                      os.environ.get("MAQAM_ALERT_PHONE", "").split(",") if p.strip()]
# Buying SMS bundles online (Flutterwave - CampusNect's account).
FLW_PUBLIC_KEY = os.environ.get("FLW_PUBLIC_KEY", "")
FLW_SECRET_KEY = os.environ.get("FLW_SECRET_KEY", "")
FLW_SECRET_HASH = os.environ.get("FLW_SECRET_HASH", "")
