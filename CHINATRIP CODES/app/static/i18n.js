/* 双语 P1（DESIGN language_dual_system §6）：H5 i18n 骨架。
 * 仅 UI 文案走字典；数据文案走 I18N.pick(_en ?? 中文) 服务端并出回退。
 * 骨架范围：nav/主按钮 + 卡片名称与地址回退；全量文案迁移 P2/P3。
 */
(function () {
  "use strict";
  var DICT = {
    "zh-CN": {
      "nav.plan": "📋 规划", "nav.t9n": "🔤 翻译", "nav.nav": "🧭 导航",
      "nav.itin": "🗓 行程", "nav.trips": "🗂 行程中心", "nav.book": "🎫 预订",
      "nav.me": "👤 个人主页",
      "plan.start": "🚀 开始规划", "plan.send": "发送",
      "auth.login": "登录", "auth.cancel": "取消", "auth.sendCode": "发送验证码",
      "locale.toggle": "🌐 EN",
      "card.pinned": "📌 已钉住", "card.pin": "📌 钉住",
      "card.minutes": " 分钟", "card.to_next": "↓ 距下一站 ",
      "card.walk": " · 步行约 ", "card.walk_min": " 分钟",
      "card.leg_amap": "（高德实测）", "card.leg_est": "（直线估算）",
      "card.grab": "抢票直达 →", "card.hours_unknown": "🕐 营业时间待确认（以现场为准）",
      "card.km": " km",
      "pay.title": "💳 支付 / 代订收款", "pay.mine": "🔄 我的付款",
      "pay.note": "Visa/Mastercard/Amex/JCB · 支付宝 · 微信支付",
      "pay.go": "💳 去支付 / 存卡",
      "pay.kind.pay_now": "立即支付报价", "pay.kind.save_method": "保存银行卡（代订扣款）",
      "nav.call": "📞 咨询",
      "call.title": "通话咨询", "call.unit.min": " 分钟",
      "call.slogan": "付费与真人坐席实时通话；$1=5 分钟，余额可累积，到点自动结束",
      "call.mode.direct": "立即拨打坐席", "call.mode.callback": "等坐席回拨",
      "call.start": "实时通话", "call.end": "挂断 / 结束", "call.close": "关闭",
      "call.dial": "立即拨打坐席", "call.hotline": "坐席热线", "call.no_hotline": "坐席未配置热线，请用「等坐席回拨」",
      "call.no_hotline_fallback": "坐席热线未配置，已切换为「等坐席回拨」",
      "call.need_topup": "余额不足，请先买分钟", "call.pick_duration": "先选通话时长",
      "call.buy_ok": "购买成功", "call.pay_redirect": "已打开收银台，支付完成后余额自动到账",
      "call.refund.title": "退款规则（下单前必读）",
      "call.records.title": "通话记录", "call.records.empty": "还没有通话记录",
      "call.start.at": "开始时刻", "call.end.at": "结束时刻", "call.elapsed": "已用时",
      "call.remaining": "剩余", "call.actual": "本次实际时长", "call.autoend": "到点自动结束（服务端计时）",
      "call.refunded": "已退回",
      "call.st.waiting": "🟡 等待接听…", "call.st.active": "🟢 通话中",
      "call.st.ended": "⚫ 通话已结束", "call.st.expired": "⚪ 未接通已退款", "call.st.failed": "🔴 会话异常",
      "call.r.exhausted": "到点自动结束", "call.r.user": "旅客挂断", "call.r.agent": "坐席挂断",
      "call.r.timeout": "未接通全退", "call.r.error": "异常"
    },
    "en": {
      "nav.plan": "📋 Plan", "nav.t9n": "🔤 Translate", "nav.nav": "🧭 Navigate",
      "nav.itin": "🗓 Itinerary", "nav.trips": "🗂 My Trips", "nav.book": "🎫 Book",
      "nav.me": "👤 Profile",
      "plan.start": "🚀 Start Planning", "plan.send": "Send",
      "auth.login": "Log in", "auth.cancel": "Cancel", "auth.sendCode": "Send code",
      "locale.toggle": "🌐 中",
      "card.pinned": "📌 Pinned", "card.pin": "📌 Pin",
      "card.minutes": " min", "card.to_next": "↓ ",
      "card.walk": " · ~", "card.walk_min": " min walk",
      "card.leg_amap": " (measured)", "card.leg_est": " (straight-line)",
      "card.grab": "Get tickets →", "card.hours_unknown": "🕐 Hours TBC (check on site)",
      "card.km": " km to next",
      "pay.title": "💳 Pay / Concierge", "pay.mine": "🔄 My payments",
      "pay.note": "Visa/Mastercard/Amex/JCB · Alipay · WeChat Pay",
      "pay.go": "💳 Pay / Save card",
      "pay.kind.pay_now": "Pay quoted amount now", "pay.kind.save_method": "Save card (concierge charge)",
      "nav.call": "📞 Call",
      "call.title": "Live Call Service", "call.unit.min": " min",
      "call.slogan": "Live calls with a human agent; $1 = 5 min, balance rolls over, auto-ends on time",
      "call.mode.direct": "Call agent now", "call.mode.callback": "Wait for callback",
      "call.start": "Real-time Call", "call.end": "Hang up / End", "call.close": "Close",
      "call.dial": "Call agent now", "call.hotline": "Hotline", "call.no_hotline": "No hotline yet — use callback",
      "call.no_hotline_fallback": "No hotline configured — switched to callback",
      "call.need_topup": "Not enough minutes — buy a package first", "call.pick_duration": "Pick a duration first",
      "call.buy_ok": "Purchased", "call.pay_redirect": "Checkout opened — balance lands automatically after payment",
      "call.refund.title": "Refund policy (read before purchase)",
      "call.records.title": "Call records", "call.records.empty": "No calls yet",
      "call.start.at": "Started", "call.end.at": "Ended", "call.elapsed": "Elapsed",
      "call.remaining": "Remaining", "call.actual": "Actual duration", "call.autoend": "Auto-ends on time (server clock)",
      "call.refunded": "Refunded",
      "call.st.waiting": "🟡 Waiting…", "call.st.active": "🟢 In call",
      "call.st.ended": "⚫ Call ended", "call.st.expired": "⚪ Unanswered — refunded", "call.st.failed": "🔴 Session error",
      "call.r.exhausted": "Time used up", "call.r.user": "Hung up by you", "call.r.agent": "Hung up by agent",
      "call.r.timeout": "Unanswered — fully refunded", "call.r.error": "Error"
    }
  };
  /* 城市英文名（双语 P1.6）：主流旅游城市精选；未收录回退中文原文。
   * 键为库内 city 原值（含“喀什地区喀什”类拼接，helper 内规整）。 */
  var CITY_EN = {
    "北京": "Beijing", "上海": "Shanghai", "天津": "Tianjin", "重庆": "Chongqing",
    "广州": "Guangzhou", "深圳": "Shenzhen", "杭州": "Hangzhou", "苏州": "Suzhou",
    "南京": "Nanjing", "成都": "Chengdu", "西安": "Xi'an", "武汉": "Wuhan",
    "厦门": "Xiamen", "青岛": "Qingdao", "长沙": "Changsha", "昆明": "Kunming",
    "桂林": "Guilin", "丽江": "Lijiang", "大理白族自治州大理": "Dali",
    "三亚": "Sanya", "海口": "Haikou", "哈尔滨": "Harbin", "沈阳": "Shenyang",
    "大连": "Dalian", "济南": "Jinan", "泰安": "Tai'an", "青岛": "Qingdao",
    "郑州": "Zhengzhou", "洛阳": "Luoyang", "开封": "Kaifeng", "登封": "Dengfeng",
    "无锡": "Wuxi", "南京": "Nanjing", "扬州": "Yangzhou", "常州": "Changzhou",
    "宁波": "Ningbo", "温州": "Wenzhou", "绍兴": "Shaoxing", "嘉兴": "Jiaxing",
    "黄山": "Huangshan", "合肥": "Hefei", "福州": "Fuzhou", "泉州": "Quanzhou",
    "武夷山": "Wuyishan", "南昌": "Nanchang", "景德镇": "Jingdezhen",
    "张家界": "Zhangjiajie", "岳阳": "Yueyang", "韶山": "Shaoshan",
    "重庆": "Chongqing", "贵阳": "Guiyang", "遵义": "Zunyi", "安顺": "Anshun",
    "拉萨": "Lhasa", "林芝": "Nyingchi", "敦煌": "Dunhuang", "嘉峪关": "Jiayuguan",
    "兰州": "Lanzhou", "西宁": "Xining", "银川": "Yinchuan", "乌鲁木齐": "Urumqi",
    "吐鲁番": "Turpan", "喀什地区喀什": "Kashgar", "伊犁": "Yili",
    "呼和浩特": "Hohhot", "鄂尔多斯": "Ordos", "太原": "Taiyuan", "大同": "Datong",
    "平遥": "Pingyao", "石家庄": "Shijiazhuang", "秦皇岛": "Qinhuangdao",
    "承德": "Chengde", "保定": "Baoding", "长春": "Changchun", "吉林市": "Jilin",
    "延安": "Yan'an", "汉中": "Hanzhong", "宝鸡": "Baoji", "华山": "Huashan",
    "峨眉山": "Emeishan", "乐山": "Leshan", "都江堰": "Dujiangyan",
    "九江": "Jiujiang", "庐山": "Lushan", "宜昌": "Yichang", "恩施土家族苗族自治州恩施": "Enshi",
    "南阳": "Nanyang", "襄阳": "Xiangyang", "佛山": "Foshan", "中山": "Zhongshan",
    "珠海": "Zhuhai", "汕头": "Shantou", "潮州": "Chaozhou", "梅州": "Meizhou",
    "南宁": "Nanning", "柳州": "Liuzhou", "北海": "Beihai", "唐山": "Tangshan",
    "曲阜": "Qufu", "潍坊": "Weifang", "烟台": "Yantai", "威海": "Weihai",
    "蓬莱": "Penglai", "徐州": "Xuzhou", "镇江": "Zhenjiang", "南通": "Nantong",
    "湖州": "Huzhou", "舟山": "Zhoushan", "义乌": "Yiwu", "金华": "Jinhua",
    "腾冲": "Tengchong", "西双版纳": "Xishuangbanna", "普洱": "Pu'er",
    "满洲里": "Manzhouli", "呼伦贝尔": "Hulunbuir", "赤峰": "Chifeng"
  };

  var KEY = "ct_locale";

  function locale() {
    try { return localStorage.getItem(KEY) === "en" ? "en" : "zh-CN"; }
    catch (e) { return "zh-CN"; }
  }
  function setLocale(l) {
    try { localStorage.setItem(KEY, l === "en" ? "en" : "zh-CN"); } catch (e) {}
    apply();
    /* 通知 JS 动态渲染的部分（如通话页 callRender）按新语言重绘；监听方见 index.html */
    try { window.dispatchEvent(new Event("i18n:change")); } catch (e) {}
  }
  function t(key) {
    var d = DICT[locale()] || DICT["zh-CN"];
    return d[key] != null ? d[key] : (DICT["zh-CN"][key] != null ? DICT["zh-CN"][key] : key);
  }
  /* 城市 EN：规整“XX自治州/地区YY”类拼接 → 取后段；未收录回退原文 */
  function city(zh) {
    if (!zh || locale() !== "en") return zh;
    var k = String(zh).replace(/^(.*?)(自治州|地区)/, "");
    return CITY_EN[k] || CITY_EN[zh] || zh;
  }
  /* 数据文案回退：en 优先取 enKey 且非空，否则中文——翻译未跑完全功能可用 */
  function pick(obj, zhKey, enKey) {
    if (!obj) return obj;
    return (locale() === "en" && obj[enKey]) ? obj[enKey] : obj[zhKey];
  }
  function apply() {
    document.documentElement.lang = locale() === "en" ? "en" : "zh-CN";
    var nodes = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = t(nodes[i].getAttribute("data-i18n"));
    }
    var btn = document.getElementById("localeToggle");
    if (btn) btn.textContent = t("locale.toggle");
  }
  function toggle() { setLocale(locale() === "en" ? "zh-CN" : "en"); }

  window.I18N = { t: t, pick: pick, city: city, locale: locale, setLocale: setLocale, toggle: toggle, apply: apply };
  document.addEventListener("DOMContentLoaded", apply);
})();
