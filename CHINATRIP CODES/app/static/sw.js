/* ChinaTrip H5 service worker。
   策略对齐 surmai (github.com/rohitkumbhar/surmai) 的 workbox 配置：
   app-shell 缓存优先+后台刷新，autoUpdate（skipWaiting+claim）；
   API NetworkFirst + 3s 超时回落缓存，离线可看最近一次成功的数据。 */
// v84 2026-11-13: 重新规划不再回到上次行程——自由输入框里的一整句新行程（换城市/换天数）优先于表单回填值；后端换局时返回新 session_id，前端跟随并同步表单，旧行程不被改动。
// v87 2026-11-14: 文字/视频简报与图片读点先确认再落心愿单——起步页长描述读出的地点不再自动钉必去，改走「必去/可选」确认轮；聊天框相机按钮上传图片（笔记截图/行程照片）读地点，同一轮待确认（默认全选，点掉不要的）。
// v88 2026-11-14: 行前信息确认卡——每次开新规划先核对出发日期、行程日期是否覆盖到达日/离开日，覆盖就要去返程航班/车次或当地到达·离开时刻（可跳过，跳过=按常规时刻排）；打字开局只读文字，表单默认值（上海→上海 1 天）不再被当成用户意图。
// v89 2026-11-14: 行前卡二拍——删日期快捷 chip；去程/返程改「到达/离开」，每行=班次号+日期+当地时刻；不填班次与时刻的那天按全天游玩规划（引擎撤腿重排），填了但当天无城际腿（单城行程）也补合成腿吸收。
// v91 2026-11-14: 行前卡三拍——到达/离开改「开始/结束」；删顶部独立出发日期（开始行日期=出发日期）；开始/结束各=班次号（可选）+日期+时刻（默认 8:30 / 21:30）；保持默认时刻=没填，那侧按全天游玩规划；「跳过」按钮移除（保持默认提交即同义）。
// v92 2026-11-14: 时刻语义写明——开始行时刻=当天到达时刻、结束行时刻=离开（起飞/发车）时刻（用户口径「改过的时刻默认为运输腿的到达时间或者离开时间」）；班次号查不到而时刻给过 → 回退按用户时刻落位。
// v93 2026-11-14: 行前卡开始/结束两行字段顺序改为 日期 → 时间 → 航班/火车号（可选）。
// v95 2026-11-14: 备选 chip 可拖——按住 chip 前 ⠿ 把手拖到任意两天之间即在该处插入新卡（主点保留；点 chip 仍是原位换点）；后端 POST /items/{id}/insert-alt 按落点插位、当天排不下按档号/距离让位，撤下谁写进回复与假设标注。
// v94 2026-11-14: 文字 vs 表单路线冲突确认——两者不一致时把两边路线/天数摆出来让用户选（用文字/用表单），不再静默以文字为准。
// v96 2026-11-14: 行前卡开始/结束行改固定两栏——日期+时间永远在左，航班/火车号列固定贴右（窄屏换行也右对齐）。
// v97 2026-11-14: 确认卡 v2——文字/表单/行前卡不一致的每一处都逐条摆出（路线、天数、班次号、行前卡 vs 表单天数），用户逐条选边后一次提交；后端 days_override/班次覆写落地。
const VERSION = 'v97'; // v86 2026-11-14: 多语言骨架（DESIGN language_nlang_switch_design_2026-11-03 §2.2，P1 机制 + L2 ja/ko 种子）——①i18n.js 字典改短码键（zh-CN→zh，存量 ct_locale 读侧归一）、新增 ja/ko 种子词典与回退链 loc→en→zh（半翻译语言按 key 逐条回退，en 为 pivot）、LANGS 注册表、二元 toggle 升级语言 picker（底部弹层，母语名+当前项勾选）、city/pick 非 zh 走 en 源、<html lang> 按 LANGS.htmlTag 标注；②index.html X-Lang/plan:start lang/share ?lang 直通 I18N.locale() 短码（后端 BCP47 归一），城市下拉 ja/ko 显示英文名，提醒时间线日期按 locale 格式化；③后端 lang_ctx 支持位置制 L(zh,en,…)+SUPPORTED（zh=0/en=1 冻结，ja/ko append）+normalize_lang，plan 会话 lang 白名单走 SUPPORTED，ja/ko 提示词档直生成。字典变更必须 bump 版本拉新缓存 // v85 2026-11-13: 「点重新规划还是上次行程」修复——①autoOpenLatestItin 载入最近行程要 1–28 秒，期间用户一旦重新规划/开始规划/发消息（planTouch 代号）就整段放弃，不再把旧行程画回对话流；②SW controllerchange 自动整页重载遇到在途请求（planWorking）或屏上有会话（planSession）只提示不重载，不再把刚生成的行程冲掉；③planRouteForm 结束城市「（不经过）」不再把空城串塞进 cities。 // v84 2026-11-13: 规划「网络错误：无法连接 API」修复——断线重试梯 1.5s/4s(≈5.5s)→1.2/2.5/5/10/20s(≈39s)，覆盖 keepalive 判活 20s+进程拉起窗（旧窗内点规划只会看到网络错误），首轮重试提示「服务未响应，正在自动重试…」；生成中文案 10s→约 30 秒（实测单次 30-40s） // v82 2026-11-13: 空餐卡腿渲染中断修复——自由安排的午饭/晚饭无 POI（只有 anchor_location），旧码百度分支读 from.location.lat 抛 TypeError 整卡「数据已返回但渲染中断」；腿链接/TAXI 按钮/导航终点/预订锚点统一走 legPoint()（location→anchor_location，缺坐标降级纯文字不出死链） // v80 2026-11-11: 照片回源接线（F2/F4，DESIGN poi_photos_functional_design）——①简介气泡空图态「🔍 找图」按钮（brief.findPhoto 中英）：POST /api/pois/photos/fetch 触发服务端确定性回源（amap v5→amap 按名搜→wikimedia，24h 冷却服务端把关），成功就地渲染首两张并接灯箱，拉空「🔍 暂无图」1.5s 后恢复可点；②死图上报 reportDeadPhoto：简介双图/悬停首图/灯箱 onerror 摘除同时 fire-and-forget POST /api/pois/photos/report-dead（poi_id 维度计数，≥3 由刷新 job 重拉）；openPhotoLB 加 poiId 参数 // v79 2026-11-11: 简介气泡并排双图——enrichBrief 有 ≥2 张时 photos 前两张 flex 并排（各 max-height 140px、object-fit:cover、cursor:pointer），第 3 张起仍点图开灯箱翻看；仅 1 张（如华清宫维基源）维持单图 // v78 2026-11-11: 照片灯箱（多张图入口）——悬停首图与简介气泡首图均可点开 openPhotoLB 看全部 photos：左右 40% 点击/←→键切换、底部 名称+序号/总数+来源小字、✕/中点/Esc 关闭，纯前端零请求 // v77 2026-11-11: 「想排未排」备选 chip——可替代品跨品类（2026-11-11 拍板）：规划器必去让位/弃排点结构化留痕 plan.unplaced，装配期挂上同城相关卡右侧 chip 区（原 day_hint 天优先），亮「想去/Want」徽标（card.alt.lv.want 中英）与同级备选区分，点击走同一换点端点；想排 chip 排最前、总量仍 ≤3 // v76 2026-11-11: 悬停简介浮层加首图——sitePopShow 渲染 detail 响应里的 photos[0]（本就随接口到达，纯渲染零额外请求；max-height 100px、loading=lazy、referrerpolicy=no-referrer、onerror 原地摘除不留占位） // v75 2026-11-10: 站点简介气泡透出点评综述（P7b 证据链）——/api/pois/detail 出参并出 review_summary/_en/_source（enrich 管道已入库，纯读侧），简介气泡在 📖 简介行后加 💬 综述行（双语 I18N.pick，source 小字标注复用 brief.sourcePre/Close；未蒸馏点不渲染） // v74 2026-11-08: 规划表单「交通」下拉从起始城市与中间城市1之间挪到中间城市1与中间城市2之间（控件与语义不变：全程城际段统一口径，规划后单段仍可改乘）；结束城市默认从杭州改为上海（planCityRender 兜底值） // v73 2026-11-07: 同街族并卡二拍「并卡不消失」——子站不再挤一行灰字，每站独立一行（名+时长，card.family.pre/dur 中英）；后端族卡 bvt 聚合（夜档成员信号>锚值，十二时辰夜档把大雁塔并卡拉到下午/晚场） // v72 2026-11-07: 同街族并卡上卡面——直线 ≤1km 的同日站点折进首件主卡（PlanStop chips），主卡名下只读一行「🚶 同街联游：子站（时长）· …」，主卡时长=族内最长一站不再叠加；删除/换点/拖拽作用于整卡（card.family.pre 中英） // v71 2026-11-07: 规划起始页精简+交通选择——中间城市3 移除（保留中间城市1/2），起始城市与中间城市1之间加「交通」下拉（按距离自动=后端距离闸 600km/🚄火车/✈️飞机，全程城际段去程/途经/返程统一口径，规划后单段仍可改乘）；plan/start 请求与 origin 重建带 intercity_mode，落 PlanSession持久（i18n plan.transport* 中英） // v70 2026-11-06: 悬停简介覆盖备选 chip——备选按钮 hover 同款 .site-pop（首行 ↺ 换点提示 card.alt.popHint 中英、次行档号·时长·距离 data-bits，原 title 信息搬入浮层）；chip 挂 data-city/data-bits、原生 title 摘除防双 tooltip，点击换点即收浮层；主点 hover 行为不变 // v69 2026-11-06: 站点悬停简介浮层——光标停在站点名 350ms 弹 .site-pop 卡（📖简介/⭐评分/⏱建议时长/📍地址/🕐开放时间），/api/pois/detail 同端点 (city,name) 内存缓存、EN 语境读 intro_en（detail 出参新增 intro_en 并出）；移入浮层可续读 250ms 宽限，滚屏/改窗/点击即关，点击仍开完整简介气泡，触屏无 hover 不受影响；站点名原生 title 摘除防双 tooltip（i18n 复用 brief.addr/hours/none；zh 词典补 brief.none 一条，EN 已有） // v68 2026-11-06: 行程卡预约信息全覆盖——后端 _reservation_hint 在「库列>名单v0」后接入 09 热门预约景点表（data/reservation_pois.csv 167 点读侧索引：需预约=提前N天+渠道+放票时刻，无需预约=渠道+外籍护照购票口径，中英双语框）；卡上仍无预约数据的非餐/非酒店条目兜底显示「预约信息无」（i18n card.resv.none 中英），餐位/酒店不显示预约行 // v67 2026-11-05: CALL TAXI 两改——①按钮从行最右挪回车程文字右侧内联（去掉 space-between 拉边布局），文案「CALL TAXI」→「🚕 TAXI」（打车标志+TAXI，中英同形）；②点击后手机端手势链内同步拼 amapuri://drive/taxi/（起点 NAV.meReal 时带 slon/slat/sname 截 6 位，终点 dlon/dlat/dname）经 openHandoff 直唤高德打车页——免「打开高德App」二次按键，未装 App 2s 探测落提示，桌面端不跳 scheme 仍走导航页扫码桥 // v66 2026-11-04: 行程卡「CALL TAXI」按钮——已算好公里数+打车时间的站间段（>1.5km）右侧一键转导航页打车：起点=当前位置（手动改过则复位定位点），终点=下一站坐标，复用导航页 deeplink+扫码桥全流程（callTaxiTo；i18n card.callTaxi* 中英） // v65 2026-11-04: 预订页 🎭演出/🎫景点 目录卡显示场次/营业时间——后端 ShowCard 透传 poi.opening_hours(+_en)，目录卡 🕐 行渲染（演出行库内 47/48 有场次文本；修「营业时间和演出场次都没有显示」反馈的目录侧） // v64 2026-11-03: 星级饭店标签读侧补全——BRIEF_TAGS 与 i18n 加 star_1…star_5（五星级饭店…一星级饭店 / 5-star hotel…1-star hotel），配合库内 mct 打标 230 行 // v63 2026-11-03: 开始日期默认下周一（2026-11-03 拍板，原 v62 前默认今天）——规划表单初始化与旧行程✏️修改无存档日期的兜底都改为 nextMondayBeijingIso()（(8-周几)%7 周一归 7，恒为未来 1-7 天内的周一，北京口径）：当天出发来不及订票/预约，下周一给足预订窗口 // v62 2026-11-01: 天头天气两修——①城市/天气按当天活动城（dayActivityCity：非转场条目城市，纯转场天回落醒来城 base_city），修「首日行程在落地城、天头却显示出发城」；②无预报的天（行程从历史日期开始，预报 casts 都从今天起）在今天/历史日回落实况（live +（实况）标注），未来日期仍等 forecast14 // v61 2026-11-01: 载入行程（auto-open/✏️修改）同步参数表单——预填城市/逐城天数/出发日期，修「选了西安参数摘要却显示 上海→杭州·共1天」、以及✏️展开表单点🚀按默认杭州路线开新规划的隐患 // v60 2026-11-01: 行程卡「✏️ 换景点」——每个景点名可编辑（系统餐位除外）：点 ✏️ 原地变输入框，关键字实时检索 POI 库（/api/pois/search）下拉候选（名字/评分/层级/无坐标标注），选中即原位替换并重排当天时链（/items/{id}/replace）；库内无匹配或清空后回车=留空（当天只保留午餐/晚餐），Esc/失焦取消 // v59 2026-10-31: 行程导入追加 .doc 与 OCR——.doc（Word97 二进制）按 FIB/分段表抽正文，扫描版 PDF 与图片（png/jpg/webp/bmp）自动走 GLM 视觉 OCR（glm-4.6v-flash，429 切备用池），OCR 仍无文字才报错 // v58 2026-10-31: v58 2026-10-31: 行程页新增 📥 导入行程文件（PDF/Word/Excel/文本/HTML → 服务端解析+AI 结构化 → 预览弹层逐天逐站 → 确认后生成新行程，列表行标注 📄 源文件名+文件ID，每次导入新文件ID） // v57 2026-10-31: v57 2026-10-31: 行程卡回合的 reply 文字压到行程卡下面渲染——行程卡一长，顶部的说明/追问整段被顶出视野用户看不见（看熊猫案用户拍板「问题移到最下面」） // v56 2026-10-31: 行程中心看板每次进入都刷新——聊天排期后 TRIP.loaded 旧壳不再钉死看板（看水利工程案：已排期心愿不显示） // v55 2026-10-31: 删行程时名下已排期心愿自动回心愿单（后端 scheduled→wishlist，booked 不动）——行程页删除确认文案同步提示（itin.delConfirmSuf 中英） // v54 2026-10-30: 行程中心已排期/已订卡标注所属行程——🧳 行程ID·行程名（/api/v1/trip-items 回填 itinerary_name=城市链） // v53 2026-10-30: 修 plan 渲染中断——v52 改名 legSeg 漏改拼接处（walkSeg is not defined，行程卡不出） // v52 2026-10-31: 卡片站间出行默认出租车口径——距离+车程（含半小时叫车，≤1.5km 仍步行），导航链接切驾车 // v51 2026-10-30: SW 接管自愈——controllerchange 时页面自动重载换新壳（旧壳赖站事故根治，发版后一次刷新即更新） // v50 2026-10-30: 夜间雨不再完全忽略——天头天气右侧补「🌙夜间<夜天气>」标注（如 🌙夜间小雨，与夜间横幅同 wxWetText 口径）；白天主图标/横幅/自动室内仍只看 day_weather // v49 2026-10-30: 雨天横幅文案带时段与量级——「白天小雨」「夜间小雨」（取 cast.day/night_weather 原文，EN 语境为读侧翻译文本） // v48 2026-10-30: 雨天双窗——夜间雨只影响夜间露天活动（游船观景/夜游等 evening 点自动换到晴夜+夜间横幅），白天雨不再动夜间点 // v47 2026-10-30: 英文版 clarify 追问卡死修复（偏好轮关键词加英文匹配 /prefer|sightsee/i + 提交文本本地化 + 提示不再限首轮） // v46 2026-10-30: 行程卡站点删除按钮加「🗑 删除」字样（card.del zh/en 词条） // v45 2026-10-30: 雨天判定改白天窗——夜间雨不影响白天行程（横幅/自动室内/图标只看 day_weather，用户拍板「避免露天活动与下雨时间段一致」） // v44 2026-10-30: 雨天收口——天头天气图标与雨天横幅同口径（夜间雨白天晴显 🌦️，修「横幅有雨图标晴」）+ 规划自动雨天排室内（整段有雨室内优先/部分日有雨自动对调，不问用户）+ 横幅去「回复重排」改备伞提示 // v43 2026-10-30: 桌面排版修复（#scrim 基础 display:none，v42 遮罩占掉 grid 第一格致侧栏/主区错位） + 布局按设备两套（断点叠加 pointer:coarse）+ 打开页面=行程页最近行程（去 localStorage 会话恢复） + 保存行程右边兜底重新规划 //  // v42 2026-10-30: 移动端（≤760px）左栏改抽屉菜单：左上角 ☰ 开关 + 遮罩，桌面端不变 // v41 2026-10-27: 行程卡片删除「✅ 到了」打卡按钮（fb-btn data-kind=visit），仅留 👍/👎/✍️ 点评；清理 visit 分支与 card.visited/plan.fb.checked* 文案
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

  // 2026-11-14（用户拍板「行程中心显示数据库信息，不吃缓存」）：心愿单
  // 看板永远直连网络——networkFirst 的 3s 超时回缓存会让删掉/去重后的
  // 旧看板闪回；本路径不写缓存、不回缓存。
  if (url.pathname.includes('/api/v1/trip-items')) {
    e.respondWith(fetch(req));
    return;
  }

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
