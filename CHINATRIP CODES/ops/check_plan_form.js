/* 规划起始页路线表单守门（node ops/check_plan_form.js，无依赖；被 require 时不执行，见文件尾）。
 *
 * 2026-11-13 事故（用户：起始北京 / 旅游上海 3 天 / 结束上海，「结果上海只排了一天」）：
 * 起始页把「旅游城市」填在中间城市行、结束城市也选同一个城市时，旧版
 * planRouteForm() 只按「与首尾同城则跳过」整行丢弃——连用户填的 3 天一起
 * 丢，结束城市默认 1 天顶上，合计塌成 1 天，出参 days=1、city_days={上海:1}。
 *
 * 本守门把 index.html 里的 planRouteForm 抽出来在 stub document 上跑，逐案钉住
 * 「同城并天不丢天」口径（结束城市同城取较大者、中间城市互相同城同理、
 * 起始城市天数无意义）。任一项失败 exit 1。 */
"use strict";
const fs = require("fs");
const path = require("path");

const HTML = path.join(__dirname, "..", "app", "static", "index.html");
let failed = 0;
function fail(msg) { console.error("FAIL " + msg); failed++; }
function ok(msg) { console.log("ok   " + msg); }

function loadForm() {
  const src = fs.readFileSync(HTML, "utf8");
  const m = src.match(/function planRouteForm\(\) \{[\s\S]*?\n\}/);
  if (!m) throw new Error("index.html 里没有找到 planRouteForm（提取规则失效？）");
  return m[0];
}

function loadFn(name) {
  const src = fs.readFileSync(HTML, "utf8");
  const re = new RegExp("function " + name + "\\([^)]*\\) \\{[\\s\\S]*?\\n\\}");
  const m = src.match(re);
  if (!m) throw new Error("index.html 里没有找到 " + name + "（提取规则失效？）");
  return m[0];
}

function build(values) {
  const nodes = {};
  const document = {
    getElementById(id) {
      if (!nodes[id]) {
        nodes[id] = {
          get value() { return values[id] === undefined ? "" : String(values[id]); },
          set value(v) { values[id] = String(v); },
        };
      }
      return nodes[id];
    },
  };
  const form = new Function("document", loadForm() + "\nreturn planRouteForm;")(document);
  return () => form();
}

function check(label, values, expect) {
  const v = Object.assign({}, values);
  const out = build(v)();
  const problems = [];
  if (JSON.stringify(out.cities) !== JSON.stringify(expect.cities)) {
    problems.push("cities=" + JSON.stringify(out.cities) + " 期望 " + JSON.stringify(expect.cities));
  }
  if (JSON.stringify(out.cityDays) !== JSON.stringify(expect.cityDays)) {
    problems.push("cityDays=" + JSON.stringify(out.cityDays) + " 期望 " + JSON.stringify(expect.cityDays));
  }
  if (out.total !== expect.total) problems.push("total=" + out.total + " 期望 " + expect.total);
  if (expect.endDays !== undefined && v.planEndDays !== String(expect.endDays)) {
    problems.push("结束城市天数框=" + v.planEndDays + " 期望回写 " + expect.endDays);
  }
  if (problems.length) fail(label + " → " + problems.join("；"));
  else ok(label);
}

/* 1. 用户案：起始北京、中间城市1=上海 3 天、结束城市=上海（天数框仍默认 1）
 *    —— 3 天必须落到上海，合计 3（事故前 total=1、cityDays={上海:1}）。 */
check(
  "用户案 北京→(上海 3天)→上海",
  { planStartCity: "北京", planEndCity: "上海", planVia1: "上海", planVia1Days: "3", planVia2: "", planVia2Days: "1", planEndDays: "1" },
  { cities: ["北京", "上海"], cityDays: { 上海: 3 }, total: 3, endDays: 3 }
);

/* 2. 中间城市2 与结束城市同城（中间1 异地）：天数并入结束城市，路线保留中间1。 */
check(
  "中间城市2=结束城市 北京→(上海 2天)→(杭州 3天)→杭州",
  { planStartCity: "北京", planEndCity: "杭州", planVia1: "上海", planVia1Days: "2", planVia2: "杭州", planVia2Days: "3", planEndDays: "1" },
  { cities: ["北京", "上海", "杭州"], cityDays: { 上海: 2, 杭州: 3 }, total: 5, endDays: 3 }
);

/* 3. 正常路径不回退：不填中间城市，结束城市天数=3。 */
check(
  "正常 北京→上海 3天",
  { planStartCity: "北京", planEndCity: "上海", planVia1: "", planVia1Days: "1", planVia2: "", planVia2Days: "1", planEndDays: "3" },
  { cities: ["北京", "上海"], cityDays: { 上海: 3 }, total: 3 }
);

/* 4. 结束城市天数比同城中间行更长：取较大者，不被较短行拉低。 */
check(
  "结束城市天数更大 上海2天 vs 结束5天",
  { planStartCity: "北京", planEndCity: "上海", planVia1: "上海", planVia1Days: "2", planVia2: "", planVia2Days: "1", planEndDays: "5" },
  { cities: ["北京", "上海"], cityDays: { 上海: 5 }, total: 5 }
);

