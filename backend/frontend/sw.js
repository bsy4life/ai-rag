// SanShin AI Service Worker
const CACHE_NAME = 'sanshin-ai-v1';
const OFFLINE_URL = '/frontend/';

// 需要快取的靜態資源
const STATIC_ASSETS = [
  '/frontend/',
  '/frontend/index.html',
  '/frontend/script.js',
  '/frontend/icon/logo.png',
  '/frontend/icon/icon-192.png',
  '/frontend/icon/icon-512.png',
  '/frontend/manifest.json'
];

// 安裝事件
self.addEventListener('install', (event) => {
  console.log('[SW] Installing...');
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] Caching static assets');
        return cache.addAll(STATIC_ASSETS).catch(err => {
          console.warn('[SW] Some assets failed to cache:', err);
        });
      })
      .then(() => self.skipWaiting())
  );
});

// 啟動事件
self.addEventListener('activate', (event) => {
  console.log('[SW] Activating...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

// 請求攔截
self.addEventListener('fetch', (event) => {
  const request = event.request;
  
  // 只處理 GET 請求
  if (request.method !== 'GET') {
    return;
  }
  
  // API 請求不快取，直接網路優先
  if (request.url.includes('/ask') || 
      request.url.includes('/api/') || 
      request.url.includes('/login') ||
      request.url.includes('/chat_')) {
    event.respondWith(
      fetch(request).catch(() => {
        return new Response(JSON.stringify({ error: '離線模式不支援此操作' }), {
          headers: { 'Content-Type': 'application/json' }
        });
      })
    );
    return;
  }
  
  // 靜態資源：快取優先，網路備援
  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      if (cachedResponse) {
        // 背景更新快取
        fetch(request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, networkResponse.clone());
            });
          }
        }).catch(() => {});
        return cachedResponse;
      }
      
      return fetch(request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const responseClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => {
            cache.put(request, responseClone);
          });
        }
        return networkResponse;
      }).catch(() => {
        // 導航請求返回離線頁面
        if (request.mode === 'navigate') {
          return caches.match(OFFLINE_URL);
        }
        return new Response('Offline', { status: 503 });
      });
    })
  );
});
