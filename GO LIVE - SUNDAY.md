# GO LIVE — Sunday 27 September 2026
## MAQAM FOOD CITY SUPERMARKET

This is the whole visit on one page: what to carry, what to do in what order,
what to train, and what to sign before leaving.

Read **THE ONE THING THAT CAN STOP THE DAY** first. Everything else is packing.

---

## THE ONE THING THAT CAN STOP THE DAY

**Is there a wi-fi router in the shop?**

He has **four computers** (2 HP laptops, 2 desktops). Only ONE of them holds the
data. The others reach it through a browser over the shop's own network. If
there is no network in the shop, only one till will work and the visit is half
wasted.

**Ask him before Saturday evening.** Word it plainly, not technically:

> "Is there a wi-fi router in the shop — the box the internet/CCTV uses? Even if it
> has no internet on it, I need to know if it is there. And are the computers near
> each other, or in different corners?"

Three possible answers, three different bags:

| His answer | What to carry |
|---|---|
| **Yes, there is a router** | Nothing extra. The computers join its wi-fi. Easiest case by far. |
| **No router** | A cheap wi-fi router (UGX 80k–150k) — used purely as a LAN box, no internet needed — plus 2 ethernet cables. |
| **Not sure** | Carry the router anyway. Coming back a second time costs more than the router. |

**Fallback if there is no router and no time to buy one:** Windows *Mobile
hotspot* on the server computer creates a network by itself, and the others join
it. It works, but only if the server machine has wi-fi — the two laptops do,
the mini-PC may not. Treat this as the rescue plan, not the plan.

> A shop computer on cable *and* wi-fi shows two different addresses. The
> **Other computers** page in the system lists every address the machine has, so
> use that page rather than guessing. `ALLOW OTHER TILLS.bat` opens the Windows
> firewall — that is nearly always why the second till fails the first time.

---

## WHAT HE ALREADY HAS — confirmed by him on WhatsApp, 25 Sept

Do not buy or carry these:

- ✅ **Thermal receipt printer** — Olina, 80mm, already on the counter
- ✅ **Barcode scanner** — counter-top type, already there
- ✅ **4 computers** — 2 HP laptops (EliteBook), 2 desktops (one is a mini-PC
  mounted behind an Acer monitor). They run Windows and are in working order.

**He does NOT have a stock or price list in any form.** He said so plainly:
*"I don't have the list."* That single fact shapes the entire day — see
**The real work of the day** below.

---

## WHAT TO CARRY

### The flash disk (the most important item)

**Two flash disks, both with the same thing on them.** One is the spare; flash
disks fail, and at the shop there is no way to make another.

Put the whole `SUPERMARKET` folder on each, which now includes:

- `supermarket_system\` — the system itself
- `supermarket_system\wheelhouse\` — **every package it needs, already downloaded**
- `PYTHON INSTALLER\python-3.12.10-amd64.exe` — **Python itself**

> **Why this matters:** until today, installing needed the internet. `INSTALL.bat`
> downloaded Django and the rest from the web. At a shop with no connection it
> would have failed on the first computer and the visit would have ended there.
> It now installs from the `wheelhouse` folder with **no internet at all**.
>
> **Use the carried Python 3.12 installer, not a newer one.** The offline
> packages are built for 3.12. If someone installs Python 3.13 the offline
> install will not fit, and it will try to reach the internet and fail.
> On the Python installer's first screen, **tick "Add python.exe to PATH"**.

### Hardware

| Item | Why |
|---|---|
| **Her laptop** | To work from, and as the emergency fourth machine |
| **Extension cable / multi-socket** | Four machines and a printer on one counter |
| **Ethernet cables ×2 + router** | Only if his answer above says so |
| **Spare 80mm thermal rolls ×2** | Testing receipts burns a roll, and a shop that runs out blames the system |
| **Her phone with data** | The rescue line for anything not anticipated — a driver, a lookup |
| **Masking tape + marker** | Label the server machine **SERVER — DO NOT SWITCH OFF**. This prevents the single most common disaster |
| **Screwdriver, cable ties** | Tidying the counter so cables are not pulled out by customers |
| **Her own flash disk for backups** | Leave one **with him** as the shop's backup disk |

### Strongly recommended, not essential

- **A UPS for the server machine** (UGX 150k–250k). Kampala power cuts on a
  machine mid-sale is exactly the situation SQLite dislikes. If a UPS is
  impossible, the **server must be one of the two laptops** — a laptop battery
  *is* a UPS. This is the cheaper and better answer.

### Paperwork — the "clean money" half

| Document | Status |
|---|---|
| **Quotation / Invoice** — 2 copies, both signed | `INVOICE - MAQAM.md`, **fill in the agreed figure before printing** |
| **Handover & Acceptance form** — 2 copies | `HANDOVER AND ACCEPTANCE.md` — he signs, she signs, each keeps one |
| **`ANSWERS TO THE CLIENT'S QUESTIONS.md`** | Print it. This is the thing still owed to him from the last round |
| **A receipt** for the money he pays | Do not leave without giving him one |
| Her mobile money / bank details | In case he pays part now, part later |

