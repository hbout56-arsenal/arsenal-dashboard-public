/* Arsenal Dashboard service worker (D107 Phase 2) — app shell for fast/offline repeat loads.
   SAFETY: this is a live trading dashboard, so freshness beats speed:
   - Navigations (the HTML shell) are NETWORK-FIRST → always fresh when online; the cached copy
     is only an OFFLINE fallback. No stale-shell trap.
   - The JSON data feeds are CROSS-ORIGIN (raw.githubusercontent.com) and are NOT intercepted at
     all — the app's own ?t= cache-busting + freshness logic is left completely untouched.
   - Only same-origin static assets (icon, manifest) are cache-first with a background refresh. */
const CACHE = "arsenal-shell-v1";
const SHELL = ["./", "./index.html", "./manifest.webmanifest", "./icon.svg"];

self.addEventListener("install", function(e){
  e.waitUntil(caches.open(CACHE).then(function(c){ return c.addAll(SHELL); }).then(function(){ return self.skipWaiting(); }));
});

self.addEventListener("activate", function(e){
  e.waitUntil(
    caches.keys().then(function(keys){ return Promise.all(keys.filter(function(k){ return k !== CACHE; }).map(function(k){ return caches.delete(k); })); })
      .then(function(){ return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function(e){
  var req = e.request;
  if(req.method !== "GET") return;
  var url = new URL(req.url);
  // cross-origin (JSON feeds) → do not touch; app freshness/cache-busting stays authoritative
  if(url.origin !== self.location.origin) return;

  if(req.mode === "navigate" || url.pathname.endsWith("/index.html") || url.pathname.endsWith("/")){
    // NETWORK-FIRST shell: fresh online, cached copy only as offline fallback
    e.respondWith(
      fetch(req).then(function(res){
        var copy = res.clone();
        caches.open(CACHE).then(function(c){ c.put("./index.html", copy); });
        return res;
      }).catch(function(){ return caches.match("./index.html"); })
    );
  } else {
    // static shell assets: cache-first + background refresh
    e.respondWith(
      caches.open(CACHE).then(function(cache){
        return cache.match(req).then(function(cached){
          var net = fetch(req).then(function(res){ if(res && res.ok) cache.put(req, res.clone()); return res; }).catch(function(){ return cached; });
          return cached || net;
        });
      })
    );
  }
});
