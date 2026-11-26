/* 酒店 → 预订页守门（node ops/check_hotel_book.js，无依赖；被 require 时不执行，见文件尾）。
 *
 * 2026-11-26 用户令「HOTEL CLICK SHOULD TURN PAGE TO RESERVATION PAGE WHICH HAS
 * HOTEL WORD PLUS, TRIP, BOOKING, AGODA THREE BUTTONS」：规划页酒店卡（入住/夜/晨
 * 三类）点酒店名 → 「🎫 预订」页 🏨 分区，顶部钉住所选酒店名 + 三家平台按钮。
 *
 * 事故史（R44d）：三家按钮只吃「住宿城市」，从酒店卡点进来也搜不到那家店——用户
 * 点的是这家酒店，落地页给的是一城酒店列表。本守门两边都钉住：
 *   A. 行为门：把 bkHotelPickText / bkHotelOutbound 抽出来在 stub 上跑，逐平台钉
 *      「选中酒店 → 搜索词=酒店名+城市」「没选中 → 回落城市」「城市/酒店都没有 →
 *      不跳转只提示」「英文态用 name_en + 英文城市名」。
 *   B. 调用点门：面板三按钮/清除按钮挂着、规划页酒店名是 hotel-link、卡片点击委托
 *      里 hotelGotoBook 真的被调用（函数写好了没接线 = 同一 bug 复现）。
 * 任一项失败 exit 1。 */
"use strict";
const fs = require("fs");
const path = require("path");

const HTML = path.join(__dirname, "..", "app", "static", "index.html");
let failed = 0;
function fail(msg) { console.error("FAIL " + msg); failed++; }
function ok(msg) { console.log("ok   " + msg); }

const src = fs.readFileSync(HTML, "utf8");

function loadFn(name) {
  const re = new RegExp("function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}");
  const m = src.match(re);
  if (!m) throw new Error("index.html 里没有找到 " + name + "（提取规则失效？）");
  return m[0];
}

const HOSTS = { trip: "www.trip.com", booking: "www.booking.com", agoda: "www.agoda.com" };
const EN_CITY = { "北京": "Beijing", "上海": "Shanghai" };

/* ---------- A. 行为门：真函数体 + stub document/window ---------- */
function run(label, opts, expect) {
  const locale = opts.locale || "zh";
  const city = opts.city || "";
  const calls = { opened: [], toasts: [] };
  const document = {
    getElementById: (id) => ({
      get value() { return id === "bkHotelCity" ? city : ""; },
      set value(v) { /* 出口函数不回写输入框 */ },
    }),
  };
  const I18N = {
    locale: () => locale,
    city: (x) => (locale === "zh" ? x : (EN_CITY[x] || x)),
    tf: (k, zh) => (locale === "zh" ? zh : k), // 提示文案不参与断言
  };
  const window = { open: (u) => calls.opened.push(u) };
  const toast = (m) => calls.toasts.push(m);
  const code = loadFn("bkHotelPickText") + "\n" + loadFn("bkHotelOutbound") + "\nreturn bkHotelOutbound;";
  const outbound = new Function("document", "BOOK", "I18N", "toast", "window", code)(
    document, { hotelPick: opts.pick || null }, I18N, toast, window
  );

  const problems = [];
  const sites = expect.sites || [];
  if (!sites.length) outbound("trip"); // 只测「该不跳」
  sites.forEach((site) => {
    calls.opened.length = 0;
    outbound(site);
    const url = calls.opened[0] || "";
    if (!url) { problems.push(site + " 没跳转"); return; }
    if (HOSTS[site] && url.indexOf(HOSTS[site]) === -1) problems.push(site + " 跳错站：" + url);
    if (expect.needle && url.indexOf(expect.needle) === -1) {
      problems.push(site + " 搜索词丢失（期望含 " + expect.needle + "，实际 " + url + "）");
    }
  });
  if (expect.noOpen && calls.opened.length) problems.push("不该跳转却跳了：" + calls.opened[0]);
  if (expect.toast && calls.toasts.length !== 1) problems.push("该提示却提示 " + calls.toasts.length + " 次");
  if (!expect.toast && calls.toasts.length) problems.push("不该提示却提示：" + calls.toasts[0]);
  if (problems.length) fail(label + " → " + problems.join("；"));
  else ok(label);
}