/* 5. 中间城市=起始城市：出发城不排活动，天数无效（维持旧口径）。 */
check(
  "中间城市=起始城市 北京→(北京 3天)→上海",
  { planStartCity: "北京", planEndCity: "上海", planVia1: "北京", planVia1Days: "3", planVia2: "", planVia2Days: "1", planEndDays: "1" },
  { cities: ["北京", "上海"], cityDays: { 上海: 1 }, total: 1 }
);

/* 6. 两个中间城市同城：并天取较大者，不重复占路线。 */
check(
  "中间城市互相同城 北京→(上海 2天)→(上海 4天)→杭州",
  { planStartCity: "北京", planEndCity: "杭州", planVia1: "上海", planVia1Days: "2", planVia2: "上海", planVia2Days: "4", planEndDays: "1" },
  { cities: ["北京", "上海", "杭州"], cityDays: { 上海: 4, 杭州: 1 }, total: 5 }
);

/* 7. 开始日期来源（2026-11-23 用户实报「表单填了日期仍弹行前卡」）：
 *    行前卡日期优先；表单开局带表单日期；纯文字开局不注入表单默认值。 */
function checkStartDate(label, intakeDate, formDate, useFormParams, expect) {
  const fn = new Function(loadFn("planResolveStartDate") + "\nreturn planResolveStartDate;")();
  const got = fn(intakeDate, formDate, useFormParams);
  if (got !== expect) fail(label + " → " + JSON.stringify(got) + " 期望 " + JSON.stringify(expect));
  else ok(label);
}
checkStartDate("开始日期：行前卡优先", "2026-12-01", "2026-11-26", true, "2026-12-01");
checkStartDate("开始日期：表单开局带表单日期", "", "2026-11-26", true, "2026-11-26");
checkStartDate("开始日期：纯文字开局不注默认值", "", "2026-11-26", false, "");

/* 8. 行前卡值回写规划快照（2026-11-23 用户实报「行前卡 → 文字/窗口差异确认
 *    → 选完又弹行前卡」）：确认卡重发只读 planLastStart，卡值没落快照 →
 *    重发缺必填出发日期 → 后端再弹一张空卡，用户永远出不来行程。 */
function checkIntakeSnapshot(label, snapshot, vals, expect) {
  const fn = new Function("planLastStart", loadFn("planMergeIntake") + "\nreturn planMergeIntake;")(snapshot);
  fn(vals);
  const got = snapshot.intake || {};
  const problems = [];
  Object.keys(expect.intake || {}).forEach(k => {
    if (got[k] !== expect.intake[k]) problems.push("intake." + k + "=" + JSON.stringify(got[k]) + " 期望 " + JSON.stringify(expect.intake[k]));
  });
  if (expect.absent) expect.absent.forEach(k => {
    if (got[k] !== undefined) problems.push("intake." + k + " 不该被空值覆盖");
  });
  if (expect.startDate !== undefined && snapshot.startDate !== expect.startDate) {
    problems.push("startDate=" + JSON.stringify(snapshot.startDate) + " 期望 " + JSON.stringify(expect.startDate));
  }
  if (problems.length) fail(label + " → " + problems.join("; "));
  else ok(label);
}
checkIntakeSnapshot(
  "行前卡值：开局 {skipped} 快照写入卡值",
  { intake: { skipped: true }, startDate: "" },
  { start_date: "2026-11-20", arrival_date: "2026-11-20", arrival_no: "MU5101", departure_date: "2026-11-21", arrival_time: "" },
  { intake: { start_date: "2026-11-20", arrival_date: "2026-11-20", arrival_no: "MU5101", departure_date: "2026-11-21" }, absent: ["arrival_time"], startDate: "2026-11-20" }
);
checkIntakeSnapshot(
  "行前卡值：服务端回显补齐不覆盖已有卡值",
  { intake: { start_date: "2026-11-20", arrival_no: "MU5101" }, startDate: "2026-11-20" },
  { start_date: "2026-11-20", arrival_date: "2026-11-20", departure_date: "2026-11-21" },
  { intake: { arrival_no: "MU5101", arrival_date: "2026-11-20", departure_date: "2026-11-21" }, startDate: "2026-11-20" }
);
checkIntakeSnapshot(
  "行前卡值：空回显不动快照",
  { intake: { start_date: "2026-11-20" }, startDate: "2026-11-20" },
  {},
  { intake: { start_date: "2026-11-20" }, startDate: "2026-11-20" }
);

/* 8b. 调用点守门：快照写入必须挂在两条真实路径上（写好了函数却没调用 =
 *     同一 bug 复现）。删掉任一调用本守门即红。 */
const htmlSrc = fs.readFileSync(HTML, "utf8");
[
  ["state=intake 提交后落快照", /if \(ov\.intakeValues\) planMergeIntake\(ov\.intakeValues\);/],
  ["confirm_route 回显并入快照", /planMergeIntake\(body\.intake\);/],
].forEach(([label, re]) => {
  if (re.test(htmlSrc)) ok(label + "：调用点在");
  else fail(label + "：调用点丢失（行前卡值会再次丢，确认卡选边后又弹卡）");
});

if (failed) {
  console.error("\n规划表单守门失败 " + failed + " 项");
  process.exit(1);
}
console.log("\n规划表单守门全部通过");