---

## THE REAL WORK OF THE DAY

He has no list. So the day is **not** an installation — installing takes forty
minutes. The day is **data capture**: getting what is on his shelves into the
system. That is what will consume the hours, and it is where the visit succeeds
or fails.

**Two new screens were built this week for exactly this:**

### 1. Stock capture — `Stock → Stock capture (scan the shelves)`

Built for one job: standing at the counter with the scanner and an item in hand.

- Scan → type name, buying price, selling price, how many → **Enter** → the
  cursor is back on the barcode box for the next item.
- **Never needs the mouse.** Enter walks through the boxes. **F2** jumps back to
  the barcode box if the cursor gets lost.
- The category stays put between items, so a whole shelf goes in fast.
- Scanning something already captured **tops up the quantity** instead of
  complaining — the same item always turns up on a second shelf.

### 2. Import a list — `Products → Import a list`

If someone types into Excel while another person calls out items, the whole
sheet goes in at once. A template is downloadable from that screen.

- Reads `12,500` and `UGX 12500` correctly.
- Reads dates **day-first** — `03/04/2027` is 3 April.
- **Shows exactly what it will do before writing anything.** Nothing is saved
  until the preview is confirmed.
- Importing the same file twice **cannot** double his stock. It is refused
  unless explicitly asked for.

### How to actually run the capture

**Do not try to capture the whole supermarket.** It will not finish, and a
half-captured shop that was promised to be finished is a worse outcome than an
honestly partial one.

1. **Ask him: "which fifty items do you sell most?"** Capture those first.
2. Then work shelf by shelf, category by category, in the order he trades.
3. **Two people, two roles:** he (or his cashier) reads out the name and the two
   prices, she types. He *must* be the one giving prices — she cannot invent
   them, and involving him means he trusts the numbers afterwards.
4. **Tell him plainly:** *"Anything not yet captured cannot be sold through the
   system. Keep capturing every evening — it takes a week, not a day."*

He needs to be taught to do this himself, or the system stops at whatever was
captured on Sunday.

---

## ORDER OF THE DAY

### 1. Before touching anything (15 min)
- Greet, sit, and agree what "finished today" means. Say out loud that the shelves
  will not all be captured today. Agree which computer is the **server**.
- **Pick the server:** prefer a **laptop** (its battery survives a power cut).
  It must be the machine that stays on the counter and stays switched on.

### 2. Install on the server (30 min)
- Run the Python installer — **tick "Add python.exe to PATH"**.
- Copy the `supermarket_system` folder to `C:\MAQAM` (short path, no spaces).
- Run `INSTALL.bat`. It installs offline from `wheelhouse`.
- Run `manage.py setup_maqam` to apply the shop's name, logo and his login.
- Run `START SUPERMARKET.bat`. Label the machine **SERVER — DO NOT SWITCH OFF**.

### 3. Printer and scanner (20 min)
- Print a test receipt. In the browser's print dialog set the paper to **80mm**
  and margins to **None**, then tick "remember". A receipt that prints across
  three pages is a paper-size setting, not a system fault.
- Test the scanner **into the till screen** — it types like a keyboard, so it
  should just work. Check it ends with Enter.

### 4. The other three machines (20 min)
- Run `ALLOW OTHER TILLS.bat` **on the server**.
- Open the **Other computers** page on the server, read the address, and type it
  into the browser on each other machine.
- **Bookmark it** and put the shortcut on each desktop. He will not retype an
  address every morning.
- Nothing is installed on these machines. Say that clearly — it reassures him.

### 5. Capture stock — the rest of the day
As above. Start with the fast movers.

### 6. Users, then training (45 min)
- Create a login for **each** cashier by name. Never one shared login — the
  cash-up and the "served by" line on the receipt are worthless if two people
  share an account.
- Keep **`maqam` / ADMIN** for him alone. Only ADMIN sees buying prices and profit.
- Walk him through the guided tour in the system. Then hand him the
  **"How do I…?"** page and show him it answers the five things he asked last time.

