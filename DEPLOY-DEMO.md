# The demonstration shop — `supermarket.campusnect.com`

**FreshWay Supermarket, Nakawa** — a made-up shop running the exact same
system as MAQAM, so that other shop owners can sign in and try it. It sits on
the same CampusNect server (InterServer VPS **205.209.125.253**) as MAQAM and
shares nothing with it, exactly the way MAQAM shares nothing with CampusNect:

| | MAQAM (real shop) | FreshWay (demo) |
|---|---|---|
| Linux user | `maqam` | `smdemo` |
| Folder | `/home/maqam` | `/home/smdemo` |
| Settings file | `/home/maqam/maqam.env` | `/home/smdemo/smdemo.env` |
| Service | `maqam`, port 8077 | `smdemo`, port 8078 |
| nginx site | `maqam` | `smdemo` |

Restarting, updating or resetting the demo never touches MAQAM.

**Already true — nothing to do:**
- **DNS.** The `*` wildcard record already sends `supermarket.campusnect.com`
  to this server, exactly as it did for `maqam.`.
- **HTTPS.** The server's certificate is a wildcard for `*.campusnect.com`,
  so it covers `supermarket.` too. **Do not run certbot.** The nginx script
  reuses that certificate, the same way MAQAM's does.
- Until step 1 is done, `supermarket.campusnect.com` shows Team University's
  page — CampusNect's wildcard is catching it. Step 1 changes that.

**What makes it a demo** is two lines in its settings file: `SMMS_BRAND=freshway`
(its own name, mark, app icons and opening animation) and `SMMS_DEMO=1` (the
"Demo" marker, the seed command allowed, and **SMS can never send** — there
are no SMS or email settings in its file at all).

**Before you start:** the code with the demo in it must be on GitHub. On your
computer, in the SUPERMARKET folder: `git push origin main`.

---

## 1. Install it — once

As **root**, **one line at a time**. Lines starting `nano` open a file to fill
in; everything else is pasted as it is.

```bash
adduser --system --group --home /home/smdemo --shell /bin/bash smdemo
cd /home/smdemo
sudo -u smdemo git clone https://github.com/jalen-projects/supermarket.git /home/smdemo/app
sudo -u smdemo python3 -m venv /home/smdemo/venv
sudo -u smdemo /home/smdemo/venv/bin/pip install -r /home/smdemo/app/supermarket_system/requirements.txt
ss -ltn | grep ':8078 ' || echo "port 8078 is free"
cp /home/smdemo/app/deploy/smdemo.env.example /home/smdemo/smdemo.env
echo "SMMS_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" >> /home/smdemo/smdemo.env
nano /home/smdemo/smdemo.env
chown smdemo:smdemo /home/smdemo/smdemo.env && chmod 600 /home/smdemo/smdemo.env
cd /home/smdemo/app/supermarket_system
sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py migrate
sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py collectstatic --noinput
sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py seed_demo_shop
cp /home/smdemo/app/deploy/smdemo.service /etc/systemd/system/smdemo.service
systemctl daemon-reload && systemctl enable --now smdemo
systemctl status smdemo --no-pager
bash /home/smdemo/app/deploy/install_nginx_demo.sh
```

What the non-obvious lines do:

- **`ss -ltn | grep ':8078 '`** must print **`port 8078 is free`**. If it
  prints a line instead, something already uses 8078 — stop and ask.
  (MAQAM is on 8077; that is expected and is not this.)
- **The `echo "SMMS_SECRET_KEY=..."` line** makes a fresh secret key for the
  demo on the server. It is never written anywhere else.
- **In `nano`** change ONE line, then Ctrl+O, Enter, Ctrl+X:
  - `DEMO_PASSWORD=` the demo password — the one printed on the first page of
    *FreshWay Supermarket Demo - Logins and Test Guide.pdf*. Type it exactly,
    capitals and `@` included, with no spaces.
  Leave every other line as it is. **Do not add SMS, email or Flutterwave
  lines** — a demo has nobody to text.
- **`seed_demo_shop`** fills the shop: about 150 products, suppliers,
  deliveries, customers and a month of sales. **It takes a few minutes** and
  ends with **`FreshWay Supermarket is ready: ... products, ... receipts`**.
  If it says `DEMO_PASSWORD is not set`, the `nano` step was missed — do it
  and run the line again; nothing was changed.
- **`systemctl status smdemo`** must say **active (running)**. Press `q`.
- **`install_nginx_demo.sh`** must end with **`nginx now serves
  supermarket.campusnect.com from the demo shop system.`** If `nginx -t`
  complains, nothing was reloaded and MAQAM and CampusNect are untouched.

**Did it land?** Open https://supermarket.campusnect.com — the sign-in page
says **FreshWay Supermarket** with a green **F** and an orange, and the
receipt on it has a line **DEMO — A demonstration shop**. Sign in as `owner`
with the demo password. Then open https://maqam.campusnect.com and check that
MAQAM still shows MAQAM.

### A fresh month every night (recommended)

Visitors ring up sales, void receipts and change prices. `crontab -e` as root
and add this line **below the `#end` marker**, under MAQAM's two lines:

```cron
30 3 * * * cd /home/smdemo/app/supermarket_system && sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py seed_demo_shop --reset >> /var/log/smdemo_reset.log 2>&1
```

At 03:30 it throws away everything visitors did and builds a fresh thirty days
ending that day, and puts every demo login back to the demo password. MAQAM's
data is in a different folder and a different database; this line cannot
reach it — and the command refuses to run anywhere `SMMS_DEMO=1` is not set.

To reset it by hand right now (for example just before showing a client):

```bash
cd /home/smdemo/app/supermarket_system
sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py seed_demo_shop --reset
```

---

## Updating it later

As root, one line at a time — the same steps as MAQAM's, with `smdemo` in
place of `maqam`:

```bash
cd /home/smdemo/app && sudo -u smdemo git pull
sudo -u smdemo /home/smdemo/venv/bin/pip install -r /home/smdemo/app/supermarket_system/requirements.txt
cd /home/smdemo/app/supermarket_system
sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py migrate
sudo -u smdemo env SMMS_ENV_FILE=/home/smdemo/smdemo.env /home/smdemo/venv/bin/python manage.py collectstatic --noinput
systemctl restart smdemo
```

The restart is not optional: the templates are cached in memory, so a
`git pull` alone leaves the old screens showing.

## When something is wrong

```bash
systemctl status smdemo --no-pager     # is it running?
journalctl -u smdemo -n 50 --no-pager  # its errors
tail -n 20 /var/log/smdemo_reset.log   # what last night's reset said
```

## Taking it down

```bash
systemctl disable --now smdemo
rm /etc/nginx/sites-enabled/smdemo && nginx -t && systemctl reload nginx
```

`supermarket.campusnect.com` then falls back to CampusNect's wildcard page.
The folder `/home/smdemo` is left in place; nothing of MAQAM's is touched.
