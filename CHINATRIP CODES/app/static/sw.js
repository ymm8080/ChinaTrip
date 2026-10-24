/* ChinaTrip H5 service worker。
   策略对齐 surmai (github.com/rohitkumbhar/surmai) 的 workbox 配置：
   app-shell 缓存优先+后台刷新，autoUpdate（skipWaiting+claim）；
   API NetworkFirst + 3s 超时回落缓存，离线可看最近一次成功的数据。 */
const VERSION = 'v20'; // v20 2026-10-24: 会话激活时参数表单收成一行摘要——矮视口下输入框被挤出屏幕的实测修复；输入框 flex-shrink:0 硬保护（外壳资产变更必须 +1，否则受控页面一直吃旧缓存）
const CACHE = 'chinatrip-h5-' + VERSION;
const SHELL = [
  './', './index.html', './qrcode.min.js', './sortable.min.js', './manifest.webmanifest',
  './icons/icon-192.png', './icons/icon-512.png',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function networkFirst(req) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 3000);
  return fetch(req, { signal: ctrl.signal })
    .then((res) => {
      clearTimeout(timer);
      if (res && res.status === 200 && (res.type === 'basic' || res.type === 'cors')) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    })
    .catch(() => caches.match(req));
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // API（含跨域 apiBase）：网络优先，断网/超时回落最近缓存
  if (url.pathname.includes('/api/')) {
    e.respondWith(networkFirst(req));
    return;
  }

  // 页面导航与同源静态：缓存优先，后台刷新
  if (req.mode === 'navigate' || url.origin === self.location.origin) {
    e.respondWith(
      caches.match(req, { ignoreSearch: req.mode === 'navigate' }).then((hit) => {
        const refresh = fetch(req)
          .then((res) => {
            if (res && res.status === 200) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy));
            }
            return res;
          })
          .catch(() => hit);
        return hit || refresh;
      })
    );
  }
});
