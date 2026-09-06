/* Splitwise Lite shell worker.

   It precaches the shell and answers from that cache. It never asks the network
   itself, so nothing outside the list below can ever reach Cache Storage: task 10's
   data cannot go stale behind a cache nobody remembers exists, and no application
   data, request queue or user input is stored here. Offline entry is cut from v1;
   the shell may open offline, and that is the whole of it.

   To pick a changed asset up locally, bump VERSION and reload. Activation then
   deletes every older cache, so exactly one entry stays in Cache Storage. The cache
   name has to change in the same commit as any change to a file in SHELL: the shell
   is answered from the cache and never revalidated, so until the cache name changes
   a returning user is served the old files however carefully the new ones were
   written. To clear a worker that is stuck: DevTools, Application, Service Workers,
   Unregister.

   That is what SHELL_DIGEST is for. It is a digest of the files in SHELL, recorded
   here by hand rather than computed at run time: computing it would mean fetching
   all nine files before the worker could name its own cache, which fails offline,
   and opening the shell offline is the whole reason this worker exists. A pytest
   test recomputes it from app/ and fails when this line is stale, printing the exact
   line to paste. So an edit to a precached file moves the cache name whether or not
   anybody remembers VERSION, and VERSION is left for the one case the digest cannot
   see: the same shell files, treated differently by this worker. sw.js is
   deliberately not in SHELL, and cannot be: SHELL_DIGEST is recorded in this file,
   so hashing sw.js into it is a self-reference with no fixed point. Every edit
   changes the digest, pasting the digest changes the file, and the new file has a
   new digest again. That reason is unconditional. Secondarily, the browser fetches
   the worker script with service-workers mode 'none', so no worker intercepts it
   and no worker can be handed its own cached self today; if that ever changed, the
   byte-compare against the running script would compare equal forever and the
   worker could never be replaced. */

var VERSION = 'v4';
var SHELL_DIGEST = 'fcb9bcbab4c5';
var CACHE = 'splitwise-lite-shell-' + VERSION + '-' + SHELL_DIGEST;

/* Exactly the shell. Relative, like every other URL in app/, so the directory can
   be mounted under a prefix later without editing this list. */
var SHELL = [
  'index.html',
  'styles.css',
  'app.js',
  'api.js',
  'manifest.json',
  'icons/icon-192.png',
  'icons/icon-512.png',
  'icons/icon-maskable-512.png',
  'icons/apple-touch-icon-180.png'
];

var INDEX = new URL('index.html', self.location.href).href;
var SHELL_URLS = SHELL.map(function (path) {
  return new URL(path, self.location.href).href;
});

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches
      .open(CACHE)
      .then(function (cache) {
        return cache.addAll(SHELL);
      })
      .then(function () {
        /* Take over straight away, so bumping VERSION and reloading picks up the
           new assets instead of waiting for every tab to close. */
        return self.skipWaiting();
      })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (names) {
        return Promise.all(
          names.map(function (name) {
            return name === CACHE ? Promise.resolve(false) : caches.delete(name);
          })
        );
      })
      .then(function () {
        return self.clients.claim();
      })
  );
});

function fromShell(url) {
  return caches
    .open(CACHE)
    .then(function (cache) {
      return cache.match(url);
    })
    .then(function (cached) {
      if (cached) {
        return cached;
      }
      /* Install fails as a whole if any shell file is missing, so this only fires
         if the cache is deleted underneath a live worker. */
      return new Response('Shell cache empty. Reload while online to restore it.', {
        status: 503,
        headers: { 'Content-Type': 'text/plain; charset=utf-8' }
      });
    });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') {
    return;
  }
  /* Never touch the API. No response from it is ever cached, so a balance cannot
     go stale behind a cache nobody remembers exists, and an offline write fails
     loudly rather than looking like a success. */
  if (new URL(request.url).pathname.indexOf('/api') === 0) {
    return;
  }
  /* Every route is the same document, so a navigation is answered with the cached
     index.html and all three routes open offline. */
  if (request.mode === 'navigate') {
    event.respondWith(fromShell(INDEX));
    return;
  }
  if (SHELL_URLS.indexOf(request.url) !== -1) {
    event.respondWith(fromShell(request.url));
    return;
  }
  /* Anything else is left to the browser untouched, and so is never cached. */
});
