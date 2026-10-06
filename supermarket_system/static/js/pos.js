/* The till.
   Written in plain JavaScript on purpose: this machine has no internet, so
   there is no framework to download and nothing to break on an old browser. */
(function () {
  'use strict';

  var cfg = document.getElementById('cfg');
  var CURRENCY = cfg.dataset.currency;
  var VAT = parseFloat(cfg.dataset.vat || '0');
  var LOOKUP = cfg.dataset.lookup;
  var CHECKOUT = cfg.dataset.checkout;
  var CSRF = document.querySelector('[name=csrfmiddlewaretoken]').value;

  var scan = document.getElementById('scan');
  var results = document.getElementById('results');
  var cartBody = document.getElementById('cart-body');
  var emptyRow = document.getElementById('empty-row');
  var errorBox = document.getElementById('pos-error');

  // Read the label off the button rather than repeating the wording here, so
  // renaming it in the template cannot leave a stale label behind after a sale.
  var CHECKOUT_LABEL = document.getElementById('checkout').innerHTML;

  var cart = [];        // {id, name, price, qty, unit, dec}

  // THE BASKET SURVIVES A RELOAD. It used to live only in this page, so a
  // refresh, a mis-click on the menu or a dropped connection emptied it and
  // it looked as if the system deleted items on its own. Now it is kept in
  // this browser, per cashier, until the sale is completed or cleared.
  var STORE = cfg.dataset.store || 'maqam';   // this shop's prefix, shop/brand.py
  var CART_KEY = STORE + '.cart.' + (cfg.dataset.user || 'till');
  function saveCart() {
    try {
      if (cart.length) localStorage.setItem(CART_KEY, JSON.stringify(cart));
      else localStorage.removeItem(CART_KEY);
    } catch (e) { /* storage blocked - the basket simply is not kept */ }
  }
  try {
    var kept = JSON.parse(localStorage.getItem(CART_KEY) || '[]');
    if (Array.isArray(kept)) cart = kept;
  } catch (e) { cart = []; }
  var matches = [];
  var selected = -1;
  var searchTimer = null;
  var busy = false;

  function money(n) {
    return CURRENCY + ' ' + (Math.round(n * 100) / 100)
      .toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function showError(text) {
    errorBox.textContent = text;
    errorBox.hidden = !text;
    if (text) errorBox.scrollIntoView({ block: 'nearest' });
  }

  // ---- cart ---------------------------------------------------------------
  function addToCart(p) {
    var existing = null;
    for (var i = 0; i < cart.length; i++) if (cart[i].id === p.id) existing = cart[i];
    if (existing) {
      existing.qty += 1;
    } else {
      cart.push({ id: p.id, name: p.name, price: parseFloat(p.price),
                  qty: 1, unit: p.unit, dec: !!p.allow_decimals, stock: p.stock });
    }
    render();
    showError('');
    // The previous sale's confirmation goes away as soon as the next one starts.
    document.getElementById('last-sale').hidden = true;
  }

  function removeFromCart(id) {
    cart = cart.filter(function (l) { return l.id !== id; });
    render();
  }

  function render() {
    saveCart();
    emptyRow.hidden = cart.length > 0;
    // Remove previously drawn rows, keep the empty-state row.
    Array.prototype.slice.call(cartBody.querySelectorAll('tr.line')).forEach(function (tr) {
      tr.remove();
    });

    cart.forEach(function (line) {
      var tr = document.createElement('tr');
      tr.className = 'line';

      var td1 = document.createElement('td');
      td1.innerHTML = '<strong>' + escapeHtml(line.name) + '</strong>' +
        '<div class="faint">' + escapeHtml(line.unit) + '</div>';

      var td2 = document.createElement('td');
      td2.className = 'num';
      var qty = document.createElement('input');
      qty.type = 'number';
      qty.className = 'qty';
      qty.min = line.dec ? '0.001' : '1';
      qty.step = line.dec ? 'any' : '1';
      qty.value = line.qty;
      qty.addEventListener('input', function () {
        var v = parseFloat(qty.value);
        line.qty = isNaN(v) || v <= 0 ? 0 : v;
        totals();
      });
      td2.appendChild(qty);

      var td3 = document.createElement('td');
      td3.className = 'num';
      var price = document.createElement('input');
      price.type = 'number';
      price.className = 'price';
      price.min = '0';
      price.step = 'any';
      price.value = line.price;
      price.addEventListener('input', function () {
        var v = parseFloat(price.value);
        line.price = isNaN(v) || v < 0 ? 0 : v;
        totals();
      });
      td3.appendChild(price);

      var td4 = document.createElement('td');
      td4.className = 'num amount';
      td4.textContent = money(line.qty * line.price);

      var td5 = document.createElement('td');
      td5.className = 'num';
      var x = document.createElement('button');
      x.type = 'button';
      x.className = 'x-btn';
      x.title = 'Remove';
      x.textContent = '×';
      x.addEventListener('click', function () { removeFromCart(line.id); });
      td5.appendChild(x);

      tr.append(td1, td2, td3, td4, td5);
      cartBody.appendChild(tr);
    });

    totals();
  }

  function totals() {
    var sub = 0;
    cart.forEach(function (l) { sub += l.qty * l.price; });

    // Keep each visible line amount in step with its quantity box.
    var rows = cartBody.querySelectorAll('tr.line');
    for (var i = 0; i < rows.length; i++) {
      var cell = rows[i].querySelector('.amount');
      if (cell && cart[i]) cell.textContent = money(cart[i].qty * cart[i].price);
    }

    var discount = parseFloat(document.getElementById('discount').value) || 0;
    if (discount > sub) discount = sub;
    var taxable = Math.max(sub - discount, 0);
    var vat = VAT ? taxable * VAT / 100 : 0;
    var total = taxable + vat;

    setText('t-sub', money(sub));
    setText('t-disc', money(discount));
    setText('t-vat', money(vat));
    setText('t-total', money(total));
    var vatBox = document.getElementById('vat');
    if (vatBox) vatBox.value = (Math.round(vat * 100) / 100).toString();

    document.getElementById('cart-count').textContent =
      cart.length + (cart.length === 1 ? ' item' : ' items');

    var paid = parseFloat(document.getElementById('paid').value) || 0;
    var changeLine = document.getElementById('change-line');
    if (paid > 0 && total > 0) {
      changeLine.hidden = false;
      var diff = paid - total;
      // A class, not an inline colour: the box has a green wash behind it and
      // red text on green is unreadable at a glance.
      changeLine.className = diff < 0 ? 'change-line short' : 'change-line';
      changeLine.firstChild.textContent = diff < 0 ? 'Short by: ' : 'Change: ';
      setText('t-change', money(Math.abs(diff)));
    } else {
      changeLine.hidden = true;
    }

    window._posTotal = total;
    window._posVat = vat;
    window._posDiscount = discount;
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  // After a sale, confirm it on screen. The cashier needs the change amount and
  // a way back to the receipt without hunting through the receipts list.
  function showLastSale(url, receiptNo, change) {
    var box = document.getElementById('last-sale');
    box.innerHTML = 'Sale <strong>' + escapeHtml(receiptNo) + '</strong> saved. ' +
      'Change <strong>' + money(parseFloat(change)) + '</strong>. ' +
      '<a href="' + url + '" target="_blank">Open the receipt again</a>';
    box.hidden = false;
  }

  function showReceiptLink(url, receiptNo, change) {
    var box = document.getElementById('last-sale');
    box.innerHTML = 'Sale <strong>' + escapeHtml(receiptNo) + '</strong> saved. ' +
      'Change <strong>' + money(parseFloat(change)) + '</strong>. ' +
      'The browser blocked the receipt window - ' +
      '<a href="' + url + '?print=1" target="_blank">click here to print it</a>, ' +
      'and allow pop-ups from this address so it opens on its own next time.';
    box.hidden = false;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // ---- search / scan ------------------------------------------------------
  function search(term) {
    if (!term) { hideResults(); return; }
    fetch(LOOKUP + '?q=' + encodeURIComponent(term))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // A scanner sends the whole barcode then Enter: an exact hit goes
        // straight into the cart, no clicking.
        if (data.exact && data.results.length === 1) {
          addToCart(data.results[0]);
          scan.value = '';
          hideResults();
          return;
        }
        matches = data.results;
        selected = matches.length ? 0 : -1;
        drawResults();
      })
      .catch(function () { hideResults(); });
  }

  function drawResults() {
    if (!matches.length) {
      results.innerHTML = '<div class="result muted">No product matches that. ' +
        'Check the spelling, or add the product first.</div>';
      results.hidden = false;
      return;
    }
    results.innerHTML = '';
    matches.forEach(function (p, i) {
      var div = document.createElement('div');
      div.className = 'result' + (i === selected ? ' sel' : '');
      var out = parseFloat(p.stock) <= 0;
      div.innerHTML =
        '<div class="r-name">' + escapeHtml(p.name) +
        (out ? (parseFloat(p.expired || '0') > 0
                 ? ' <span class="badge badge-danger">expired date - ask the manager</span>'
                 : ' <span class="badge badge-danger">out of stock</span>') : '') +
        '<div class="r-meta">' + escapeHtml(p.barcode || 'no barcode') +
        ' &middot; ' + p.stock + ' ' + escapeHtml(p.unit) + ' left' +
        (p.expiry ? ' &middot; expires ' + p.expiry : '') + '</div></div>' +
        '<div class="num"><strong>' + money(parseFloat(p.price)) + '</strong></div>';
      div.addEventListener('click', function () {
        addToCart(p);
        scan.value = '';
        hideResults();
        scan.focus();
      });
      results.appendChild(div);
    });
    results.hidden = false;
  }

  function hideResults() {
    results.hidden = true;
    matches = [];
    selected = -1;
  }

  scan.addEventListener('input', function () {
    clearTimeout(searchTimer);
    var term = scan.value.trim();
    if (!term) { hideResults(); return; }
    // Short delay so a scanner's burst of keystrokes is one lookup, not ten.
    searchTimer = setTimeout(function () { search(term); }, 120);
  });

  scan.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') {
      e.preventDefault();
      clearTimeout(searchTimer);
      if (selected >= 0 && matches[selected]) {
        addToCart(matches[selected]);
        scan.value = '';
        hideResults();
      } else {
        search(scan.value.trim());
      }
    } else if (e.key === 'ArrowDown' && matches.length) {
      e.preventDefault();
      selected = Math.min(selected + 1, matches.length - 1);
      drawResults();
    } else if (e.key === 'ArrowUp' && matches.length) {
      e.preventDefault();
      selected = Math.max(selected - 1, 0);
      drawResults();
    } else if (e.key === 'Escape') {
      scan.value = '';
      hideResults();
    }
  });

  document.addEventListener('click', function (e) {
    if (!results.contains(e.target) && e.target !== scan) hideResults();
  });

  // Quick-pick buttons
  Array.prototype.forEach.call(document.querySelectorAll('.quick-btn'), function (btn) {
    btn.addEventListener('click', function () {
      addToCart({
        id: parseInt(btn.dataset.id, 10), name: btn.dataset.name,
        price: btn.dataset.price, unit: btn.dataset.unit,
        allow_decimals: btn.dataset.dec === '1', stock: '0'
      });
      scan.focus();
    });
  });

  ['discount', 'paid'].forEach(function (id) {
    document.getElementById(id).addEventListener('input', totals);
  });

  // ---- tender buttons -----------------------------------------------------
  // "Exact money" fills in the total. A note button adds that note to what has
  // already been handed over, because a customer paying 15,000 gives a 10 and
  // a 5 - that is two taps, not mental arithmetic at the counter.
  Array.prototype.forEach.call(document.querySelectorAll('.tender'), function (btn) {
    btn.addEventListener('click', function () {
      var paidBox = document.getElementById('paid');
      var kind = btn.dataset.tender;
      if (kind === 'exact') {
        paidBox.value = Math.round((window._posTotal || 0) * 100) / 100;
      } else {
        paidBox.value = (parseFloat(paidBox.value) || 0) + parseFloat(kind);
      }
      totals();
      scan.focus();
    });
  });

  // ---- checkout -----------------------------------------------------------
  function checkout() {
    if (busy) return;
    if (!cart.length) { showError('Add at least one item before completing the sale.'); return; }
    for (var i = 0; i < cart.length; i++) {
      if (!cart[i].qty || cart[i].qty <= 0) {
        showError('Quantity for ' + cart[i].name + ' must be more than zero.');
        return;
      }
    }

    var total = window._posTotal || 0;
    // CASH OUT WITHOUT TYPING THE MONEY (the manager's request, 6 Oct 2026):
    // an empty "amount paid" means the customer paid exactly. Typing an
    // amount still works, for working out change; a typed amount that is too
    // little is still questioned below.
    var paidRaw = document.getElementById('paid').value.trim();
    var paid = paidRaw === '' ? total : (parseFloat(paidRaw) || 0);
    var method = document.getElementById('method').value;
    if (method !== 'CREDIT' && paid < total) {
      if (!confirm('The customer has given ' + money(paid) + ' but the total is ' +
                   money(total) + ', short by ' + money(total - paid) + '.\n\n' +
                   'Press OK to cash out anyway and record the rest as still owed. ' +
                   'Press Cancel to go back and correct the amount.')) {
        return;
      }
    }

    busy = true;
    var button = document.getElementById('checkout');
    button.disabled = true;
    button.textContent = 'Saving...';
    showError('');

    fetch(CHECKOUT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify({
        lines: cart.map(function (l) {
          return { product_id: l.id, quantity: l.qty, unit_price: l.price };
        }),
        customer_id: document.getElementById('customer').value || null,
        discount: window._posDiscount || 0,
        tax: window._posVat || 0,
        payment_method: method,
        amount_paid: paid
      })
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        busy = false;
        button.disabled = false;
        button.innerHTML = CHECKOUT_LABEL;
        if (!res.ok || !res.d.ok) {
          showError(res.d.error || 'The sale could not be saved. Nothing was charged.');
          return;
        }
        // Open the receipt; the print dialog fires on its own. If the browser
        // blocks the popup, fall back to a link the cashier can click - the sale
        // is already saved either way, so it must never look like a failure.
        var win = window.open(res.d.receipt_url + '?print=1', '_blank',
                              'width=420,height=680');
        if (!win) {
          showReceiptLink(res.d.receipt_url, res.d.receipt_no, res.d.change);
        } else {
          showLastSale(res.d.receipt_url, res.d.receipt_no, res.d.change);
        }
        cart = [];
        document.getElementById('paid').value = '';
        document.getElementById('discount').value = '0';
        document.getElementById('customer').value = '';
        render();
        scan.focus();
      })
      .catch(function () {
        busy = false;
        button.disabled = false;
        button.innerHTML = CHECKOUT_LABEL;
        showError('The sale could not be saved. Check that the system is still running, ' +
                  'then try again. Nothing was charged.');
      });
  }

  document.getElementById('checkout').addEventListener('click', checkout);

  document.getElementById('clear').addEventListener('click', function () {
    if (cart.length && !confirm('Clear this sale and start again?')) return;
    cart = [];
    document.getElementById('paid').value = '';
    document.getElementById('discount').value = '0';
    render();
    scan.focus();
  });

  // ---- hold / bring back ("park the basket") -----------------------------
  // A customer goes back for the bigger tin; the queue cannot wait. The
  // basket is held ON THE SERVER (see HeldSale) so it is still there after
  // a break, a restart, or when the customer comes back to another till.
  var HELD = cfg.dataset.held;
  var heldCard = document.getElementById('held-card');
  var heldList = document.getElementById('held-list');
  var holdDialog = document.getElementById('hold-dialog');
  var holdLabel = document.getElementById('hold-label');

  function postJson(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CSRF },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      return r.json().then(function (d) { return { ok: r.ok && d.ok, d: d }; });
    });
  }

  function emptyTheTill() {
    cart = [];
    document.getElementById('paid').value = '';
    document.getElementById('discount').value = '0';
    document.getElementById('customer').value = '';
    render();
  }

  function drawHeld(list) {
    heldList.innerHTML = '';
    heldCard.hidden = !list.length;
    document.getElementById('held-count').textContent =
      list.length + (list.length === 1 ? ' basket' : ' baskets');
    list.forEach(function (h) {
      var li = document.createElement('li');
      li.className = 'held-item';
      li.innerHTML =
        '<div class="held-main"><strong>' + escapeHtml(h.label) + '</strong>' +
        '<span class="held-meta">' + h.items + (h.items === 1 ? ' item' : ' items') +
        ' &middot; held ' + (h.today ? '' : 'yesterday ') + escapeHtml(h.held_at) +
        (h.mine ? '' : ' by ' + escapeHtml(h.held_by)) +
        (h.customer ? ' &middot; ' + escapeHtml(h.customer) : '') + '</span></div>' +
        '<span class="held-total">' + money(parseFloat(h.total)) + '</span>';
      var back = document.createElement('button');
      back.type = 'button';
      back.className = 'btn btn-sm btn-primary';
      back.textContent = 'Bring back';
      back.addEventListener('click', function () { bringBack(h); });
      var drop = document.createElement('button');
      drop.type = 'button';
      drop.className = 'x-btn';
      drop.title = 'Discard - the customer is not coming back';
      drop.setAttribute('aria-label', 'Discard ' + h.label);
      drop.textContent = '×';
      drop.addEventListener('click', function () { discard(h); });
      li.append(back, drop);
      heldList.appendChild(li);
    });
  }

  function refreshHeld() {
    if (!HELD) return Promise.resolve();
    return fetch(HELD, { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (d.ok) drawHeld(d.held); })
      .catch(function () { /* offline for a moment - the list waits */ });
  }

  // Resolves with the held basket, or rejects with the reason.
  function holdCurrent(label) {
    return postJson(HELD, {
      label: label || '',
      customer_id: document.getElementById('customer').value || null,
      lines: cart.map(function (l) {
        return { product_id: l.id, quantity: l.qty, unit_price: l.price };
      })
    }).then(function (res) {
      if (!res.ok) throw new Error(res.d.error || 'The sale could not be held.');
      emptyTheTill();
      return res.d.held;
    });
  }

  function askToHold() {
    if (busy) return;
    if (!cart.length) { showError('There is nothing on this sale to hold.'); return; }
    showError('');
    holdLabel.value = '';
    if (holdDialog && holdDialog.showModal) {
      holdDialog.showModal();
      holdLabel.focus();
    } else {
      var name = window.prompt("Customer's name (optional):", '');
      if (name !== null) finishHold(name);
    }
  }

  function finishHold(label) {
    holdCurrent(label).then(function (held) {
      var box = document.getElementById('last-sale');
      box.innerHTML = 'Sale held as <strong>' + escapeHtml(held.label) + '</strong>. ' +
        'Serve the next customer, and bring it back from <strong>On hold</strong>.';
      box.hidden = false;
      refreshHeld();
      scan.focus();
    }).catch(function (err) {
      showError(err.message || 'The sale could not be held. Nothing was lost - try again.');
    });
  }

  if (holdDialog) {
    document.getElementById('hold-form').addEventListener('submit', function () {
      // method="dialog" closes it; this only reads the name.
      finishHold(holdLabel.value.trim());
    });
    document.getElementById('hold-cancel').addEventListener('click', function () {
      holdDialog.close();
      scan.focus();
    });
  }
  document.getElementById('hold').addEventListener('click', askToHold);

  // Bringing a basket back never mixes two customers' shopping. If there is
  // a sale on screen it is held first, under its own name, and then the
  // chosen one comes back - nothing is merged and nothing is lost.
  function bringBack(h) {
    if (busy) return;
    var first = Promise.resolve(null);
    if (cart.length) {
      if (!confirm('There is a sale on screen. It will be put on hold first, so nothing ' +
                   'is lost, and then ' + h.label + ' comes back.\n\nContinue?')) return;
      first = holdCurrent('');
    }
    busy = true;
    first.then(function (parked) {
      return postJson(HELD + h.id + '/recall/').then(function (res) {
        busy = false;
        if (!res.ok) {
          showError(res.d.error || 'That basket could not be brought back.');
          refreshHeld();
          return;
        }
        cart = res.d.lines;
        document.getElementById('customer').value = res.d.customer_id || '';
        render();
        var box = document.getElementById('last-sale');
        box.innerHTML = '<strong>' + escapeHtml(res.d.label) + '</strong> is back on the till.' +
          (parked ? ' The previous sale is on hold as <strong>' +
                    escapeHtml(parked.label) + '</strong>.' : '');
        box.hidden = false;
        showError((res.d.notes || []).join(' '));
        refreshHeld();
        scan.focus();
      });
    }).catch(function (err) {
      busy = false;
      showError((err && err.message) || 'That basket could not be brought back. Try again.');
    });
  }

  function discard(h) {
    if (!confirm('Throw away ' + h.label + ' (' + h.items + ' items)? ' +
                 'Only do this if the customer is not coming back.')) return;
    postJson(HELD + h.id + '/discard/').then(function (res) {
      if (!res.ok) showError(res.d.error || 'It could not be discarded.');
      refreshHeld();
    });
  }

  refreshHeld();
  // Another till may hold or bring back a basket at any moment.
  setInterval(function () { if (!document.hidden) refreshHeld(); }, 30000);

  // Till shortcuts - a busy cashier should not need the mouse.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') { e.preventDefault(); scan.focus(); scan.select(); }
    if (e.key === 'F9') { e.preventDefault(); checkout(); }
    if (e.key === 'F8') { e.preventDefault(); askToHold(); }
  });

  render();
})();