### 7. Cash-up training — do not skip this (20 min)
This is the new thing that protects **his** money. See below.

### 8. Backup (15 min)
- Press **Back up now**, then **copy it to the flash disk you are leaving with him**.
- Show him `BACKUP NOW.bat` on the desktop.
- Tell him the rule in one sentence: **"Every evening, press it, and take the
  flash disk home with you."** A backup left in the shop does not survive a theft.

### 9. Sign and get paid (15 min)
Do not leave this until everyone is tired at the door. See **Leaving with clean
money**.

---

## CASH-UP — the new feature, and the one he will care about most

He has cashiers. Until this week the system could tell him *what was sold* but
not *whether the money was handed over*. That gap is now closed.

**How it works, in his language:**

- A cashier's drawer **opens by itself** the first time they sell something.
  Nobody has to remember to start a shift.
- At handover, the cashier opens **Cash up**, counts the notes in the drawer,
  and types the total.
- The system compares that against what it expected: **the change money they
  started with, plus every sale paid in cash.**
- Mobile money, card and credit sales are **deliberately excluded** — that money
  never reaches the drawer, and counting it would accuse an honest cashier.
- The result is a printed **cash-up sheet** the cashier signs with the money.
- **A cashier cannot see the expected figure before they count.** If they could,
  they would write down the target and the control would be worthless.
- He opens **Cash-ups & shortages** to see every drawer, who balanced and who
  did not.

**Teach him this sentence:** *"One bad day is a mistake. The same name short,
again and again, is not."*

Also point out: **voided sales are counted on the cash-up sheet.** Ringing up a
sale, taking the cash, then voiding it is the oldest way to empty a till, and
he should ask why whenever the number is not zero.

---

## LEAVING WITH CLEAN MONEY

The mistake to avoid is installing everything, training everybody, and *then*
raising money at the door when everyone is tired and he is happy but distracted.

1. **Agree the figure before Sunday, over WhatsApp, in writing.** It is already
   agreed — get it restated in a message so there is a record.
2. **Bring the invoice already filled in.** An invoice written by hand at the
   counter looks improvised and invites negotiation.
3. **Do the handover form BEFORE the goodbye.** Sit down, go through the
   checklist together, both sign. The form is what makes the work visible —
   without it he only remembers the hours of typing, not the system.
4. **Take the money and give a receipt.** If he pays part, write the balance and
   the date it is due **on both copies** and have him initial it.
5. **Be explicit about what is NOT included**, so the next request is a new job
   and not a free favour:
   - Supplier returns, partial refunds, loyalty/points
   - EFRIS / URA integration
   - Weighing-scale integration
   - A second branch
   - Capturing the remaining shelves for him
   - Anything after the agreed support period

   These are listed on the handover form on purpose. Going through them takes
   two minutes and saves months of "can you just…".

6. **Agree the support arrangement out loud**: what is free (phone help for
   settling in), for how long, and what is chargeable after. Write it on the form.

---

## WHAT TO SAY, AND WHAT NOT TO PROMISE

**Say:**
- "The shelves will take about a week of evenings to capture fully. I will show
  you how so you are not waiting for me."
- "Take the flash disk home every night. That is your insurance."
- "This machine stays on. The others just open a browser."

**Do not promise:**
- EFRIS or URA receipts. Not built, and not a small job.
- That it works without the server machine on. It does not.
- Anything over the internet from his home. It is a shop-network system.
- That the address and phone on the receipt are final — **they are still the
  placeholders** `Kampala, Uganda` / `0700 000 000`. **Ask him for the real ones
  on the day and change them in Setup → Shop details** while sitting with him. It
  prints on every receipt, so it is worth the two minutes.

---

## WHAT TO CHECK BEFORE LEAVING THE SHOP

- [ ] A real sale rung up on the till, paid, receipt **printed on the thermal printer**
- [ ] The **scanner** adds an item on the till screen
- [ ] **A second computer** made a sale — proving the network works
- [ ] A **cash-up** completed and printed by an actual cashier, not by her
- [ ] **A backup taken and copied onto the flash disk left with him**
- [ ] He signed into **his own** ADMIN account and saw buying prices
- [ ] A cashier signed in and **could not** see buying prices
- [ ] Shortcuts on every desktop, all four machines
- [ ] The server machine is **labelled**
- [ ] Shop name, address and phone correct on a printed receipt
- [ ] **Handover form signed, invoice given, money received, receipt issued**
