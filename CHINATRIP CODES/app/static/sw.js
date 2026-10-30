/* ChinaTrip H5 service worker。
   策略对齐 surmai (github.com/rohitkumbhar/surmai) 的 workbox 配置：
   app-shell 缓存优先+后台刷新，autoUpdate（skipWaiting+claim）；
   API NetworkFirst + 3s 超时回落缓存，离线可看最近一次成功的数据。 */
const VERSION = 'v50'; // v50 2026-10-30: 夜间雨不再完全忽略——天头天气右侧补「🌙夜间<夜天气>」标注（如 🌙夜间小雨，与夜间横幅同 wxWetText 口径）；白天主图标/横幅/自动室内仍只看 day_weather // v49 2026-10-30: 雨天横幅文案带时段与量级——「白天小雨」「夜间小雨」（取 cast.day/night_weather 原文，EN 语境为读侧翻译文本） // v48 2026-10-30: 雨天双窗——夜间雨只影响夜间露天活动（游船观景/夜游等 evening 点自动换到晴夜+夜间横幅），白天雨不再动夜间点 // v47 2026-10-30: 英文版 clarify 追问卡死修复（偏好轮关键词加英文匹配 /prefer|sightsee/i + 提交文本本地化 + 提示不再限首轮） // v46 2026-10-30: 行程卡站点删除按钮加「🗑 删除」字样（card.del zh/en 词条） // v45 2026-10-30: 雨天判定改白天窗——夜间雨不影响白天行程（横幅/自动室内/图标只看 day_weather，用户拍板「避免露天活动与下雨时间段一致」） // v44 2026-10-30: 雨天收口——天头天气图标与雨天横幅同口径（夜间雨白天晴显 🌦️，修「横幅有雨图标晴」）+ 规划自动雨天排室内（整段有雨室内优先/部分日有雨自动对调，不问用户）+ 横幅去「回复重排」改备伞提示 // v43 2026-10-30: 桌面排版修复（#scrim 基础 display:none，v42 遮罩占掉 grid 第一格致侧栏/主区错位） + 布局按设备两套（断点叠加 pointer:coarse）+ 打开页面=行程页最近行程（去 localStorage 会话恢复） + 保存行程右边兜底重新规划 //  // v42 2026-10-30: 移动端（≤760px）左栏改抽屉菜单：左上角 ☰ 开关 + 遮罩，桌面端不变 // v41 2026-10-27: 行程卡片删除「✅ 到了」打卡按钮（fb-btn data-kind=visit），仅留 👍/👎/✍️ 点评；清理 visit 分支与 card.visited/plan.fb.checked* 文案
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
