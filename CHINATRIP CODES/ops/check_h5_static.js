/* H5 静态资源守门（node ops/check_h5_static.js，无依赖；被 require 时不执行，见文件尾）。
 * 2026-10-25 语言开关白屏事故的两类静默故障，改前改后都查不出——必须机器把关：
 *   1) index.html 内联 <script> 一处引号错误 → 整个主脚本不执行，页面半死（i18n 来自独立文件仍在跑，更具迷惑性）；
 *   2) data-i18n 用到的词条缺词典 → 界面直接显示 "call.slogan" 之类的原始 key。
 * 2026-10-25 EN 全量迁移期新增 C 门：JS 动态文案逐条迁 I18N.tf(key,"中文原文")，
 * 迁漏一条英文模式就漏出中文——人工肉眼不可穷尽，同样必须机器把关。
 * 检查项：
 *   A. 语法门：index.html / agent.html 全部内联脚本块 + i18n.js + sw.js 逐块 new Function() 解析；
 *   B. 词条门（按 key 类别分档）：
 *      - data-i18n：en 必查（zh 由 data-i18n-orig 原文暂存兜底，zh 词典可选）；
 *      - I18N.t("…") 字面量：en 与 zh-CN 都必查（t() 无兜底参，缺词裸显 key）；
 *      - 动态文案 I18N.tf("key"…)/tf("key"…)/callT("key"…（单双引号、允许空白）：
 *        只要求 en 词典收录（zh 由调用点内联原文兜底，词典可选——tf 的设计）。
 *   C. 残留门（EN 模式中文残留扫描，仅 index.html 的内联 <script> 块；
 *      agent.html 是内部中文运营台，无多语言诉求，豁免）：
 *      状态机分词（字符串/模板串/注释/正则/转义全支持）后，任何含 CJK 的字符串字面量
 *      ——含模板串文本段——除非 (a) 恰为 tf/callT 第二参（zh 兜底原文）或 (b) 在
 *      数据比对字面量白名单（香港/澳门），否则 FAIL 并列出全部位置。
 *      预剥离纯数据声明 CITYS/PLAN_CITIES/ORI（城市表/计划城市表/方位表：仅作数据比对
 *      或经 I18N.city() 渲染，与文案无关）；三者任一在文件里找不到即 FAIL（剥离规则失效告警）。
 * 任一项失败 exit 1。 */
"use strict";
const fs = require("fs");
const path = require("path");

const STATIC_DIR = path.join(__dirname, "..", "app", "static");
let failed = 0;
function fail(msg) { console.error("FAIL " + msg); failed++; }
function ok(msg) { console.log("ok   " + msg); }

/* ---------- A. 语法门 ---------- */
function gateA() {
  const files = ["index.html", "agent.html", "i18n.js", "sw.js"];
  for (const f of files) {
    const p = path.join(STATIC_DIR, f);
    if (!fs.existsSync(p)) { fail(f + " 不存在"); continue; }
    const src = fs.readFileSync(p, "utf8");
    if (f.endsWith(".html")) {
      const blocks = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)];
      if (!blocks.length) fail(f + " 没有找到内联 <script> 块（提取规则失效？）");
      blocks.forEach((m, i) => {
        try { new Function(m[1]); ok(f + " 内联脚本块#" + i); }
        catch (e) { fail(f + " 内联脚本块#" + i + " 语法错误: " + e.message); }
      });
    } else {
      try { new Function(src); ok(f); }
      catch (e) { fail(f + " 语法错误: " + e.message); }
    }
  }
}

/* ---------- B. 词条门 ---------- */
// 在 stub 环境里跑真 i18n.js（而非解析文本），用 t() 的「缺词回退为 key」特性判定词条存在
function loadI18n(locale) {
  const store = { ct_locale: locale };
  const sandbox = {
    window: {},
    localStorage: {
      getItem: k => (k in store ? store[k] : null),
      setItem: (k, v) => { store[k] = String(v); },
    },
    document: {
      documentElement: {},
      addEventListener() {},
      querySelectorAll() { return []; },
      getElementById() { return null; },
    },
  };
  sandbox.globalThis = sandbox;
  const vm = require("vm");
  const ctx = vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(STATIC_DIR, "i18n.js"), "utf8"), ctx);
  return sandbox.window.I18N;
}

