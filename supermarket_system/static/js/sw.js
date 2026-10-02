/* The phone app's service worker.
 *
 * What it caches, and what it never does:
 *   - The look of the app (CSS, scripts, logo, fonts) is cached, so the app
 *     opens instantly and still looks like itself on a bad connection - and
 *     replaced whole whenever a deploy changes it (see VERSION).
 *   - Pages are NEVER cached. Every page carries money - takings, receipts,
 *     prices - and a figure from this morning shown as if it were now is
 *     worse than no figure. With no connection the phone shows the offline
 *     page, which says so plainly and carries no numbers at all.
 *   - Nothing that is not a GET is touched. A sale or a sign-in always goes
 *     to the server or fails visibly; it is never queued, replayed or faked.
 */
// Stamped by the server from the files themselves (shop/views.py), so every
// deploy that changes the look gets a new name here, and the old cache - the
// old colours, the old screens - is thrown away the next time the app opens.
var VERSION = 'maqam-__STAMP__';
var SHELL = ['/offline/'];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(VERSION).then(function (cache) { return cache.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== VERSION; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  if (req.mode === 'navigate') {
    // Network only. The offline page if the network is not there.
    event.respondWith(fetch(req).catch(function () {
      return caches.match('/offline/');
    }));
    return;
  }

  if (url.pathname.indexOf('/static/') === 0) {
    // A file named by its content (app.3f9c1a2b.css) never changes, so it is
    // served straight from the phone: no trip to the server at all. Anything
    // else is asked for fresh, with the saved copy only as a fallback.
    var named = /\.[0-9a-f]{12}\./.test(url.pathname);
    event.respondWith(caches.open(VERSION).then(function (cache) {
      return cache.match(req).then(function (hit) {
        if (hit && named) return hit;
        return fetch(req).then(function (res) {
          if (res && res.ok) cache.put(req, res.clone());
          return res;
        }).catch(function () { return hit; });
      });
    }));
    return;
  }
  // Everything else (check-ins, lookups, receipts) goes straight to the network.
});
