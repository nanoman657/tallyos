// Service worker: app shell works offline; API calls always go to the network.
const CACHE = "tallyos-v2";
const SHELL = [
  "./", "index.html", "join.html", "css/app.css", "manifest.webmanifest", "icons/icon.svg",
  "js/app.js", "js/api.js", "js/ui.js", "js/charts.js", "js/join.js",
  "js/views/today.js", "js/views/schedule.js", "js/views/clients.js", "js/views/growth.js", "js/views/more.js",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.startsWith("/api/")) return;
  // Network first so deploys show up immediately; fall back to cache offline.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("index.html"))),
  );
});
