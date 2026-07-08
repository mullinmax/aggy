// Aggy service worker — makes the app installable and resilient offline.
//
// Strategy:
//   * App shell (HTML pages, static CSS/JS/icons): network-first, falling
//     back to the cache so a flaky connection still opens the app. Fresh
//     responses are written back so the cache tracks the latest deploy
//     (static assets are cache-busted with ?v=<mtime>, so this stays valid).
//   * API / auth requests and anything non-GET: never touched — always go
//     straight to the network so we never serve stale feed data or tokens.

const CACHE = 'aggy-shell-v1';

// Minimal shell precached on install so the app can cold-start offline.
const PRECACHE = [
  '/app',
  '/login',
  '/static/favicon.svg',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Only the app shell is cacheable. Everything the app talks to for data is not.
function isShellRequest(url) {
  if (url.pathname.startsWith('/static/')) return true;
  return url.pathname === '/app' || url.pathname === '/login';
}

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (!isShellRequest(url)) return;

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request).then((cached) => cached || caches.match('/app')))
  );
});
