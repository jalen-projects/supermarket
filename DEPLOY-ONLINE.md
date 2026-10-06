# MAQAM online — `maqam.campusnect.com`

The shop system running on the CampusNect server (InterServer VPS
**205.209.125.253**) instead of on the shop's own computer. Every till and
the owner's phone open **https://maqam.campusnect.com**.

It sits beside CampusNect and shares nothing with it: its own Linux user
(`maqam`), its own folder (`/home/maqam`), its own database, its own service
(`maqam`, on `127.0.0.1:8077`) and its own nginx site. Restarting one never
touches the other.

**A second shop runs beside it the same way:** the FreshWay demonstration
shop at `supermarket.campusnect.com` (user `smdemo`, port 8078). Its set-up is
in **DEPLOY-DEMO.md**; nothing in it touches MAQAM.

**Already true, checked on 1 Oct 2026 — nothing to do:**
- **DNS.** `maqam.campusnect.com` already resolves to 205.209.125.253 (the
  `*` wildcard record covers it). No new record is needed.
- **HTTPS.** The certificate the server already has is a wildcard for
  `*.campusnect.com`, so it covers `maqam.` too. **Do not run certbot.** The
  nginx script reuses that certificate.
- Until step 1 is done, `maqam.campusnect.com` shows Team University's page —
  CampusNect's wildcard is catching it. Step 1 is what changes that.

**The database is SQLite in WAL mode, on purpose.** It is one shop with a few
tills, it is the exact database his computer already uses (so moving his data
is a copy, not a conversion), and it is backed up by the same tested code.
PostgreSQL would add a second server process to run and a migration to get
wrong for no gain at this size.

---

## 1. Install it — once

As **root**, **one line at a time**. Lines starting `nano` open a file to fill
in; everything else is pasted as it is.

```bash
adduser --system --group --home /home/maqam --shell /bin/bash maqam
cd /home/maqam
sudo -u maqam git clone https://github.com/jalen-projects/supermarket.git /home/maqam/app
sudo -u maqam python3 -m venv /home/maqam/venv
sudo -u maqam /home/maqam/venv/bin/pip install -r /home/maqam/app/supermarket_system/requirements.txt
ss -ltn | grep ':8077 ' || echo "port 8077 is free"
cp /home/maqam/app/deploy/maqam.env.example /home/maqam/maqam.env
echo "SMMS_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" >> /home/maqam/maqam.env
grep -E '^EMAIL_(HOST|PORT|HOST_USER|HOST_PASSWORD|USE_TLS)=' /home/campusnect/app/.env >> /home/maqam/maqam.env
nano /home/maqam/maqam.env
chown maqam:maqam /home/maqam/maqam.env && chmod 600 /home/maqam/maqam.env
cd /home/maqam/app/supermarket_system
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py migrate
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py collectstatic --noinput
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py setup_maqam --close-spare-admin
cp /home/maqam/app/deploy/maqam.service /etc/systemd/system/maqam.service
systemctl daemon-reload && systemctl enable --now maqam
systemctl status maqam --no-pager
bash /home/maqam/app/deploy/install_nginx.sh
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py watch_tills --test-email
```

What the non-obvious lines do:

- **`ss -ltn | grep ':8077 '`** must print **`port 8077 is free`**. If it prints
  a line instead, something already uses 8077 — stop and ask before going on.
- **The `echo "SMMS_SECRET_KEY=..."` line** makes a fresh secret key on the
  server. It is never written anywhere else.
- **The `grep -E '^EMAIL_...'` line** copies CampusNect's own email settings,
  so the alerts send through the account that already works. It prints
  nothing; that is normal.
- **In `nano`** change three lines, then Ctrl+O, Enter, Ctrl+X:
  - `MAQAM_ALERT_EMAIL=` his Gmail address (add `,` and yours for copies)
  - `MAQAM_OWNER_PASSWORD=` a temporary password — only used until his own
    data arrives in step 2, which brings his real password with it
  - `MAQAM_HOSTING_PAID_UNTIL=` the last day of the year he paid for
    (paid 2 Oct 2026 → `2027-10-01`)
