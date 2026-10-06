/* The till checking in, once a minute.
 *
 * Every signed-in screen tells the server "this till is alive". If every till
 * goes quiet while the shop should be open, the server emails the owner -
 * that is the whole answer to "the cashier switched the router off".
 *
 * The till is known by a random id kept in this browser, so the owner's list
 * shows each counter separately. If storage is blocked the id lives only for
 * this page load, which still keeps the alarm quiet while the till is in use.
 */
(function () {
  var cfg = document.getElementById('till-cfg');
  if (!cfg || !window.fetch) return;

  // Each shop keeps its own names in the browser (shop/brand.py) - MAQAM's
  // are 'maqam.*', exactly as they always were, so no till is forgotten.
  var STORE = cfg.getAttribute('data-store') || 'maqam';
  var key;
  try {
    key = localStorage.getItem(STORE + '.till');
    if (!key) {
      key = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
        : String(Date.now()) + Math.random().toString(16).slice(2);
      localStorage.setItem(STORE + '.till', key);
    }
  } catch (e) {
    key = 'tmp-' + String(Date.now()) + Math.random().toString(16).slice(2);
  }

  var label = (/Android|iPhone|iPad/i.test(navigator.userAgent) ? 'Phone' : 'Computer')
    + ' - ' + (cfg.getAttribute('data-user') || '');
  var token = cfg.getAttribute('data-csrf');

  function ping() {
    fetch(cfg.getAttribute('data-url'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
      body: JSON.stringify({ till: key, label: label })
    }).catch(function () { /* offline - that is exactly what the server notices */ });
  }

  ping();
  setInterval(ping, 60000);
})();
