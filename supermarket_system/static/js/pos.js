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

  var cart = [];        // {id, name, price, qty, unit, dec}
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
      changeLine.style.color = diff < 0 ? 'var(--danger)' : 'var(--brand)';
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
        (out ? ' <span class="badge badge-danger">out of stock</span>' : '') +
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
    var paid = parseFloat(document.getElementById('paid').value) || 0;
    var method = document.getElementById('method').value;
    if (method !== 'CREDIT' && paid < total) {
      if (!confirm('The cash received is less than the total. Record it anyway as a part payment?')) {
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
        button.textContent = 'Complete sale & print (F9)';
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
        button.textContent = 'Complete sale & print (F9)';
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

  // Till shortcuts - a busy cashier should not need the mouse.
  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') { e.preventDefault(); scan.focus(); scan.select(); }
    if (e.key === 'F9') { e.preventDefault(); checkout(); }
  });

  render();
})();
