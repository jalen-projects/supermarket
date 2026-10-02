---
name: MAQAM FOOD CITY SUPERMARKET
description: The shop's till roll as the material of its own system - warm charcoal, thermal paper, one persimmon.
colors:
  persimmon: "#c8481a"
  persimmon-deep: "#a23a12"
  persimmon-on-dark: "#e2662f"
  persimmon-pale: "#f3c4ab"
  persimmon-wash: "#fbece4"
  charcoal: "#1d1612"
  charcoal-raised: "#2b1e17"
  ink-soft: "#5e524b"
  ink-faint: "#8e8079"
  thermal-paper: "#fafaf7"
  paper: "#ffffff"
  wash: "#f7f6f2"
  line: "#e7dfda"
  line-soft: "#f1ece8"
  line-receipt: "#ddd5cf"
  sidebar-text: "#cdbfb6"
  sidebar-muted: "#a08f85"
  ok: "#1f7a54"
  ok-wash: "#e8f4ee"
  live: "#1f9d6b"
  warn: "#b45309"
  warn-wash: "#fef4e6"
  danger: "#b42318"
  danger-wash: "#fdeceb"
  info: "#1c4e80"
  info-wash: "#eef4fb"
typography:
  display:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(2.4rem, 4.8vw, 4.4rem)"
    fontWeight: 760
    lineHeight: 0.96
    letterSpacing: "-0.035em"
    fontVariation: "'wdth' 88"
  headline:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "clamp(1.7rem, 2.6vw, 2.35rem)"
    fontWeight: 720
    lineHeight: 1.02
    letterSpacing: "-0.03em"
    fontVariation: "'wdth' 90"
  title:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "1.15rem"
    fontWeight: 700
    lineHeight: 1.25
    letterSpacing: "-0.02em"
    fontVariation: "'wdth' 94"
  figure:
    fontFamily: "Bricolage Grotesque, Segoe UI, system-ui, sans-serif"
    fontSize: "1.7rem"
    fontWeight: 700
    letterSpacing: "-0.02em"
    fontFeature: "'tnum' 1"
  body:
    fontFamily: "-apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.72rem"
    fontWeight: 600
    letterSpacing: "0.07em"
  receipt:
    fontFamily: "ui-monospace, Cascadia Mono, Consolas, SF Mono, Roboto Mono, monospace"
    fontSize: "0.92em"
    fontWeight: 400
    fontFeature: "'tnum' 1"
rounded:
  receipt: "6px"
  control: "8px"
  card: "10px"
  field-large: "12px"
  band: "14px"
  pill: "999px"
spacing:
  xs: "0.5rem"
  sm: "0.85rem"
  md: "1.15rem"
  lg: "1.5rem"
components:
  button-primary:
    backgroundColor: "{colors.persimmon}"
    textColor: "{colors.paper}"
    rounded: "{rounded.control}"
    padding: "0.5rem 0.9rem"
  button-primary-hover:
    backgroundColor: "{colors.persimmon-deep}"
  button-secondary:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.control}"
    padding: "0.5rem 0.9rem"
  button-signin:
    backgroundColor: "{colors.persimmon}"
    textColor: "{colors.paper}"
    rounded: "{rounded.field-large}"
    height: "3.5rem"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.control}"
    padding: "0.55rem 0.7rem"
  input-signin:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.field-large}"
    height: "3.25rem"
  card:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.card}"
    padding: "1.15rem"
  nav-item-active:
    textColor: "{colors.paper}"
    padding: "0.5rem 1.15rem"
  badge-ok:
    backgroundColor: "{colors.ok-wash}"
    textColor: "{colors.ok}"
    rounded: "{rounded.pill}"
    padding: "0.13rem 0.5rem"
  receipt-slip:
    backgroundColor: "{colors.thermal-paper}"
    textColor: "{colors.charcoal}"
    rounded: "{rounded.receipt}"
    typography: "{typography.receipt}"
---

# Design System: MAQAM FOOD CITY SUPERMARKET

## Overview

**Creative North Star: "The Shop's Own Till Roll"**

The material of this system is the thermal paper that comes out of the shop's own receipt printer. Sign-in is a receipt held up against the shop floor: a frosted slip standing over a photograph of a shopper with a full trolley, printed in with a date, hours and address set the way a till sets them. Once signed in, the shell is warm charcoal and plain paper, and on the dashboard the day's roll keeps feeding quietly out of a printer mouth above the figures. The world refuses the category defaults it replaced: the split-screen brand panel beside a white form, and the flat grey admin dashboard.