- **`systemctl status maqam`** must say **active (running)**. Press `q` to leave.
- **`install_nginx.sh`** must end with **`nginx now serves maqam.campusnect.com`**.
  If `nginx -t` complains, nothing was reloaded and CampusNect is untouched.
- **`--test-email`** must say **`Test email sent to ...`** — and it must arrive
  on his phone. If it fails, the alerts will fail too; fix the email first.

**Did it land?** Open https://maqam.campusnect.com — the green MAQAM sign-in
page with the arches drawing themselves. Sign in as `maqam` with the temporary
password.

### The scheduled jobs

`crontab -e` as root, and add these **below the `#end` marker** (InterServer's
template owns everything above it):

```cron
*/5 * * * * cd /home/maqam/app/supermarket_system && sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py watch_tills >> /var/log/maqam_watch.log 2>&1
15 23 * * * cd /home/maqam/app/supermarket_system && sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py backup_db >> /var/log/maqam_backup.log 2>&1
```

- The first is **the answer to his fear**. Every five minutes it checks that a
  till has checked in; if none has for 10 minutes while the shop is open
  (07:00–22:00 unless he changes it under *Shop details*), it emails him, and
  emails again when they come back, with how long they were gone. It also
  sends the day's summary after closing. Without this line none of that
  happens.
- The second keeps a nightly copy of his data on the server (30 are kept).

---

## 2. Move his shop's data up — at closing time, once

His shop computer has every product, price and receipt so far. This moves all
of it, including his own password. **Do it after the shop closes**: any sale
made on the old computer after the backup is taken would be left behind.

**At the shop (or ask him):** on the shop computer, sign in → *Backup* →
**Take a backup now** → click the newest file to download it
(`backup_2026-10-…sqlite3`). Send it to yourself (WhatsApp as a *document*,
email, or flash disk).

**From your computer** (PowerShell), put it on the server — change the path to
where the file is:

```powershell
scp "$HOME\Downloads\backup_2026-10-02_220500.sqlite3" root@205.209.125.253:/home/maqam/incoming.sqlite3
```

**On the server**, as root, one line at a time:

```bash
chown maqam:maqam /home/maqam/incoming.sqlite3
cd /home/maqam/app/supermarket_system
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py import_shop_db /home/maqam/incoming.sqlite3 --check
systemctl stop maqam
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py import_shop_db /home/maqam/incoming.sqlite3
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py setup_maqam --close-spare-admin
systemctl start maqam
```

- **`--check` changes nothing.** It prints the shop's name, how many products
  and receipts, the **last sale**, and every login. **Read it.** The last sale
  should be today, near closing time. If it is days old, it is the wrong file —
  stop here.
- The real import keeps a copy of whatever the server held before, refuses a
  damaged file, and signs everybody out.
- `setup_maqam` puts the logo back and **closes the spare `admin` account**
  the installer made (its password was printed on screen in the shop). It
  does **not** touch his password — he signs in with the one he already uses.

**Then, at the shop — this is what makes it real:**

1. On **every** till, open **https://maqam.campusnect.com** and make it the
   browser's home page / desktop shortcut.
2. **Retire the old system.** Close the black *START SUPERMARKET* window on the
   shop computer and delete its desktop shortcut. If anybody starts it again,
   sales go into the old computer and NOT online, and the two never meet.
3. On his phone, open https://maqam.campusnect.com/owner/ and tap **Install the
   app** (on an iPhone: Share → *Add to Home Screen*).

---

## Updating it later

As root, one line at a time:

```bash
cd /home/maqam/app && sudo -u maqam git pull
sudo -u maqam /home/maqam/venv/bin/pip install -r /home/maqam/app/supermarket_system/requirements.txt
cd /home/maqam/app/supermarket_system
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py migrate
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py collectstatic --noinput
systemctl restart maqam
```

The restart is not optional: the templates are cached in memory, so a
`git pull` alone leaves the old screens showing.

