/* Stock capture - scan, type, Enter, next item.
 *
 * No library: the shop has no internet, so nothing may be fetched from a CDN.
 *
 * The whole point of this screen is that a person can capture two hundred
 * products without ever touching the mouse. Every decision below serves that:
 * the cursor returns to the barcode box after each save, Enter moves forward
 * through the boxes, and the page never reloads.
 */
(function () {
  'use strict';

  var form = document.getElementById('capture-form');
  if (!form) return;

  var barcode = document.getElementById('c-barcode');
  var name = document.getElementById('c-name');
  var buying = document.getElementById('c-buying');
  var selling = document.getElementById('c-selling');
  var quantity = document.getElementById('c-quantity');
  var expiry = document.getElementById('c-expiry');
  var category = document.getElementById('c-category');
  var unit = document.getElementById('c-unit');
  var status = document.getElementById('c-status');
  var log = document.getElementById('c-log');
  var counter = document.getElementById('c-count');
  var lookupUrl = form.dataset.lookupUrl;

  var captured = 0;

  function say(message, kind) {
    status.textContent = message;
    status.className = 'capture-status ' + (kind || '');
  }

  function money(value) {
    var n = parseFloat(value || 0);
    return isNaN(n) ? '0' : n.toLocaleString('en-UG', { maximumFractionDigits: 0 });
  }

  /* Clear for the next item, but KEEP category and unit. Walking one shelf
   * means twenty items in the same category, and re-picking it every time is
   * the slowest part of the job. */
  function reset() {
    barcode.value = '';
    name.value = '';
    buying.value = '';
    selling.value = '';
    quantity.value = '';
    expiry.value = '';
    barcode.focus();
  }

  /* When a barcode is scanned, check whether it is already known. If it is,
   * fill the boxes in so the person only types the quantity found. */
  var lookupTimer = null;
  function lookup() {
    var code = barcode.value.trim();
    if (!code) return;
    fetch(lookupUrl + '?barcode=' + encodeURIComponent(code), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.found) {
          say('New item - type the name and prices.', '');
          name.focus();
          return;
        }
        name.value = data.name;
        buying.value = data.buying_price;
        selling.value = data.selling_price;
        if (data.category) category.value = data.category;
        if (data.unit) unit.value = data.unit;
        say('Already captured: ' + data.name + ' (' + data.stock +
            ' in stock). Type how many more you found.', 'warn');
        quantity.focus();
        quantity.select();
      })
      .catch(function () { name.focus(); });
  }

  barcode.addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    clearTimeout(lookupTimer);
    lookup();
  });

  /* A scanner types the whole code in a burst and may or may not send Enter.
   * The short delay makes that burst one lookup rather than a dozen. */
  barcode.addEventListener('input', function () {
    clearTimeout(lookupTimer);
    if (barcode.value.trim().length < 6) return;
    lookupTimer = setTimeout(lookup, 250);
  });

  /* Enter walks forward through the boxes instead of submitting early - so the
   * whole item can be typed without reaching for the mouse or Tab. */
  var order = [name, buying, selling, quantity, expiry];
  order.forEach(function (box, index) {
    box.addEventListener('keydown', function (e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      if (index < order.length - 1) {
        order[index + 1].focus();
        order[index + 1].select();
      } else {
        form.requestSubmit ? form.requestSubmit() : save();
      }
    });
  });

  function save() {
    var data = new FormData(form);
    say('Saving...', '');
    fetch(form.action, {
      method: 'POST',
      body: data,
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, body: j }; }); })
      .then(function (res) {
        if (!res.ok || !res.body.ok) {
          say(res.body.error || 'That did not save. Check the boxes.', 'bad');
          return;
        }
        var b = res.body;
        captured += 1;
        counter.textContent = b.total_products;
        say(b.name + ' ' + b.action + '. Scan the next item.', 'good');

        var row = document.createElement('tr');
        row.innerHTML =
          '<td>' + captured + '</td>' +
          '<td>' + escapeHtml(b.name) + '</td>' +
          '<td class="mono">' + escapeHtml(b.barcode || '-') + '</td>' +
          '<td class="num">' + money(b.selling_price) + '</td>' +
          '<td class="num">' + b.stock + '</td>';
        log.insertBefore(row, log.firstChild);

        reset();
      })
      .catch(function () {
        say('The system did not answer. Is it still running?', 'bad');
      });
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    save();
  });

  function escapeHtml(text) {
    var d = document.createElement('div');
    d.textContent = text == null ? '' : text;
    return d.innerHTML;
  }

  /* F2 anywhere jumps back to the barcode box, the same key the till uses. */
  document.addEventListener('keydown', function (e) {
    if (e.key === 'F2') { e.preventDefault(); barcode.focus(); barcode.select(); }
  });

  barcode.focus();
})();