const ALL = ["trip", "booking", "agoda"];

run("选中酒店（中文态）：三家按「酒店名 城市」搜",
  { pick: { name: "北京饭店", name_en: "Beijing Hotel", city: "北京" }, city: "北京" },
  { sites: ALL, needle: encodeURIComponent("北京饭店 北京") });
run("选中酒店（英文态）：用 name_en + 英文城市名",
  { locale: "en", pick: { name: "北京饭店", name_en: "Beijing Hotel", city: "北京" }, city: "北京" },
  { sites: ALL, needle: encodeURIComponent("Beijing Hotel Beijing") });
run("没选中酒店：回落纯城市搜",
  { city: "上海" },
  { sites: ALL, needle: encodeURIComponent("上海") });
run("酒店名在、城市框空：仍按酒店名 + 酒店城市搜",
  { pick: { name: "和平饭店", city: "上海" }, city: "" },
  { sites: ALL, needle: encodeURIComponent("和平饭店 上海") });
run("既没酒店也没城市：只提示不跳转",
  {},
  { noOpen: true, toast: true });
run("城市框有值 + 酒店名空串：按城市搜（不拼空名）",
  { pick: { name: "", city: "", name_en: "" }, city: "上海" },
  { sites: ALL, needle: encodeURIComponent("上海") });

/* ---------- B. 调用点门 ---------- */
const gates = [
  ["预订页选中酒店面板在位（酒店名 + 三家按钮同卡）", /id="bkHotelSel"[\s\S]*?id="bkHotelSelName"[\s\S]*?id="bkHotelSelTrip"[\s\S]*?id="bkHotelSelBooking"[\s\S]*?id="bkHotelSelAgoda"/],
  ["面板 Trip 按钮", /getElementById\("bkHotelSelTrip"\)\.addEventListener\("click", \(\) => bkHotelOutbound\("trip"\)\)/],
  ["面板 Booking 按钮", /getElementById\("bkHotelSelBooking"\)\.addEventListener\("click", \(\) => bkHotelOutbound\("booking"\)\)/],
  ["面板 Agoda 按钮", /getElementById\("bkHotelSelAgoda"\)\.addEventListener\("click", \(\) => bkHotelOutbound\("agoda"\)\)/],
  ["面板清除按钮清选中态", /getElementById\("bkHotelSelClear"\)\.addEventListener\("click", \(\) => \{[\s\S]*?BOOK\.hotelPick = null/],
  ["规划页酒店名是 hotel-link", /it\.category === "hotel" \? '<a class="site-link hotel-link" data-action="hotelbook"/],
  ["酒店卡卡底指路行也是 hotel-link", /if \(it\.category === "hotel"\) blk\.appendChild\(el\('<div class="muted" style="margin:0 2px 6px ' \+ ind \+ ';font-size:11px"><a class="site-link hotel-link" data-action="hotelbook"/],
  ["卡片点击委托真的调用 hotelGotoBook", /closest\('a\.hotel-link'\)[\s\S]{0,400}?hotelGotoBook\(/],
  ["hotelGotoBook 切预订页并刷面板", /function hotelGotoBook\(name, city, addr, nameEn\) \{[\s\S]*?switchTab\("book"\);[\s\S]*?bkShow\("hotel"\);[\s\S]*?bkHotelSelPaint\(\);/],
  ["bkShow(hotel) 刷新选中面板", /if \(kind === "hotel"\) \{\s*\n\s*bkRenderPlanDays\(\);\s*\n\s*bkHotelSelPaint\(\);/],
  ["三家出口优先读选中酒店", /function bkHotelOutbound\(site\) \{\s*\n\s*const pickQ = bkHotelPickText\(\);/],
];
gates.forEach(([label, re]) => {
  if (re.test(src)) ok(label + "：在位");
  else fail(label + "：丢失（点酒店到不了预订页 / 三家按钮搜不到这家酒店）");
});

/* 面板必须默认隐藏（没选酒店时不能挡表单） */
if (/id="bkHotelSel"[^>]*style="display:none/.test(src)) ok("选中面板默认隐藏：在位");
else fail("选中面板默认隐藏：缺失（没选酒店就顶在表单上面）");

if (failed) {
  console.error("\n酒店→预订页守门失败 " + failed + " 项");
  process.exit(1);
}
console.log("\n酒店→预订页守门全部通过");
