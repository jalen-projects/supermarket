/* The guided tour.

   The shop owner sent back a list of "how do I" questions after using the
   system, so the tour is built from those questions rather than from our menu
   structure. It walks him through doing each one on the real screens, not on a
   video or a picture.

   Two things shape how this is written:

   * The system is server-rendered across many pages, so a tour that spans
     pages has to survive a page load. Progress lives in sessionStorage and is
     picked up again on the next page.
   * There is no internet in the shop, so there is no tour library. This is
     plain JavaScript that runs on whatever browser the shop already has. */
(function () {
  'use strict';

  var cfg = document.getElementById('tour-cfg');
  if (!cfg) return;

  var KEY = 'smms.tour';
  var IS_ADMIN = cfg.dataset.admin === '1';
  var STATE_URL = cfg.dataset.stateUrl;
  var URLS = JSON.parse(cfg.dataset.urls || '{}');
  var AUTO = cfg.dataset.auto === '1';

  // ---------------------------------------------------------------------
  // The tour itself
  //
  // Each chapter belongs to one page. `at` is the page key, set by the
  // template on <body data-page="...">. When a chapter ends and the next one
  // is elsewhere, the tour navigates and resumes on arrival.
  //
  // `target` is a CSS selector. If the element is not on the page - a shop
  // with no products yet has no product row to point at - the step is skipped
  // rather than pointing at nothing.
  // ---------------------------------------------------------------------
  var CHAPTERS = [
    {
      at: 'dashboard',
      title: 'Welcome',
      steps: [
        { title: 'Let me show you round',
          body: 'This takes about three minutes. It follows the questions you sent back, ' +
                'one screen at a time.<br><br>You can stop at any point with <b>Escape</b>, ' +
                'and start again from <b>How do I…?</b> in the menu whenever you want.' },
        { target: '[data-tour="nav"]',
          title: 'Everything lives here',
          body: 'The menu on the left never moves. <b>Selling</b> at the top for the till ' +
                'and receipts, <b>Stock</b> underneath for your goods, then your reports ' +
                'and setup.' },
        { target: '[data-tour="takings"]',
          title: 'What came in today',
          body: 'The first thing you see when you sign in: today\'s takings, and how many ' +
                'receipts made it up.' },
        { target: '[data-tour="alerts"]', optional: true,
          title: 'What needs your attention',
          body: 'Low stock and anything expired on the shelf. If these are not zero, they ' +
                'are costing you money today.' }
      ]
    },
    {
      at: 'pos', admin: false,
      title: 'Cashing out a customer',
      steps: [
        { title: 'This is the till',
          body: 'You asked how to cash out. This screen is where it happens, and it is the ' +
                'one your cashiers will live on all day.' },
        { target: '[data-tour="scan"]',
          title: 'Start here, always',
          body: 'Scan the item, or type part of its name and press <b>Enter</b>. ' +
                'A barcode scanner types into this box on its own — you do not have to ' +
                'click anything first.' },
        { target: '[data-tour="cart"]',
          title: 'The items build up here',
          body: 'Scan the same thing twice and the quantity becomes 2, or type the ' +
                'quantity straight into the box. The × removes a line.' },
        { target: '[data-tour="total"]',
          title: 'What the customer owes',
          body: 'This is the number you read out. It updates as you scan.' },
        { target: '[data-tour="paid"]',
          title: 'What the customer handed you',
          body: 'Type it in — or use the buttons underneath. <b>Exact money</b> fills in ' +
                'the total. Tapping the notes adds them up: 10,000 then 5,000 for a ' +
                'customer paying 15,000.' },
        { target: '[data-tour="change"]',
          title: 'The change to hand back',
          body: 'Green means you have enough and this is their change. Red means they have ' +
                'not given you enough yet.' },
        { target: '[data-tour="checkout"]',
          title: 'This is cashing out',
          body: 'One button. It takes the money, prints the receipt, and removes the goods ' +
                'from your stock. Nothing else to press.<br><br>The keyboard shortcut is ' +
                '<b>F9</b>, which is faster once your cashiers know it.' }
      ]
    },
    {
      at: 'product_create',
      title: 'Putting a product in',
      steps: [
        { title: 'Adding a new product',
          body: 'You asked how to enter products. This is the screen — and there is one box ' +
                'on it that matters more than the rest.' },
        { target: '[data-tour="form"]',
          title: 'The details',
          body: 'Name, then the barcode — click the box and scan the item, or leave it ' +
                'empty for loose goods. Then the category, the measurement, and both ' +
                'prices.<br><br>Put in the <b>buying price</b> honestly. Every profit ' +
                'figure you will ever read comes from it.' },
        { target: '[data-tour-field="opening_quantity"]',
          title: 'How many you have right now',
          body: 'This is the important one. Type what is already on the shelf and the goods ' +
                'go into stock immediately — you can sell the item the moment you press ' +
                'save.<br><br>Leave it empty and the product exists but has nothing to ' +
                'sell yet.' }
      ]
    },
    {
      at: 'stock_take',
      title: 'The goods already in your shop',
      steps: [
        { title: 'Stock taking',
          body: 'You starred this one. This is how the goods that were in your supermarket ' +
                'before the system existed get onto the books — and afterwards, how you ' +
                'find out what has gone missing.' },
        { target: '[data-tour="scope"]',
          title: 'One shelf at a time',
          body: 'Never try to count the whole supermarket in one sitting. Pick a category, ' +
                'count that shelf, save it. Beverages this morning, soap after lunch — ' +
                'nothing is lost in between.' },
        { target: '[data-tour="sheet"]', optional: true,
          title: 'Type what you actually find',
          body: 'Walk the shelf and put the real number in the <b>Counted</b> box. The ' +
                '<b>Difference</b> column fills in as you type, so a wrong number is ' +
                'obvious while you are still standing there.<br><br>Leave a row empty if ' +
                'you did not count it. <b>Empty is not zero</b> — it means "I did not look ' +
                'at this one", and nothing about it changes.' },
        { target: '[data-tour="save-count"]', optional: true,
          title: 'The system does the arithmetic',
          body: 'Anything extra goes onto the books, anything missing comes off. You then ' +
                'get a sheet of every item that did not match and <b>what the gap is worth ' +
                'in shillings</b>.<br><br>That sheet is the point of the whole exercise.' }
      ]
    },
    {
      at: 'purchase_create',
      title: 'A delivery with no paperwork',
      steps: [
        { title: 'Receiving a delivery',
          body: 'This is how goods come into the shop from a supplier — and it answers your ' +
                'question about goods that arrive with no invoice number.' },
        { target: '[data-tour-field="invoice_no"]',
          title: 'Both of these are optional',
          body: 'No invoice? Leave it empty. Do not know the supplier either? Leave that as ' +
                '<b>Not recorded</b>.<br><br>The system still gives every delivery its own ' +
                'number, so the goods are fully tracked either way. If the invoice turns up ' +
                'later, open the delivery and type it in then.' },
        { target: '[data-tour="delivery-lines"]', optional: true,
          title: 'What was delivered',
          body: 'A line per item: how many, what one costs you, and the expiry date if it ' +
                'has one.<br><br>Fill the expiry in. It is what lets the system stop a ' +
                'cashier selling something that has gone off.' },
        { target: '[data-tour="receive"]', optional: true,
          title: 'Receive puts it on the shelf',
          body: '<b>Receive into stock now</b> is what actually adds the goods. A draft ' +
                'changes nothing until you receive it — useful when you are typing up ' +
                'yesterday\'s delivery and get interrupted.' }
      ]
    },
    {
      at: 'product_list',
      title: 'Removing a product',
      steps: [
        { title: 'Your products',
          body: 'Everything you sell. The tabs at the top narrow it down to what is running ' +
                'low, what is finished, and what you have taken off sale.' },
        { target: '[data-tour="remove"]', optional: true,
          title: 'How to delete a product',
          body: 'Your other question. Press <b>Remove</b> and the next screen tells you ' +
                'which of two things is about to happen, before you confirm anything.' },
        { title: 'Why there are two kinds of delete',
          body: 'A product that has never been sold or delivered is <b>really deleted</b> — ' +
                'that is the one you typed in twice.<br><br>A product with history is ' +
                '<b>taken off sale instead</b>. Its name is printed on receipts your ' +
                'customers are holding and it is inside last month\'s profit. Erasing it ' +
                'would change what those receipts add up to.<br><br>You can put it back on ' +
                'sale any time from the <b>Not for sale</b> tab.' }
      ]
    },
    {
      at: 'backup',
      title: 'Backup, and your second computer',
      steps: [
        { target: '[data-tour="backup-btn"]', optional: true,
          title: 'Do this at the end of every day',
          body: 'One click writes a dated copy of everything.<br><br>Then <b>copy it onto a ' +
                'flash disk that does not live in the shop</b>. A backup sitting on the same ' +
                'computer protects you from nothing — not from theft, not from fire, not ' +
                'from that computer simply dying.' },
        { target: '[data-tour="nav-network"]', optional: true,
          title: 'Your second computer',
          body: 'Yes — two computers can use this at the same time and share the same data, ' +
                'still with no internet. One runs the system; the other just opens a browser ' +
                'and types in an address.<br><br><b>Other computers</b> in the menu shows ' +
                'you exactly what to type.' },
        { title: 'That is the tour',
          body: 'Everything here is also written down under <b>How do I…?</b> in the menu — ' +
                'print that page and leave it at the till.<br><br>You can run this tour ' +
                'again from the same place whenever you like.' }
      ]
    }
  ];

  // ---------------------------------------------------------------------
  // State that survives a page load
  // ---------------------------------------------------------------------
  function readState() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || 'null'); }
    catch (e) { return null; }
  }
  function writeState(state) {
    try {
      if (state) sessionStorage.setItem(KEY, JSON.stringify(state));
      else sessionStorage.removeItem(KEY);
    } catch (e) { /* private mode - the tour just will not resume */ }
  }

  function chaptersForUser() {
    return CHAPTERS.filter(function (c) { return c.admin === false || IS_ADMIN; });
  }

  function page() {
    return document.body.dataset.page || '';
  }

  // ---------------------------------------------------------------------
  // Chrome
  // ---------------------------------------------------------------------
  var overlay, spot, bubble, active = null;

  function build() {
    overlay = document.createElement('div');
    overlay.className = 'tour-overlay';

    spot = document.createElement('div');
    spot.className = 'tour-spot';
    spot.hidden = true;

    bubble = document.createElement('div');
    bubble.className = 'tour-bubble';
    bubble.setAttribute('role', 'dialog');
    bubble.setAttribute('aria-live', 'polite');

    document.body.append(overlay, spot, bubble);
    overlay.addEventListener('click', function () { stop(true); });
  }

  function escapeAttr(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---------------------------------------------------------------------
  // Running a step
  // ---------------------------------------------------------------------
  function visibleSteps(chapter) {
    return chapter.steps.filter(function (s) {
      if (!s.target || document.querySelector(s.target)) return true;
      // The target is not on this page. An `optional` step is one that points
      // at a row that may not exist yet - a brand new shop has no products to
      // point at - so it is dropped. Anything else still has something worth
      // saying, and `place()` shows it in the middle with no highlight rather
      // than losing the explanation.
      return !s.optional;
    });
  }

  function show() {
    var chapters = chaptersForUser();
    var chapter = chapters[active.chapter];
    var steps = visibleSteps(chapter);
    var step = steps[active.step];
    if (!step) { advanceChapter(); return; }

    // May be null even when the step names a target - see visibleSteps().
    var target = step.target ? document.querySelector(step.target) : null;
    var totalChapters = chapters.length;

    var isLastStep = active.step === steps.length - 1;
    var isLastChapter = active.chapter === totalChapters - 1;

    bubble.innerHTML =
      // "Part" not "Step": these are the chapters, and each has several steps
      // inside it. Calling both a step made the counter look stuck.
      '<div class="tour-step">Part ' + (active.chapter + 1) + ' of ' + totalChapters +
        ' &middot; ' + escapeAttr(chapter.title) +
        (steps.length > 1 ? ' &middot; ' + (active.step + 1) + '/' + steps.length : '') +
        '</div>' +
      '<h3>' + escapeAttr(step.title) + '</h3>' +
      '<div class="tour-body">' + step.body + '</div>' +
      '<div class="tour-actions">' +
        '<button type="button" class="btn btn-sm" data-tour-act="skip">Skip the tour</button>' +
        '<div class="tour-spacer"></div>' +
        (active.chapter === 0 && active.step === 0 ? '' :
          '<button type="button" class="btn btn-sm" data-tour-act="back">Back</button>') +
        '<button type="button" class="btn btn-sm btn-primary" data-tour-act="next">' +
          (isLastStep && isLastChapter ? 'Finish' : 'Next') +
        '</button>' +
      '</div>';

    Array.prototype.forEach.call(bubble.querySelectorAll('[data-tour-act]'), function (b) {
      b.addEventListener('click', function () {
        var act = b.dataset.tourAct;
        if (act === 'skip') stop(true);
        else if (act === 'back') back();
        else next();
      });
    });

    place(target);
  }

  function place(target) {
    if (!target) {
      spot.hidden = true;
      overlay.classList.remove('tour-overlay-clear');
      bubble.className = 'tour-bubble tour-bubble-center';
      bubble.style.top = '';
      bubble.style.left = '';
      return;
    }

    target.scrollIntoView({ block: 'center', behavior: 'auto' });

    var r = target.getBoundingClientRect();
    var pad = 6;
    spot.hidden = false;
    // The spot dims the page from here on; the flat overlay must stand down.
    overlay.classList.add('tour-overlay-clear');
    spot.style.top = (r.top - pad) + 'px';
    spot.style.left = (r.left - pad) + 'px';
    spot.style.width = (r.width + pad * 2) + 'px';
    spot.style.height = (r.height + pad * 2) + 'px';

    bubble.className = 'tour-bubble';
    bubble.style.top = '0px';
    bubble.style.left = '0px';
    var b = bubble.getBoundingClientRect();

    // Prefer under the highlight, flip above when there is no room, and keep
    // the whole bubble on screen either way.
    var top = r.bottom + 14;
    if (top + b.height > window.innerHeight - 10) {
      top = r.top - b.height - 14;
    }
    top = Math.max(10, Math.min(top, window.innerHeight - b.height - 10));

    var left = r.left + (r.width / 2) - (b.width / 2);
    left = Math.max(10, Math.min(left, window.innerWidth - b.width - 10));

    bubble.style.top = top + 'px';
    bubble.style.left = left + 'px';
  }

  // ---------------------------------------------------------------------
  // Moving about
  // ---------------------------------------------------------------------
  function next() {
    var chapter = chaptersForUser()[active.chapter];
    if (active.step < visibleSteps(chapter).length - 1) {
      active.step += 1;
      show();
    } else {
      advanceChapter();
    }
  }

  function back() {
    if (active.step > 0) {
      active.step -= 1;
      show();
      return;
    }
    if (active.chapter === 0) return;
    goToChapter(active.chapter - 1, 'last');
  }

  function advanceChapter() {
    if (active.chapter >= chaptersForUser().length - 1) { stop(true); return; }
    goToChapter(active.chapter + 1, 0);
  }

  function goToChapter(index, step) {
    var chapter = chaptersForUser()[index];
    var target = URLS[chapter.at];

    if (chapter.at === page() || !target) {
      active.chapter = index;
      active.step = step === 'last' ? Math.max(visibleSteps(chapter).length - 1, 0) : step;
      show();
      return;
    }

    // The next chapter lives on another screen. Save where we are and go
    // there; the tour picks itself up when that page loads.
    writeState({ chapter: index, step: step === 'last' ? 'last' : step, running: true });
    window.location.href = target;
  }

  function stop(markDone) {
    writeState(null);
    active = null;
    if (overlay) { overlay.remove(); spot.remove(); bubble.remove(); overlay = null; }
    document.body.classList.remove('tour-running');
    document.removeEventListener('keydown', onKey, true);
    if (markDone) tellServer(true);
  }

  function onKey(e) {
    if (!active) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); stop(true); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); next(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); back(); }
  }

  function tellServer(done) {
    if (!STATE_URL) return;
    var token = document.querySelector('[name=csrfmiddlewaretoken]');
    if (!token) return;
    fetch(STATE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token.value },
      body: JSON.stringify({ done: !!done })
    }).catch(function () { /* the tour must never break the shop */ });
  }

  function start(chapterIndex, stepIndex) {
    if (active) return;
    if (!overlay) build();
    document.body.classList.add('tour-running');
    active = { chapter: chapterIndex || 0, step: 0 };
    var chapter = chaptersForUser()[active.chapter];
    active.step = stepIndex === 'last'
      ? Math.max(visibleSteps(chapter).length - 1, 0)
      : (stepIndex || 0);
    document.addEventListener('keydown', onKey, true);
    show();
    // Keep the highlight glued to its element when the window is resized.
    window.addEventListener('resize', reposition);
  }

  function reposition() {
    if (!active) return;
    var chapter = chaptersForUser()[active.chapter];
    var step = visibleSteps(chapter)[active.step];
    place(step && step.target ? document.querySelector(step.target) : null);
  }

  // ---------------------------------------------------------------------
  // Starting up
  // ---------------------------------------------------------------------
  // Resuming after the tour navigated to another page.
  var saved = readState();
  if (saved && saved.running) {
    var chapters = chaptersForUser();
    var wanted = chapters[saved.chapter];
    if (wanted && wanted.at === page()) {
      writeState(null);
      start(saved.chapter, saved.step);
    } else if (!wanted) {
      writeState(null);
    }
  }

  // Anything on any page can offer the tour.
  document.addEventListener('click', function (e) {
    var trigger = e.target.closest ? e.target.closest('[data-tour-start]') : null;
    if (!trigger) return;
    e.preventDefault();
    writeState(null);
    tellServer(false);
    goFromScratch();
  });

  function goFromScratch() {
    var first = chaptersForUser()[0];
    if (first.at === page()) { start(0, 0); return; }
    writeState({ chapter: 0, step: 0, running: true });
    window.location.href = URLS[first.at] || '/';
  }

  // First sign-in: offer it rather than launching into it uninvited. Somebody
  // who opened the till to serve a customer standing in front of them must not
  // have a tour take over the screen.
  if (AUTO && !readState()) {
    var invite = document.createElement('div');
    invite.className = 'tour-invite';
    invite.innerHTML =
      '<div class="tour-invite-body">' +
        '<strong>New here?</strong>' +
        '<p>A three-minute walk through the system, built from the questions you sent ' +
           'back — cashing out, entering products, stock taking and the rest.</p>' +
      '</div>' +
      '<div class="tour-invite-actions">' +
        '<button type="button" class="btn btn-primary btn-sm" data-tour-start>Show me</button>' +
        '<button type="button" class="btn btn-sm" data-tour-dismiss>Not now</button>' +
      '</div>';
    document.body.appendChild(invite);
    invite.querySelector('[data-tour-dismiss]').addEventListener('click', function () {
      invite.remove();
      tellServer(true);
    });
    invite.querySelector('[data-tour-start]').addEventListener('click', function () {
      invite.remove();
    });
  }
})();
