// Service worker: keeps a copy of the app's own files so it opens quickly from
// the Home Screen. It always tries the network first, so updates show up right
// away, and it never stores API data (jobs, profile).
// Bump CACHE when you bump ?v= in index.html.

const CACHE = "jobmatch-v3";
const APP_FILES = [
  "/",
  "/static/style.css?v=3",
  "/static/app.js?v=3",
  "/static/icons/icon-192.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(APP_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const isAppFile = url.pathname === "/" || url.pathname.startsWith("/static/");
  if (event.request.method !== "GET" || url.origin !== self.location.origin || !isAppFile) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
