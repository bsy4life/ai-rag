self.addEventListener('install', function (e) {
  self.skipWaiting();
});

self.addEventListener('fetch', function (event) {
  // 可以加進階快取，這裡單純 passthrough
});