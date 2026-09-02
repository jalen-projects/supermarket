#!/usr/bin/env bash
# Build step for the online demo. Render runs this once per deploy.
#
# The free plan gives the container no permanent disk: it is rebuilt from this
# script every deploy, and reset back to this state whenever the instance
# wakes from sleep. So the demo database is created here, from scratch, every
# time - which is why the client can click around freely and never break it.
#
# THIS IS THE DEMO ONLY. The shop's real installation is INSTALL.bat and it
# keeps its data forever.
set -o errexit

pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Reference data (units, categories) and the administrator account. The
# password is never defaulted here the way INSTALL.bat may do it - this box is
# on the public internet, so it comes from the environment or the account is
# left out entirely.
if [ -n "$SMMS_ADMIN_PASSWORD" ]; then
  python manage.py setup_shop \
    --company "MAQAM FOOD CITY SUPERMARKET" \
    --username admin --password "$SMMS_ADMIN_PASSWORD"
else
  echo "SMMS_ADMIN_PASSWORD not set - creating a throwaway one."
  python manage.py setup_shop \
    --company "MAQAM FOOD CITY SUPERMARKET" \
    --username admin --password "$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
fi

# A week of believable trading, then the branding and his login over the top.
# Order matters: load_demo needs the units and categories setup_shop creates,
# and setup_maqam must run last so its branding wins.
python manage.py load_demo
python manage.py setup_maqam
