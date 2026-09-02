# Putting the demo online, so the client can see it from where he is

The supermarket system is an **offline** system. That has not changed. What
follows puts a **second, throwaway copy** of it on the internet purely so the
client can open it on his phone, click around, and tell you what he wants
different — without you carrying a computer to him.

Two copies, two different jobs:

|                | The shop's copy                  | The demo copy                       |
| -------------- | -------------------------------- | ----------------------------------- |
| Where it runs  | His computer, in the shop        | Render, on the internet             |
| Data           | Real, and kept forever           | Fake, and wiped on every restart    |
| Needs internet | No                               | Yes                                 |
| Installed by   | `INSTALL.bat`                    | `render.yaml` + `build.sh`          |

Nothing in this repository makes the shop's copy talk to the internet. The
online hardening in `smms/settings.py` only switches on when `SMMS_ONLINE=1`,
and only the demo sets that.

---

## Setting it up (about 10 minutes, once)

1. Push this repository to GitHub, if you have not already.

2. Go to **render.com** and sign in **with GitHub**. The free plan is enough —
   no card is asked for.

3. **New → Blueprint**, choose the `jalen-projects/supermarket` repository, and
   let it read `render.yaml`. Everything is already filled in.

4. It will stop and ask you for one value: **`MAQAM_OWNER_PASSWORD`**. This is
   the password the client will use. Type one you are happy to send him over
   WhatsApp. It is stored on Render, never in this repository.

   **This repository is public**, so his password cannot live in the code — put
   it here and nowhere else. If you skip this step the demo still builds, but
   his account is locked with a random password nobody has, and you will have
   to set the variable and deploy again.

5. Click apply and wait roughly five minutes for the first build.

6. The address will be **`https://maqam-food-city.onrender.com`** (Render will
   confirm the exact one — if that name is taken it appends something).

---

## What to send him

> Here is the supermarket system, running online so you can look at it from
> your phone or laptop:
>
> **https://maqam-food-city.onrender.com**
> Username: **maqam**
> Password: *(the one you set in step 4)*
>
> Two things to know. The first page may take about a minute to open if nobody
> has used it for a while — that is the free hosting waking up, not the system
> being slow. And everything in it is **practice data**, so please open
> anything, sell anything, change anything. You cannot break it.
>
> Write down whatever you want changed and we will go through it together.

The code itself is at **https://github.com/jalen-projects/supermarket** if he
ever wants to show it to someone technical. Do not send him only that link —
he would have to install Python and Django to see anything.

---

## Things to know before he asks

**It sleeps.** On the free plan the site shuts down after 15 minutes with no
visitors, and takes 30–60 seconds to wake up on the next click. Warn him, or
he will think the system is slow. Paying about $7 a month removes this.

**The data resets.** The demo database is rebuilt from `build.sh` on every
deploy and every wake-up. This is deliberate: he can do anything at all and it
tidies itself. But it also means **anything he types in there is not kept** —
if he enters his real products to try it out, they will vanish. Tell him that
plainly, or he will be annoyed later.

**It is a real login, on the real internet.** Only give the address to him.
The demo also contains the two demo cashier accounts (`moses` and `aisha`,
password `till1234`) so he can see what a cashier sees versus what the owner
sees — those passwords are in the source code, which is one more reason the
demo holds nothing real.

---

## Changing what he sees

Anything about the shop's identity — name, logo, phone, address, receipt
wording — lives in one place:

```
supermarket_system/shop/management/commands/setup_maqam.py
```

Edit it, push, and Render rebuilds with the change. The same command is what
you run on his real installation:

```
venv\Scripts\python.exe manage.py setup_maqam
```

It is safe to run repeatedly — it only rewrites the shop's identity and his
password, and never touches stock or sales.

> **Still to fill in:** the address and phone in that file are placeholders
> (`Kampala, Uganda` / `0700 000 000`). They print on every receipt, so get his
> real ones and correct them.

## The logo

Two files in `supermarket_system/static/brand/`, both drawn from the same mark
— an **M** whose shoulders are two market arches, standing on a counter:

- **`maqam-logo.svg` / `.png`** — green on transparent. This is the one the
  system uses, on screen and on receipts. It stays light on a thermal roll.
- **`maqam-icon.svg` / `.png`** — the mark reversed out of a solid green tile,
  for signage, a WhatsApp display picture, or a desktop shortcut.

The `.svg` files are the masters; they can be scaled to any size without going
blurry. Send him both and let him say whether he likes it.
