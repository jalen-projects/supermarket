/* The phone app's service worker.
 *
 * What it caches, and what it never does:
 *   - The look of the app (CSS, scripts, logo, fonts) is cached, so the app
 *     opens instantly and still looks like itself on a bad connection.
 *   - Pages are NEVER cached. Every page carries money - takings, receipts,
 *     prices - and a figure from this morning shown as if it were now is
 *     worse than no figure. With no connection the phone shows the offline
 *     page, which says so plainly and carries no numbers at all.
 *   - Nothing that is not a GET is touched. A sale or a sign-in always goes
 *     to the server or fails visibly; it is never queued, replayed or faked.
 */
var VERSION = 'maqam-v1';
var SHELL = [
  '/offline/',
  '/static/css/app.css',
  '/static/css/login.css',
  '/static/css/owner.css',
  '/static/fonts/bricolage-grotesque-latin.woff2',
  '/static/brand/maqam-logo.png',
  '/static/brand/app-192.png'
];

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
    // Static files: from the cache, refreshed in the background.
    event.respondWith(caches.open(VERSION).then(function (cache) {
      return cache.match(req).then(function (hit) {
        var fresh = fetch(req).then(function (res) {
          if (res && res.ok) cache.put(req, res.clone());
          return res;
        }).catch(function () { return hit; });
        return hit || fresh;
      });
    }));
  }
  // Everything else (check-ins, lookups, receipts) goes straight to the network.
});