function gateB() {
  /* 三类 key，词典要求不同：
   * - data-i18n：en 必查。zh 走 data-i18n-orig 原文暂存兜底（apply() 用 tf），zh 词典可选；
   * - I18N.t("…") 字面量：en/zh 都必查——t() 无兜底参，zh 缺词会裸显 key；
   * - tf/callT 动态文案：只查 en（zh 由调用点内联原文兜底，zh 词典可选）。 */
  const keysDataI18n = new Set();
  const keysT = new Set();
  const usedKeysEn = new Set();
  for (const f of ["index.html", "agent.html"]) {
    const p = path.join(STATIC_DIR, f);
    if (!fs.existsSync(p)) continue;
    const src = fs.readFileSync(p, "utf8");
    for (const m of src.matchAll(/data-i18n="([^"]+)"/g)) keysDataI18n.add(m[1]);
    for (const m of src.matchAll(/I18N\.t\("([^"]+)"\)/g)) keysT.add(m[1]);
    // \btf\( 同时命中 I18N.tf( 与裸 tf(（"." 是词边界）；单双引号、键后空白均可。
    // 键后必须是 , 或 ) —— 排除 tf("前缀." + 变量) 这类拼接键（永远无法命中词典，纯误报）。
    for (const m of src.matchAll(/\btf\(\s*(["'])([^"'\n]+)\1\s*[),]/g)) usedKeysEn.add(m[2]);
    for (const m of src.matchAll(/\bcallT\(\s*(["'])([^"'\n]+)\1\s*[),]/g)) usedKeysEn.add(m[2]);
  }
  if (!keysDataI18n.size && !keysT.size && !usedKeysEn.size) fail("没有从 HTML/JS 提取到任何 i18n key（提取规则失效？）");

  let zhI18n = null, enI18n = null;
  try { zhI18n = loadI18n("zh-CN"); }
  catch (e) { fail("i18n.js 在 zh-CN 下无法加载: " + e.message); }
  try { enI18n = loadI18n("en"); }
  catch (e) { fail("i18n.js 在 en 下无法加载: " + e.message); }

  if (zhI18n && keysT.size) {
    const missing = [...keysT].filter(k => zhI18n.t(k) === k);
    if (missing.length) fail("词典[zh-CN] 缺 " + missing.length + " 个 I18N.t 词条（t() 无兜底）: " + missing.join(", "));
    else ok("词典[zh-CN] 覆盖全部 " + keysT.size + " 个 I18N.t key");
  }
  if (enI18n) {
    const allEn = new Set([...keysDataI18n, ...keysT, ...usedKeysEn]);
    const missing = [...allEn].filter(k => enI18n.t(k) === k);
    if (missing.length) fail("词典[en] 缺 " + missing.length + " 个词条（data-i18n/I18N.t/tf/callT 合并）: " + missing.join(", "));
    else ok("词典[en] 覆盖全部 " + allEn.size + " 个在用 key（data-i18n/I18N.t/tf/callT；zh 词典除 I18N.t 外可选）");
  }
}

/* ---------- C. 残留门公共件 ---------- */
const CJK_RE = /[　-〿㐀-䶿一-鿿豈-﫿＀-￯]/;
const ZH_ALLOW = new Set([
  "香港", "澳门", "全国统一价",          // 与外部数据比对的字面量（POI 库城市名/后端返回的 tag 值）
  "上海", "杭州", "北京",               // 下拉/NAV.city 的中文规范市名（API 契约值，渲染处经 I18N.city()）
  "我的位置", "故宫",                   // 位置数据值（渲染处 posName() 动态转标签）
  "都可以",                             // 城市下拉「不限」哨兵值（提交数据值）
  "偏好", "观光",                       // 后端 clarify 问题关键词嗅探（双语文档输入 P3 前保持中文比对）
  "偏好：", "无特别要求", "要安排：", "；不安排：", "无", "；", "、", // 组合给规划引擎的中文输入串/分隔符（反向数据非 UI；EN 输入链路 P3）
]);

/* JS 状态机分词器：normal/单引号/双引号/模板串/行注释/块注释/正则。
 * 产出 token: {type:"string"|"ident"|"punct"|"regex", text, line}；注释与正则内容丢弃。
 * - 正则 vs 除法：normal 态遇 "/"，仅当前一个有效字符（非空白/注释）属于
 *   ( , = : [ ! & | ? { } ; + - * % ~ ^ < > 或流起始 才按正则起 token，否则按除法。
 * - 模板串 "${" 进入嵌套代码态（互递归 + 花括号配深），闭合 "}" 后回到模板文本态（栈式支持嵌套）。
 * - 转义（\x \uXXXX \' \" \` \\ \<换行>）按两字符吞掉，内嵌引号不会提前终结 token。 */
function tokenizeJs(src) {
  const tokens = [];
  const REGEX_PREV = new Set(["(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";", "+", "-", "*", "%", "~", "^", "<", ">"]);
  const isWord = c => /[A-Za-z0-9_$]/.test(c) || c.charCodeAt(0) > 0x7f;
  let i = 0, line = 1, prevSig = ""; // 前一个有效字符（决定 "/" 的归属）

  function lexRegex() { // i 指向起始 "/"
    const startLine = line;
    let j = i + 1, inCls = false;
    while (j < src.length) {
      const ch = src[j];
      if (ch === "\\") { j += 2; continue; }
      if (ch === "\n") { line++; j++; continue; }
      if (ch === "[") inCls = true;
      else if (ch === "]") inCls = false;
      else if (ch === "/" && !inCls) { j++; break; }
      j++;
    }
    while (j < src.length && /[a-z]/i.test(src[j])) j++; // flags
    tokens.push({ type: "regex", text: "", line: startLine });
    i = j; prevSig = "/";
  }

  function lexString(q) { // i 指向起始引号
    const startLine = line;
    let j = i + 1, inner = "";
    while (j < src.length) {
      const ch = src[j];
      if (ch === "\\") { if (src[j + 1] === "\n") line++; inner += src.slice(j, j + 2); j += 2; continue; }
      if (ch === q) { j++; break; }
      if (ch === "\n") line++;
      inner += ch; j++;
    }
    tokens.push({ type: "string", text: inner, line: startLine });
    i = j; prevSig = q;
  }

  function lexTemplate() { // i 指向起始反引号；文本段逐段产 string token
    let j = i + 1, seg = "", segLine = line;
    for (;;) {
      if (j >= src.length) break;
      const ch = src[j];
      if (ch === "\\") { if (src[j + 1] === "\n") line++; seg += src.slice(j, j + 2); j += 2; continue; }
      if (ch === "`") { j++; break; }
      if (ch === "$" && src[j + 1] === "{") {
        if (seg) { tokens.push({ type: "string", text: seg, line: segLine }); seg = ""; }
        i = j + 2;
        lexCode(true); // 内嵌代码，直到配对的 "}"（prevSig/line 继续沿用）
        j = i;
        segLine = line;
        continue;
      }
      if (ch === "\n") line++;
      seg += ch; j++;
    }
    if (seg) tokens.push({ type: "string", text: seg, line: segLine });
    i = j; prevSig = "`";
  }

  function lexCode(inBrace) { // inBrace=true：花括号深度归零处的 "}" 消费并返回（供 ${…} 收口）
    let depth = 0;
    while (i < src.length) {
      const c = src[i];
      if (c === "\n") { line++; i++; continue; }
      if (c === " " || c === "\t" || c === "\r") { i++; continue; }
      if (c === "/" && src[i + 1] === "/") { while (i < src.length && src[i] !== "\n") i++; continue; }
      if (c === "/" && src[i + 1] === "*") {
        i += 2;
        while (i < src.length && !(src[i] === "*" && src[i + 1] === "/")) { if (src[i] === "\n") line++; i++; }
        i += 2;
        continue;
      }
      if (c === "/" && (prevSig === "" || REGEX_PREV.has(prevSig))) { lexRegex(); continue; }
      if (c === "'" || c === '"') { lexString(c); continue; }
      if (c === "`") { lexTemplate(); continue; }
      if (isWord(c)) {
        const startLine = line;
        let s = c; i++;
        while (i < src.length && isWord(src[i])) s += src[i++];
        tokens.push({ type: "ident", text: s, line: startLine });
        prevSig = s[s.length - 1];
        continue;
      }
      tokens.push({ type: "punct", text: c, line });
      i++; prevSig = c;
      if (c === "{") depth++;
      else if (c === "}") { if (inBrace && depth === 0) return; depth--; }
    }
  }

  lexCode(false);
  return tokens;
}

/* 在 token 流上判定违规：含 CJK 的 string token 记违规，除非——
 * (a) 它恰是 tf/callT 的第二参：序列 ident(tf|callT) "(" string "," → 置豁免旗，
 *     紧随其后的下一个 token 若为 string 即豁免（流式判定天然跨行）；
 *     若不是 string 则旗立即失效（严格限定「紧随其后」）。
 * (b) 整串恰为白名单（香港/澳门）。 */
function findZhViolations(tokens) {
  const v = [];
  let exemptNext = false;
  const isP = (t, s) => t && t.type === "punct" && t.text === s;
  for (let k = 0; k < tokens.length; k++) {
    const tok = tokens[k];
    if (tok.type === "string") {
      const wasExempt = exemptNext;
      exemptNext = false;
      if (wasExempt) continue;
      if (CJK_RE.test(tok.text) && !ZH_ALLOW.has(tok.text)) v.push(tok);
    } else if (tok.type === "ident" && (tok.text === "tf" || tok.text === "callT")
        && isP(tokens[k + 1], "(") && tokens[k + 2] && tokens[k + 2].type === "string"
        && isP(tokens[k + 3], ",")) {
      exemptNext = true;
      k += 3; // 跳到 "，"；循环自增后正好落在 zh 兜底参上
    } else if (exemptNext) {
      exemptNext = false;
    }
  }
  return v;
}

/* 预剥离中文纯数据声明（值非 UI：仅作数据比对，或作为调用点 I18N.tf() 的 zh 兜底
 * 被动态包裹——定义处包裹会把语言冻结在首载 locale，见 modeLabel 范式）。
 * 名单（新增表请附理由追加）：
 *   CITYS/PLAN_CITIES  城市坐标/规划城市表：经 I18N.city() 渲染；
 *   ORI                方位表：与高德数据比对，仅 emoji 上屏；
 *   AMAP_DETAIL_ZH/AUTH_ERR_CN  高德 detail 码/后端账号错误码 → 中文，调用点 tf("前缀."+code, 表[code])；
 *   MODE_CN/BRIEF_TAGS/PREFS/REVIEW_TAGS/t9nName  交通方式/简报标签/偏好/点评标签/译向名，同上调用点动态包裹。
 * 锚点正则只负责"找到"声明头；数组/对象本体含嵌套括号，故从起始括号起做
 * 字符串感知的配平扫描到配对闭括号，再吞可选 ";"。整段替换为等长空白（保留 \n）
 * → 行号零漂移。返回 {code, found}：found 为本次命中的声明名集合。 */
const ZH_DATA_NAMES = ["CITYS", "PLAN_CITIES", "ORI", "AMAP_DETAIL_ZH", "AUTH_ERR_CN",
  "MODE_CN", "BRIEF_TAGS", "PREFS", "REVIEW_TAGS", "t9nName",
  "TC_SRC", "BK_CHANNEL", "BK_KIND_ZH", "PAY_STATUS_ZH", "TV_DOC_ZH", "WELCOME"]; // TV_DOC_ZH 证件类型 code→中文兜底，tvDocLabel 调用点 tf(key, 表[code]) 动态包裹 // 各「code→中文兜底」表：调用点 tf("前缀."+code, 表[code]) 动态包裹（WELCOME 为 [flowId, key, zh 兜底] 行，i18n:change 时重写欢迎气泡）
const ZH_DATA_DECL_RE = new RegExp("(?:var|const|let)\\s+(" + ZH_DATA_NAMES.join("|") + ")\\s*=\\s*([\\[{])", "g");
function stripZhDataArrays(code) {
  const found = new Set();
  let out = code;
  for (;;) {
    ZH_DATA_DECL_RE.lastIndex = 0;
    const m = ZH_DATA_DECL_RE.exec(out);
    if (!m) break;
    found.add(m[1]);
    const open = m[2], close = open === "[" ? "]" : "}";
    let j = m.index + m[0].length; // 指向起始括号之后
    let depth = 1, q = null;
    while (j < out.length && depth > 0) {
      const ch = out[j];
      if (q) { if (ch === "\\") { j++; } else if (ch === q) q = null; }
      else if (ch === "'" || ch === '"') q = ch;
      else if (ch === "[") depth++;      // 对象内嵌数组照常配平
      else if (ch === "{") depth++;
      else if (ch === "]" || ch === "}") depth--;
      j++;
    }
    if (out[j] === ";") j++;
    let blank = "";
    for (let k = m.index; k < j; k++) blank += out[k] === "\n" ? "\n" : " ";
    out = out.slice(0, m.index) + blank + out.slice(j);
  }
  return { code: out, found };
}

/* ---------- C. 残留门（EN 模式中文残留扫描，仅 index.html） ---------- */
function gateC() {
  const p = path.join(STATIC_DIR, "index.html");
  if (!fs.existsSync(p)) { fail("残留门: index.html 不存在"); return; }
  const src = fs.readFileSync(p, "utf8");
  const blocks = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  if (!blocks.length) { fail("残留门: index.html 没有内联 <script> 块"); return; }

  const declFound = new Set();
  const violations = [];
  blocks.forEach((m, bi) => {
    const stripped = stripZhDataArrays(m[1]);
    stripped.found.forEach(n => declFound.add(n));
    for (const tok of findZhViolations(tokenizeJs(stripped.code)))
      violations.push({ block: bi, line: tok.line, text: tok.text });
  });
  for (const name of ["CITYS", "PLAN_CITIES", "ORI"])
    if (!declFound.has(name)) fail("残留门: 未找到 " + name + " 声明（预剥离规则失效？）");

  const CAP = 40;
  violations.slice(0, CAP).forEach(v =>
    fail('残留门 index.html 脚本块#' + v.block + ":" + v.line + ' 含中文未包 tf(): "' + v.text.slice(0, 30) + '…"'));
  if (violations.length > CAP) console.error("…and " + (violations.length - CAP) + " more");
  if (!violations.length && declFound.size === 3)
    ok("残留门 index.html " + blocks.length + " 个脚本块无未包裹中文（已预剥离 CITYS/PLAN_CITIES/ORI）");
}

/* ---------- 入口：直接运行才执行；被 require 时只导出分词器供 harness 复用 ---------- */
function main() {
  gateA();
  gateB();
  gateC();
  if (failed) { console.error("\n" + failed + " 项未过——见上方 FAIL"); process.exit(1); }
  console.log("\nH5 静态守门全部通过");
}
if (require.main === module) main();
module.exports = { tokenizeJs, stripZhDataArrays, findZhViolations, CJK_RE, ZH_ALLOW };