Colour is restrained on purpose. One deep, red-leaning persimmon (taken from the cart handle in the photograph) marks only where you act, where you are, what you can follow, and the mark itself. Everything you read - money, quantities, times - is ink on paper. Status keeps its own conventional colours: online and success stay green, because they are states, not the brand.

The system is dense and practical. Cashiers read it at arm's length with a queue waiting, the owner reads it on his phone from away. Expression lives around the work (the sign-in, the dashboard band, the owner's takings receipt) and never on the till itself. Every asset is served locally - one self-hosted variable font, local photographs - so it runs the same on an offline shop PC.

**Key Characteristics:**
- Warm charcoal and thermal-paper white, with one persimmon used sparingly.
- Money and times printed in mono, tabular figures; headline totals in the display face, still tabular.
- Receipt devices: dashed rules, dotted leaders, perforated and torn edges cut with masks.
- The arch mark (an M of two market arches on a counter bar) is the only ornament.
- Motion is transform and clip only, authored for the front door and the dashboard band, and still under reduced motion.

## Colors

A warm, low-chroma charcoal-and-paper ground carrying a single persimmon accent and a conventional set of status colours.

### Primary
- **Persimmon** (#c8481a): THE orange. Primary buttons, the sign-in button, the active tab, links, focus rings, the caret, the native `accent-color`, and the mark. Deep and red-leaning by client decision.
- **Persimmon Deep** (#a23a12): pressed and hover state of primary actions; orange text that has to sit on paper (the Show button, the receipt header on the rolls, owner-screen links).
- **Persimmon on Dark** (#e2662f): the orange where the ground is charcoal - the active nav rule, the mark's counter bar on the photograph, the faint watermark mark in the dashboard band.
- **Persimmon Pale** (#f3c4ab): text selection, secondary text on dark heads.
- **Persimmon Wash** (#fbece4): hover wash of quick-pick buttons and search results, the owner's install panel, ghost hover.

### Neutral
- **Warm Charcoal** (#1d1612): the ink of the roll and the night shop. Body text, the sidebar, the dashboard band, the page behind the sign-in.
- **Charcoal Raised** (#2b1e17): the owner phone head, one step lifted from the charcoal.
- **Ink Soft** (#5e524b): secondary text, ledes, receipt fact labels.
- **Ink Faint** (#8e8079): table headers, stat labels, empty states.
- **Thermal Paper** (#fafaf7): receipt slips - the sign-in receipt and the feeding rolls.
- **Paper** (#ffffff): cards, inputs, tables.
- **Wash** (#f7f6f2): the signed-in page ground, row hover, table footers.
- **Line** (#e7dfda) and **Line Soft** (#f1ece8): card borders and in-card dividers. **Receipt Line** (#ddd5cf): the dashed rules and field strokes on the sign-in receipt.
- **Sidebar Text** (#cdbfb6) and **Sidebar Muted** (#a08f85): nav items and section labels on charcoal.

### Status
- **Ok Green** (#1f7a54 on #e8f4ee) and **Live Green** (#1f9d6b): success messages, "ok" badges, the online-till dot.
- **Warn** (#b45309 on #fef4e6), **Danger** (#b42318 on #fdeceb), **Info** (#1c4e80 on #eef4fb): messages, badges, stat tiles and row tints by state.

### Named Rules
**The Act-Here Rule.** Persimmon appears only where you act (buttons, focus, caret), where you are (active nav, active tab), what you can follow (links), and on the mark. It is never the colour of a number, a heading, a fill area or a decorative band.

**The Persimmon-Not-Yellow Rule.** The orange is deep and red-leaning (#c8481a family). No yellow-orange, amber or tangerine stands in for it, anywhere, including the logo.

**The Status-Is-Not-Brand Rule.** Online, success and "ok" stay green; warnings amber; faults red. Never recolour a status in persimmon to make it "on brand".

## Typography

**Display Font:** Bricolage Grotesque (self-hosted variable woff2, weight 400-800, width 75-100%), falling back to Segoe UI / system-ui
**Body Font:** the platform UI stack (-apple-system, Segoe UI, Roboto, Helvetica Neue, Arial)
**Label/Mono Font:** ui-monospace, Cascadia Mono, Consolas, SF Mono, Roboto Mono

**Character:** A slightly condensed, heavy grotesque for names and totals, set tight, against the plain system face for everything a cashier reads at speed; the mono face is the receipt printer's voice.

### Hierarchy
- **Display** (760, clamp(2.4rem, 4.8vw, 4.4rem), 0.96, width 88%): the shop's name on the sign-in photograph only.
- **Headline** (720-760, clamp(1.7rem, 2.6vw, 2.35rem), ~1.0, width 88-92%): the sign-in greeting and the day on the dashboard band.
- **Title** (700, 1.5rem page / 1.15rem section, 1.25, width 94%): h1 and h2 in the shell; h3 and below drop to the body face at 650.
- **Figure** (700, 1.7rem stat tiles up to clamp(2rem, 10vw, 2.6rem) on the owner total, tabular): the few headline money figures, in ink.
- **Body** (400, 15px in the shell, 16px on sign-in and the owner phone, 1.5): everything else. Inputs on the phone never go under 16px.
- **Label** (600, 0.67-0.72rem, 0.06-0.09em, uppercase): table headers, stat-tile labels, nav section labels - they name data, they do not introduce headings.
- **Receipt** (mono, 0.92em in tables, 0.74-0.85rem on slips and facts, tabular): every money amount and time in a row, receipt numbers, the sign-in facts, the till-roll lines.

### Named Rules
**The Printed Figure Rule.** Money, quantities and times in rows are set in the mono face with tabular figures, right-aligned; column headings stay in the page's own voice. Headline totals may use the display face but keep `tnum`.

**The One Web Font Rule.** Bricolage Grotesque is the only downloaded face, served from /static and preloaded on sign-in. Nothing loads from a CDN.

## Layout

The shell is a fixed 232px charcoal sidebar beside a sticky translucent top bar (white at 0.86 with a 10px blur) and a content column padded 1.5rem, capped at 1400px. Content is cards in auto-fit grids (minimum tracks 190 / 240 / 320px, 1.15rem gaps); grid children carry `min-width: 0` so a wide table scrolls inside its card instead of widening the page. The POS is a two-column grid (1fr and a 400px totals panel) that stacks below 1100px.

The sign-in is a full-bleed photograph with a two-column grid over it: the shop name bottom-left on the photo, the receipt (22-29rem) centred right. Below 860px the photograph becomes fixed behind the page and the receipt is pulled up over it, full width with 0.9rem gutters.

At 760px and below (the owner's phone) the sidebar becomes a top strip whose nav scrolls sideways as pills, faded at the right edge with a mask; grids collapse to one column. The owner screen is a single 34rem column with 1.5rem gaps and safe-area padding. Spacing steps cluster at 0.5 / 0.85 / 1.15 / 1.5rem. No layout is decided by JavaScript; every page is whole without it.

## Elevation & Depth

A hybrid of low ambient shadow and material layering. Cards and stat tiles sit on the wash ground with a hairline border and a barely-there two-layer shadow. Depth with character is reserved for the receipt material: slips cast a long, soft drop below them as if hanging off the printer, and the sign-in receipt is frosted glass at its head and foot (shop floor blurred through) and near-solid paper behind the form.

### Shadow Vocabulary
- **Card** (`box-shadow: 0 1px 2px rgba(29,22,18,.06), 0 4px 14px rgba(29,22,18,.05)`): cards and stat tiles at rest.
- **Hanging receipt** (`box-shadow: 0 30px 60px -28px rgba(10,6,4,.75), 0 2px 6px rgba(10,6,4,.18)`): the sign-in receipt; the owner's takings receipt uses the lighter `0 18px 34px -22px rgba(29,22,18,.45)`.
- **Band** (`box-shadow: 0 18px 40px -26px rgba(29,22,18,.6)`): the dashboard printer band.
- **Persimmon lift** (`box-shadow: 0 12px 24px -12px rgba(162,58,18,.8)`): under the sign-in button only.
- **Focus halo** (`box-shadow: 0 0 0 4px rgba(200,72,26,.16)`): sign-in fields on focus.

### Named Rules
**The Paper-Over-Glass Rule.** Glass is allowed only where nothing has to be read through it. Behind any form or label the receipt goes to near-solid paper (0.94); blur shows only at the head and foot.

## Shapes

Corners are gently soft and scale with the object: 6px for receipts (top corners only - the foot is torn), 8px for buttons, shell inputs and messages, 10px for cards and stat tiles, 12px for the large sign-in fields and button, 14px for the dashboard band and phone-width receipts, 999px for badges and phone nav pills. Receipt edges are cut, not drawn: a perforated foot from a repeating radial-gradient mask (14px pitch on sign-in, 10px top and bottom on the rolls), and dashed 1.5px rules dividing a receipt's header, body and foot. The arch mark - two round-capped arches over a rounded counter bar - is the one recurring silhouette.

## Components

### Buttons
Plain, compact and clearly pressable; only the primary carries colour.
- **Shape:** gently rounded (8px); the sign-in button is larger and softer (12px, 3.5rem tall, full width).
- **Primary:** persimmon fill, white text, 0.5rem 0.9rem, weight 550. Large (0.75rem 1.4rem) and small (0.3rem 0.6rem) sizes.
- **Hover / Focus:** hover deepens to Persimmon Deep; focus is a 2px persimmon outline offset 2px. The sign-in button presses to scale(.985) and its arrow travels 4px on hover.
- **Secondary:** white with a hairline line border and ink text; hover to wash.
- **Danger / Danger Ghost:** solid red for confirmations; in busy rows a ghost with red text that only tints on hover.

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** paper on the wash ground.
- **Shadow Strategy:** the Card shadow (see Elevation).
- **Border:** 1px line; head divided from body by line-soft.
- **Internal Padding:** 1.15rem; head 0.9rem 1.15rem. Stat tiles carry an uppercase label, an ink figure, and a soft note; alert and caution tiles tint the whole tile in the status wash.

### Inputs / Fields
- **Style:** white, 1px line stroke, 8px radius, 0.55rem 0.7rem in the shell; on sign-in 1.5px stroke, 12px radius, 3.25rem tall, 1.05rem text.
- **Focus:** border goes persimmon with a 2px persimmon outline (shell) or a soft 4px persimmon halo (sign-in). The caret is persimmon.
- **Error:** red text below the field; the sign-in error is a danger-wash panel that nudges once.

### Navigation
Charcoal sidebar, items in sidebar-text at 0.875rem with uppercase section labels in sidebar-muted. Hover lifts to white on a 5% white wash. Active: white text on a persimmon-on-dark tint (14%) with a 3px persimmon-on-dark left rule. On a phone the nav becomes a horizontal pill strip and the active pill's tint strengthens to 30%. Tabs: ink-soft text; active tab persimmon with a 2px persimmon underline.

### Badges
Pills (999px), 0.72rem at 600, coloured only by status wash and status text: ok, warn, danger, neutral.

### Receipt (signature)
The recurring receipt slip: thermal paper, mono tabular lines, a centred header with the mark or the shop name, dashed rules between head, body and foot, and a perforated or torn edge cut by a mask. On sign-in it is frosted, prints in from the top edge (clip-path reveal, 1.25s) and carries the day's facts as a mono definition list. On the owner phone it is the takings slip with dotted leaders and the total in the display face, in ink.

### Printer Band (signature)
A charcoal band (15.5rem, 14px radius) with a faint persimmon glow in the top-left corner, the day in the headline style and the hours and address in mono. Three paper rolls of the shop's real product names and shelf prices feed upward out of the top edge at 46s / 62s / 54s, each slightly rotated, masked to fade at both ends; a large faint mark breathes behind the name. Only transform animates; with reduced motion everything stands still. Two rolls at mid width, one on a phone; hidden in print.

## Do's and Don'ts

### Do:
- **Do** keep persimmon (#c8481a) to actions, the active place, links, focus and the mark; use #e2662f for it on charcoal and #a23a12 for orange text on paper.
- **Do** set every money amount, quantity and time in a row in the mono face with tabular figures, right-aligned.
- **Do** keep online, success and ok states green (#1f7a54 / #1f9d6b).
- **Do** cut receipt edges with masks (radial-gradient perforations) and divide receipts with dashed rules.
- **Do** make glass near-solid (0.94 paper) behind anything that must be read.
- **Do** animate only transform, clip-path and opacity, wrap authored motion in `prefers-reduced-motion: no-preference`, and leave the page whole without it.
- **Do** serve every font and image from /static; the system must run on an offline shop PC.

### Don't:
- **Don't** colour a number, total or figure persimmon; figures are ink (or a status colour when they report a fault).
- **Don't** use a yellow-orange, amber or tangerine as the brand colour.
- **Don't** put any moving or decorative material on the till (POS) screen.
- **Don't** load fonts, scripts or images from a CDN.
- **Don't** return to the split-screen brand panel with a plain white form, or to a flat grey admin dashboard.
- **Don't** let JavaScript apply a class that decides layout.
