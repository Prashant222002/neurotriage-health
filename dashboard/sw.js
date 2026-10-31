const C = "nts-2", SHELL = ["/", "/manifest.webmanifest", "/icon.png", "/icon-192.png"];
self.addEventListener("install", e => { e.waitUntil(caches.open(C).then(c => c.addAll(SHELL).catch(() => {}))); self.skipWaiting(); });
self.addEventListener("activate", e => e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== C).map(k => caches.delete(k)))).then(() => self.clients.claim())));
// network-first for the page/static files (always fresh), cache fallback offline; /api/* and other origins are never touched
self.addEventListener("fetch", e => { const u = new URL(e.request.url); if (e.request.method !== "GET" || u.origin !== location.origin || u.pathname.startsWith("/api/")) return;
  e.respondWith(fetch(e.request).then(r => { if (r.ok) { const cp = r.clone(); caches.open(C).then(c => c.put(e.request, cp)); } return r; }).catch(() => caches.match(e.request).then(m => m || caches.match("/")))); });