## SMS: sign-in codes, texted alerts, his own messages — once

The shop has its own channel on EGO SMS, like St Lucia and Team. With it set
up, everybody signing in online gets a 6-digit code after their password
(cashiers by SMS; the owner by SMS **and** email), the till alerts and the
nightly summary are texted to him as well as emailed, and he can buy SMS
credit and text his top customers or his cashiers from **SMS & messages**.
Until the channel is set up, signing in is the password alone, as before.

**1. Add these lines** to `/home/maqam/maqam.env` (`nano /home/maqam/maqam.env`):

```
MAQAM_SMS_USERNAME=
MAQAM_SMS_KEY=
MAQAM_SMS_SENDER=
MAQAM_SMS_LIVE=0
MAQAM_ALERT_PHONE=
```

- `MAQAM_SMS_USERNAME` / `MAQAM_SMS_KEY` — the **API** username and key of the
  MAQAM channel in the EGO dashboard (not the website login — the wrong pair is
  answered "That user does not exist").
- `MAQAM_SMS_SENDER` — the sender ID EGO approved for that channel, e.g. `MAQAM`.
- `MAQAM_SMS_LIVE` — leave `0` first: every text is recorded and priced, none
  leaves, and sign-in codes are written to `journalctl -u maqam` so you can
  test. Change to `1` once a test sign-in works.
- `MAQAM_ALERT_PHONE` — his mobile for the till alerts, e.g. `07XXXXXXXX`
  (add `,` and yours for copies).
- `FLW_*` — the same three Flutterwave lines as in `/home/campusnect/app/.env`
  (they let him buy SMS credit with Mobile Money or card). To copy them:

```bash
grep -E '^FLW_(PUBLIC_KEY|SECRET_KEY|SECRET_HASH)=' /home/campusnect/app/.env >> /home/maqam/maqam.env
```

  Run it once, after saving the file. Do not also type empty `FLW_` lines -
  the first copy of a setting is the one that counts.

**2. Before switching on:** every cashier needs their mobile number - and,
ideally, their own email - on their account (*Users* → edit). With neither
they cannot sign in online. The owner's account
should have his email and phone.

**3. Apply it** — run the "Updating it later" block above (it migrates and
restarts).

**Credit paid outside the website** (cash, or Mobile Money to +256 708 646603):

```bash
cd /home/maqam/app/supermarket_system
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py sms_credit 20000 --ref "MoMo 1234567890"
```

The reference must be the payment's own, so the same money cannot be added
twice. `... manage.py sms_credit --balance` shows what is left.

**When the credit runs out:** the owner still gets his code by email. A
cashier's code goes to the cashier's own email; only a cashier with no email
of their own has it sent to the owner, and is told to ask him for it — the till keeps selling, nobody gets in without a code, and
he learns at once that it is time to top up.

## When he renews the hosting

Change `MAQAM_HOSTING_PAID_UNTIL` in `/home/maqam/maqam.env` (`nano`), then:

```bash
cd /home/maqam/app/supermarket_system
sudo -u maqam env SMMS_ENV_FILE=/home/maqam/maqam.env /home/maqam/venv/bin/python manage.py setup_maqam
```

The reminder banner disappears as soon as the new date is more than 30 days
away.

## When something is wrong

```bash
systemctl status maqam --no-pager     # is it running?
journalctl -u maqam -n 50 --no-pager  # its errors
tail -n 20 /var/log/maqam_watch.log   # what the five-minute check said
```

## What it can and cannot tell him — say this to him plainly

- It **can** tell him, within about 15 minutes, that every till stopped
  reaching the system while the shop should be open, and exactly how long for.
- It **cannot** tell him *why*. A power cut, the internet provider, and a
  cashier pulling the router all look the same from the server. The email
  says so. A call to the shop answers it.
- Online means **the tills need internet to sell**. A small 4G MiFi kept as a
  backup, and a UPS on the router, are what keep a dead line from stopping the
  shop.
