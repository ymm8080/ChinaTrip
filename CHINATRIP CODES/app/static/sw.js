/* ChinaTrip H5 service worker。
   策略对齐 surmai (github.com/rohitkumbhar/surmai) 的 workbox 配置：
   app-shell 缓存优先+后台刷新，autoUpdate（skipWaiting+claim）；
   API NetworkFirst + 3s 超时回落缓存，离线可看最近一次成功的数据。 */
const VERSION = 'v31'; // v31 2026-10-25: 语言开关白屏永久修复——tab 切换只挂 .nav-item[data-tab]（.nav-item 仅样式）+ call.no_hotline_fallback 词条入壳；v30 修复 localeToggle 无 data-tab 被当页签致全 .tab 失活 + 抢票直达链接引号 + call.slogan 词条；v28 预订 tab 新增「💳 支付 / 代订收款」卡（pay_now + save_method + 我的付款，i18n pay.*）入壳；v27 通话咨询 tab（tab-call + 覆盖层 + 通话记录）+ agent.html 坐席台入壳；v26 双语 P1（i18n.js 入壳 + locale 开关）
const CACHE = 'chinatrip-h5-' + VERSION;
const SHELL = [
  './', './index.html', './i18n.js', './qrcode.min.js', './sortable.min.js', './manifest.webmanifest', './agent.html',
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
