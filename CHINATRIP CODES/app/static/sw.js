/* ChinaTrip H5 service worker。
   策略对齐 surmai (github.com/rohitkumbhar/surmai) 的 workbox 配置：
   app-shell 缓存优先+后台刷新，autoUpdate（skipWaiting+claim）；
   API NetworkFirst + 3s 超时回落缓存，离线可看最近一次成功的数据。 */
const VERSION = 'v72'; // v72 2026-11-07: 同街族并卡上卡面——直线 ≤1km 的同日站点折进首件主卡（PlanStop chips），主卡名下只读一行「🚶 同街联游：子站（时长）· …」，主卡时长=族内最长一站不再叠加；删除/换点/拖拽作用于整卡（card.family.pre 中英） // v71 2026-11-07: 规划起始页精简+交通选择——中间城市3 移除（保留中间城市1/2），起始城市与中间城市1之间加「交通」下拉（按距离自动=后端距离闸 600km/🚄火车/✈️飞机，全程城际段去程/途经/返程统一口径，规划后单段仍可改乘）；plan/start 请求与 origin 重建带 intercity_mode，落 PlanSession持久（i18n plan.transport* 中英） // v70 2026-11-06: 悬停简介覆盖备选 chip——备选按钮 hover 同款 .site-pop（首行 ↺ 换点提示 card.alt.popHint 中英、次行档号·时长·距离 data-bits，原 title 信息搬入浮层）；chip 挂 data-city/data-bits、原生 title 摘除防双 tooltip，点击换点即收浮层；主点 hover 行为不变 // v69 2026-11-06: 站点悬停简介浮层——光标停在站点名 350ms 弹 .site-pop 卡（📖简介/⭐评分/⏱建议时长/📍地址/🕐开放时间），/api/pois/detail 同端点 (city,name) 内存缓存、EN 语境读 intro_en（detail 出参新增 intro_en 并出）；移入浮层可续读 250ms 宽限，滚屏/改窗/点击即关，点击仍开完整简介气泡，触屏无 hover 不受影响；站点名原生 title 摘除防双 tooltip（i18n 复用 brief.addr/hours/none；zh 词典补 brief.none 一条，EN 已有） // v68 2026-11-06: 行程卡预约信息全覆盖——后端 _reservation_hint 在「库列>名单v0」后接入 09 热门预约景点表（data/reservation_pois.csv 167 点读侧索引：需预约=提前N天+渠道+放票时刻，无需预约=渠道+外籍护照购票口径，中英双语框）；卡上仍无预约数据的非餐/非酒店条目兜底显示「预约信息无」（i18n card.resv.none 中英），餐位/酒店不显示预约行 // v67 2026-11-05: CALL TAXI 两改——①按钮从行最右挪回车程文字右侧内联（去掉 space-between 拉边布局），文案「CALL TAXI」→「🚕 TAXI」（打车标志+TAXI，中英同形）；②点击后手机端手势链内同步拼 amapuri://drive/taxi/（起点 NAV.meReal 时带 slon/slat/sname 截 6 位，终点 dlon/dlat/dname）经 openHandoff 直唤高德打车页——免「打开高德App」二次按键，未装 App 2s 探测落提示，桌面端不跳 scheme 仍走导航页扫码桥 // v66 2026-11-04: 行程卡「CALL TAXI」按钮——已算好公里数+打车时间的站间段（>1.5km）右侧一键转导航页打车：起点=当前位置（手动改过则复位定位点），终点=下一站坐标，复用导航页 deeplink+扫码桥全流程（callTaxiTo；i18n card.callTaxi* 中英） // v65 2026-11-04: 预订页 🎭演出/🎫景点 目录卡显示场次/营业时间——后端 ShowCard 透传 poi.opening_hours(+_en)，目录卡 🕐 行渲染（演出行库内 47/48 有场次文本；修「营业时间和演出场次都没有显示」反馈的目录侧） // v64 2026-11-03: 星级饭店标签读侧补全——BRIEF_TAGS 与 i18n 加 star_1…star_5（五星级饭店…一星级饭店 / 5-star hotel…1-star hotel），配合库内 mct 打标 230 行 // v63 2026-11-03: 开始日期默认下周一（2026-11-03 拍板，原 v62 前默认今天）——规划表单初始化与旧行程✏️修改无存档日期的兜底都改为 nextMondayBeijingIso()（(8-周几)%7 周一归 7，恒为未来 1-7 天内的周一，北京口径）：当天出发来不及订票/预约，下周一给足预订窗口 // v62 2026-11-01: 天头天气两修——①城市/天气按当天活动城（dayActivityCity：非转场条目城市，纯转场天回落醒来城 base_city），修「首日行程在落地城、天头却显示出发城」；②无预报的天（行程从历史日期开始，预报 casts 都从今天起）在今天/历史日回落实况（live +（实况）标注），未来日期仍等 forecast14 // v61 2026-11-01: 载入行程（auto-open/✏️修改）同步参数表单——预填城市/逐城天数/出发日期，修「选了西安参数摘要却显示 上海→杭州·共1天」、以及✏️展开表单点🚀按默认杭州路线开新规划的隐患 // v60 2026-11-01: 行程卡「✏️ 换景点」——每个景点名可编辑（系统餐位除外）：点 ✏️ 原地变输入框，关键字实时检索 POI 库（/api/pois/search）下拉候选（名字/评分/层级/无坐标标注），选中即原位替换并重排当天时链（/items/{id}/replace）；库内无匹配或清空后回车=留空（当天只保留午餐/晚餐），Esc/失焦取消 // v59 2026-10-31: 行程导入追加 .doc 与 OCR——.doc（Word97 二进制）按 FIB/分段表抽正文，扫描版 PDF 与图片（png/jpg/webp/bmp）自动走 GLM 视觉 OCR（glm-4.6v-flash，429 切备用池），OCR 仍无文字才报错 // v58 2026-10-31: v58 2026-10-31: 行程页新增 📥 导入行程文件（PDF/Word/Excel/文本/HTML → 服务端解析+AI 结构化 → 预览弹层逐天逐站 → 确认后生成新行程，列表行标注 📄 源文件名+文件ID，每次导入新文件ID） // v57 2026-10-31: v57 2026-10-31: 行程卡回合的 reply 文字压到行程卡下面渲染——行程卡一长，顶部的说明/追问整段被顶出视野用户看不见（看熊猫案用户拍板「问题移到最下面」） // v56 2026-10-31: 行程中心看板每次进入都刷新——聊天排期后 TRIP.loaded 旧壳不再钉死看板（看水利工程案：已排期心愿不显示） // v55 2026-10-31: 删行程时名下已排期心愿自动回心愿单（后端 scheduled→wishlist，booked 不动）——行程页删除确认文案同步提示（itin.delConfirmSuf 中英） // v54 2026-10-30: 行程中心已排期/已订卡标注所属行程——🧳 行程ID·行程名（/api/v1/trip-items 回填 itinerary_name=城市链） // v53 2026-10-30: 修 plan 渲染中断——v52 改名 legSeg 漏改拼接处（walkSeg is not defined，行程卡不出） // v52 2026-10-31: 卡片站间出行默认出租车口径——距离+车程（含半小时叫车，≤1.5km 仍步行），导航链接切驾车 // v51 2026-10-30: SW 接管自愈——controllerchange 时页面自动重载换新壳（旧壳赖站事故根治，发版后一次刷新即更新） // v50 2026-10-30: 夜间雨不再完全忽略——天头天气右侧补「🌙夜间<夜天气>」标注（如 🌙夜间小雨，与夜间横幅同 wxWetText 口径）；白天主图标/横幅/自动室内仍只看 day_weather // v49 2026-10-30: 雨天横幅文案带时段与量级——「白天小雨」「夜间小雨」（取 cast.day/night_weather 原文，EN 语境为读侧翻译文本） // v48 2026-10-30: 雨天双窗——夜间雨只影响夜间露天活动（游船观景/夜游等 evening 点自动换到晴夜+夜间横幅），白天雨不再动夜间点 // v47 2026-10-30: 英文版 clarify 追问卡死修复（偏好轮关键词加英文匹配 /prefer|sightsee/i + 提交文本本地化 + 提示不再限首轮） // v46 2026-10-30: 行程卡站点删除按钮加「🗑 删除」字样（card.del zh/en 词条） // v45 2026-10-30: 雨天判定改白天窗——夜间雨不影响白天行程（横幅/自动室内/图标只看 day_weather，用户拍板「避免露天活动与下雨时间段一致」） // v44 2026-10-30: 雨天收口——天头天气图标与雨天横幅同口径（夜间雨白天晴显 🌦️，修「横幅有雨图标晴」）+ 规划自动雨天排室内（整段有雨室内优先/部分日有雨自动对调，不问用户）+ 横幅去「回复重排」改备伞提示 // v43 2026-10-30: 桌面排版修复（#scrim 基础 display:none，v42 遮罩占掉 grid 第一格致侧栏/主区错位） + 布局按设备两套（断点叠加 pointer:coarse）+ 打开页面=行程页最近行程（去 localStorage 会话恢复） + 保存行程右边兜底重新规划 //  // v42 2026-10-30: 移动端（≤760px）左栏改抽屉菜单：左上角 ☰ 开关 + 遮罩，桌面端不变 // v41 2026-10-27: 行程卡片删除「✅ 到了」打卡按钮（fb-btn data-kind=visit），仅留 👍/👎/✍️ 点评；清理 visit 分支与 card.visited/plan.fb.checked* 文案
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
