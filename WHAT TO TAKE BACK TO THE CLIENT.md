# Supermarket Management System — what to show the client, and what to ask him

A working system has been built from the feature list on his paper. Take him through it
on a laptop; it runs without internet, which is itself part of the pitch.

It is branded as **MAQAM FOOD CITY SUPERMARKET**, with a logo, on screen and on every
printed receipt.

**If you cannot get to him in person,** there is a copy of it online he can open from
his own phone — see `DEMO.md` for how to put it up and exactly what to send him. Walk
the same ten-minute order below with him over a call.

> **He has since sent back a list of questions** (photographed at
> `supermarket challenges.jpeg`) and asked whether more than one computer could share
> the data. All of it is answered in **`ANSWERS TO THE CLIENT'S QUESTIONS.md`**, and the
> system was changed so each answer is now on the screen rather than in a phone call.
>
> **He is confirmed on two computers.** Nothing more is needed in the system for that;
> it decides a second receipt printer and a UPS on the server, which is a conversation,
> not a change.
>
> **He checks it online at the Render URL.** That is the copy he browses from his phone
> — the offline install is what actually runs the shop. Send him the Render link and
> `ANSWERS TO THE CLIENT'S QUESTIONS.md` together.
>
> **He does not need walking through it any more.** The system now offers him a guided
> tour the first time he signs in, and he can restart it from **How do I…?** whenever he
> likes. Let him run that before you spend an hour on the phone.

---

## 1. Show him his own list, working

Open the system and walk it in this order. It takes about ten minutes.

1. **Let the tour run.** On a fresh account the system offers to show him round. It is
   three minutes and it covers most of what follows, in his own words.
2. **Sign in as a cashier.** Point out that the receipt will carry *this* person's name —
   that is his "Served by (seller)".
3. **Make a sale.** Scan or type an item, change a quantity, take cash, press F9. The
   receipt prints with his shop name, the date, the seller and "Walk-in customer".
4. **Sign in as the owner.** Show that the cashier could not see buying prices, profit,
   or any report — only the owner can.
5. **Dashboard.** Today's takings, low stock, and what has expired on the shelf.
6. **Purchases → Receive a delivery.** This is his "Purchase". Enter quantity, buying
   price and expiry date, press Receive, and watch the stock rise.
7. **Stock available.** His shelves valued twice: what they cost him, and what they will
   fetch. The difference is profit still sitting on the shelf.
8. **Expiry watch.** What has expired and what expires soon, with the money at stake.
   Show him that the till *refuses* to sell an expired item.
9. **Profit report.** Selling price less buying price, per product, ranked.
10. **Backup.** One click. Tell him plainly: no backup, no shop.

---

## 2. What his list did not cover

Raise these as questions, not as extras you have already built. Some are done; the last
few are genuinely new work and should be priced.

**Already built, mention them as value:**

- Voiding a wrong receipt (goods go back to stock, receipt kept and marked VOIDED)
- Discounts, and VAT if he charges it
- Payment method — cash, mobile money, card, or credit
- Credit customers, with a running balance
- Cashier vs owner permissions
- A full history of every movement of stock, with who did it
- Export to Excel
- **Stock take**, shelf by shelf, with a variance sheet showing what the gap is worth
- **Several tills on one shop network**, all sharing the same books, still offline

**Questions to put to him:**

| Question | Why it matters |
|---|---|
| His **exact address and phone number** | Currently placeholders, and they print on every single receipt |
| Does he approve the **logo**? | Drawn for him; easy to change now, awkward once it is on printed material |
| Does he charge **VAT**, and is he on **EFRIS**? | EFRIS means sending each invoice to URA — that needs internet and is a separate job |
| Does he ever **return goods to a supplier**? | Not built yet; different from voiding a sale |
| Does he give **customer refunds**? | Currently handled by voiding the whole receipt |
| Does he want **loyalty or discount cards**? | Extra work |
| Does he have a **barcode scanner** and a **receipt printer**? | The system supports both, but he must buy them; both are inexpensive |
| Does he sell anything by **weight at the till** (a scale)? | Scale integration is a separate job. Typing 2.5 kg already works |
| ~~How many people will use it at once?~~ | **Answered: two computers.** One runs the system, the second opens a browser. Now decides printers and a UPS, not code |
| Does he already have a **stock list on paper or Excel**? | Bulk-importing it saves days of typing — quote for it |
| Who **counts stock**, and how often? | There is now a full **Stock take** screen with a variance report — this is his best defence against shrinkage |
| What happens when the **power goes off**? | Strongly recommend he buy a UPS, or run it on a laptop |

---

## 3. Things to tell him honestly

- **This is offline.** He owns the data. But it also means he owns the risk: if that
  computer dies and no backup was taken, the records are gone. Insist on a daily backup
  to a flash disk kept away from the shop. Consider charging for a small monthly
  check-in that verifies backups are actually being made.
- **Rubbish in, rubbish out.** The reports are only as good as the buying prices and
  expiry dates entered on deliveries. Budget real time for training whoever receives
  goods, not just the cashiers.
- **Entering the opening stock is the biggest single task** at setup, and it is his
  staff's job as much as yours. Price it, or agree in writing that he does it. The
  Stock take screen makes it far quicker, but somebody still has to walk the shelves.
- **On a network, the server computer is the shop.** If it is off, every till stops.
  That is the price of one honest set of books, and he should hear it from you before
  he discovers it on a busy Saturday.

---

## 4. What is not built (be straight about this)

- Supplier returns
- Partial refunds on a receipt
- Loyalty cards or customer points
- EFRIS / URA integration
- A weighing-scale connection
- More than one branch

None are hard. All are extra work, and each should be quoted separately rather than
absorbed.

---

## 5. Before quoting

Settle these first:

1. **Who enters the opening stock**, and by when.
2. **How many computers**, and whether the shop already has a network.
3. **Training** — how many staff, and how many sessions.
4. **Support after handover** — how long, and what it covers. Put an end date on it, or
   it never ends.
5. **What happens when he asks for a change** six months from now.
