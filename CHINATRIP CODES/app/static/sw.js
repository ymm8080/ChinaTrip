/* ChinaTrip H5 service worker。
   策略对齐 surmai (github.com/rohitkumbhar/surmai) 的 workbox 配置：
   app-shell 缓存优先+后台刷新，autoUpdate（skipWaiting+claim）；
   API NetworkFirst + 3s 超时回落缓存，离线可看最近一次成功的数据。 */
const VERSION = 'v38'; // v38 2026-10-27: 预订 tab 新增「🎫 景点」分区（/booking-auto/sites 目录：旅游品类评分热门榜 + 订票直达 geo 分流，与 🎭 演出同构）；v37 2026-10-27: 演出预订补全——预订 tab 新增「🎭 演出」分区（/booking-auto/shows 目录 + 订票直达走 order-intent geo 分流，铁律 23 浮层）+ 行程卡演出行无 booking_url 也渲染（geo 模板兜底）+ 回填列表 site_ticket 🎭 图标 + klook/other 渠道名；v36 2026-10-27: 演出预订路径 A（show_booking_design P0）——演出条目「🎭 演出票务 · 订票直达」行（poi.booking_url 成品页直开）+ 锁单确认窗文案（提交后库存仅锁 4–15 分钟，热门更短）+ 抢票直达带 data-url 官方页优先；v35 2026-10-25: api() 全量带 X-Lang 头（后端 L() 双语）+ 分享链接 EN 模式带 ?lang=en + 订票卡标签 EN 抑制对齐 bk.unified；v34 2026-10-25: itinSavedList 加载占位补 data-i18n=itin.loading（EN 模式最后一块静态中文闪烁）；v33 2026-10-25: 全量 EN 迁移（JS 动态文案 477 处 I18N.tf + en 词典 ~700 条 + 守门 C 门）+ 规划会话 lang 透传（EN 模式 LLM 英文回复）+ 登录弹窗 3 按钮补 data-i18n；v32 2026-10-25: 旧行程打开缺省今天出发日期（日期+天气立现，保存落库自愈）；v31 2026-10-25: 语言开关白屏永久修复——tab 切换只挂 .nav-item[data-tab]（.nav-item 仅样式）+ call.no_hotline_fallback 词条入壳；v30 修复 localeToggle 无 data-tab 被当页签致全 .tab 失活 + 抢票直达链接引号 + call.slogan 词条；v28 预订 tab 新增「💳 支付 / 代订收款」卡（pay_now + save_method + 我的付款，i18n pay.*）入壳；v27 通话咨询 tab（tab-call + 覆盖层 + 通话记录）+ agent.html 坐席台入壳；v26 双语 P1（i18n.js 入壳 + locale 开关）
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
