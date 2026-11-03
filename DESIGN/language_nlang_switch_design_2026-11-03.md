# 多语言通用化设计（分层语言策略 + 页内语言切换器）— 2026-11-03

状态：v1.0 设计定稿待实施 ｜ 触发：用户需求「H5 现中英双语，如何灵活支持多语言 + 页面上语言切换」+ 同日拍板「偶发语言直接用浏览器网页翻译，不为一档语言加 POI 列」
关联：[language_dual_system_design_2026-10-25.md](language_dual_system_design_2026-10-25.md)（部署边界/分库/`_en` 列的权威设计，**不因本文改变**）、[translation_pipeline_design_2026-10-30.md](translation_pipeline_design_2026-10-30.md)（用户语言口径「中文为主 + 英文，偶尔其它语言」）

---

## 0. 决策摘要

语言**分三层**，机制一次建好、语言逐个加入、投入按档位递减：

| 层 | 定义 | UI 文案 | POI/参考数据 | Agent 生成内容 | 单语言成本 |
| --- | --- | --- | --- | --- | --- |
| **L1 产品级** | zh、en（**已建成**） | 前端字典全量 | 专属列（`name_en` 等，既有） | prompt 档（既有） | 已沉没 |
| **L2 试点级** | 候选 ja / ko（西安入境主力客源） | 前端字典 ~450 key + 城市名 199 条 | **serve en，浏览器翻译 en→X**，零 DB 改动 | 新增该语言 prompt 档 | 一次字典批量 + 一个 prompt 档 |
| **L3 偶发级** | 其余任何语言 | 回退 en 字典 | 同上，浏览器原生整页翻译 | en 生成，浏览器翻 | **零** |

三条核心拍板：

1. **零新增 POI 列**（2026-11-03）。偶发/试点语言的 POI 内容翻译交给浏览器网页翻译；数据侧 serve en（pivot 语言 MT 质量最优，且 `_en` 已部分人工校订）。
2. JSONB `translations` 列方案**降级为毕业通道**：仅当某语言流量/留存达到产品级标准（类比 en 的双部署地位）才启用，一列含所有未来语言，避免每语言一列的迁移爆炸。
3. 通用机制（后端 `L()` 位置制回退链 + 前端字典回退链 + 页内 picker）一次建成，加语言从此是**数据 + 配置动作，不是机制改动**。

## 1. 现状盘点（代码事实，2026-11-03 探针）

| 层 | 现状 | 位置 |
| --- | --- | --- |
| 后端语言态 | `ContextVar` 存 lang，默认 zh；`set_lang` 把一切非 en 归一成 zh | `app/services/lang_ctx.py:9-20` |
| 后端双语串 | `L(zh, en)` 位置对，~257 处调用 / 22 文件（plan.py 128、trip_export 39、rules 14、visa_check 14、pipeline 13） | `lang_ctx.py:24` |
| 语言注入 | `LangMiddleware` 每请求读 `X-Lang` 头 | `app/middleware/lang.py:14-19` |
| 分享页 | 无 app 壳，读 `?lang=` query | `app/api/share.py:129-139` |
| Agent 输出 | `lang=get_lang()` 进规划管线，prompt 分档 | `app/api/plan.py:321` |
| 前端字典 | `I18N.DICT` 仅 `"zh-CN"`/`"en"` 两顶层键，~450 key；`tf(key, fallbackZh)` 以 en 字典为准、zh 内联兜底 | `app/static/i18n.js:10,58,955` |
| 前端 locale | `ct_locale` 存 localStorage（值仅 en/zh-CN）；`toggle()` 二元翻板；`i18n:change` 事件驱动重渲染 | `i18n.js:939-948,1002,947` |
| 城市名 | `CITY_EN` 硬编码映射 199 条 | `i18n.js:731` |
| 头部注入 | 所有 fetch 三目 `X-Lang: en|zh` | `app/static/index.html:913,978` |
| SW 缓存 | `i18n.js` 在 SHELL 预缓存，字典改动必须 `sw.js VERSION` +1 | `app/static/sw.js:5,8` |
| DB | `pois`: name/address/opening_hours + `_en` 列对；`restaurants`: name/cuisine + `_en`；只填空语义，backfill 不覆盖 | `app/models.py:54-69` |
| 货币二元 | `usd/cny` 硬编码判断 4 处（语言相邻债，见 §7） | `index.html:2081,2270,3246,4915` |

## 2. 通用机制（一次建成，语言无关）

### 2.1 后端：位置制 `L()` + 回退链

```python
SUPPORTED = ("zh", "en")          # 起步两员；zh=0 / en=1 位置永久冻结，新语言只 append
DEFAULT_LANG = "zh"               # CN 站默认；INTL 站默认 en（dual 设计 §6 不变）

def L(*texts) -> str:
    for code in _chain(get_lang()):        # 请求语言 → en → zh
        i = SUPPORTED.index(code)
        if i < len(texts):
            return texts[i]
    return texts[0]
```

- **257 处既有调用零改动**：`L("中文", "English")` 两参语义不变；某串要给 L2 语言专属译法时，仅在那一处补第三参 `L(zh, en, ja)`，其余串自动回退 en。
- `set_lang` 归一化升级：BCP47 折叠（`zh-CN`/`zh-TW`→zh、`en-US`→en），SUPPORTED 成员直通，未知码 → `DEFAULT_LANG`。
- 中间件 / 分享页 `?lang=` / `plan.py` lang 透传共用同一归一化函数。
- `is_en()` 调用点审计列入 P1：逻辑分叉处要么改 `get_lang() == X`（真语言逻辑），要么显式标注为二元保留（货币，见 §7）。

### 2.2 前端：字典回退链 + picker

- `DICT` 顶层键 = 语言短码；新语言 = 新顶层键。`t(key)` 查找链：`DICT[loc] → DICT["en"] → tf 内联 zh 原文`——**半翻译语言按 key 逐条回退，可安全上线**。
- `locale()/setLocale` 去二元三目；`ct_locale` 存短码，**读侧归一存量 `"zh-CN"→"zh"`**（向后兼容已存用户）。
- `LANGS` 注册表 `{code, htmlTag, native}`：`zh/zh-CN/中文`、`en/en/English`、L2 落地时 `ja/ja/日本語`…；`<html lang>` 取 `htmlTag`（顺带让浏览器翻译提示弹出正确）。
- **页内切换器**：`toggle()` 二元翻板 → picker（复用 H5 既有 bottom-sheet 模式），原生语言名 + 当前项勾选；点选 → `setLocale` → 既有 `i18n:change` 重渲染链，其余接线不动。
- `X-Lang` 头直通 `locale()` 短码（替换 index.html:913/978 三目）。
- `pick(obj, zhKey, enKey)` 语义升级：locale ≠ zh 时 `*_en ?? zh 基列`（L2/L3 的 POI 数据即此路径，en 作浏览器翻译的源文本）。
- `sw.js VERSION` +1 铁律不变。

## 3. 分层细则

### 3.1 L1 产品级（zh / en，已建成，不动）

`_en` 专属列、双部署默认语言、agent prompt 档、译文人工校订名单——全部沿用 dual 设计 v1.5 现状。本文对 L1 的唯一要求：**机制改造后 zh/en 行为零变化**（P1 出口判据）。

### 3.2 L2 试点级（ja / ko 候选，用户拍板选谁先上）

| 件 | 做法 |
| --- | --- |
| UI 字典 | `DICT["ja"]` 全量种子：GLM 批量翻译 + 高频 key（首页/规划表单/行程卡/报错）人工校订名单，模式同 dual P3 译文质检 |
| 城市名 | `CITY_JA` 199 条（量小，一次批量 + 抽检） |
| Agent 输出 | prompt 加 ja 档（直接日文生成 vs en 生成后翻译，**逐语言拍板**，默认先直接生成） |
| POI 数据 | 零改动：后端 `L()` 回退自动全 en，serializer 已并出 `name_en`；前端 `pick` 走 en，浏览器翻译 en→ja |
| 导出物 | PDF/图片固定 en（服务端生成绕过浏览器，trip_export 39 处 L() 已有 en 档） |

### 3.3 L3 偶发级（其余任何语言，零改动）

不进 picker、不进字典、不进 SUPPORTED。用户浏览器对 zh/en 页面自行弹原生整页翻译（`<html lang>` 正确标注即最佳引导）。**该层不需要任何代码**——机制上唯一要求是 L1/L2 的 `htmlTag` 标注正确。

### 3.4 毕业通道（JSONB translations，仅产品级升级时）

某语言流量/留存达标、需要**可人工校订的专名存储**时：`pois`/`restaurants` 加一列 JSONB `translations`（`{"ja": {"name": …, "address": …}}`），只填空语义，backfill 照抄 `backfill_en_columns` 模式（GLM 快车道 + 短语缓存），参考同步链白名单自动随行、海外侧译文保留策略同 `_en`。一列含所有未来语言，此后加产品级语言零迁移。

## 4. 浏览器网页翻译的能力边界（诚实清单）

| 面 | 浏览器翻译 | 对策 |
| --- | --- | --- |
| 页面渲染的 POI 内容 | ✅ 整页 DOM | 无需对策，L2/L3 主路径 |
| UI 按钮文案 | ⚠️ 能翻但首屏闪烁/术语失控 | 走前端字典，不依赖浏览器 |
| Agent 生成内容（行程理由/提示） | ⚠️ 能翻但双重 MT | prompt 档直接生成（L2）/en+浏览器（L3） |
| 服务端导出 PDF/图片/邮件 | ❌ 绕过浏览器 | 固定 en |
| 专名/菜名质量 | ❌ 不可控**且不可人工校订** | 接受为 L3 属性；要校订 = 升产品级走 §3.4 |
| WebView 内嵌壳 | ❌ 无浏览器翻译 | H5 现为纯浏览器 PWA 暂无此面；未来打包 App 时重评 |
| 用户输入（X 语言许愿/搜索） | 与展示无关 | 输入理解层（t9n 翻译管线多后端，已另有设计） |

## 5. 实施阶段

| 阶段 | 内容 | 出口判据 |
| --- | --- | --- |
| **P1 机制（零行为变化）** | 后端 `L(*texts)` + `SUPPORTED` + 归一化 + pytest；`is_en` 调用点审计；前端回退链 + `LANGS` + picker 替换 toggle + `X-Lang` 直通 + 存量 locale 归一 + sw bump | pytest 全绿；zh/en 冒烟与改造前逐屏无差异 |
| **P2 试点语言（拍板 ja 或 ko）** | 字典种子 + 城市名 + prompt 档 + `LANGS` 注册 + `pick` en 优先链 | 该语言 UI 全量母语、agent 输出该语言、POI 卡浏览器翻译可用、导出 en |
| **P3 毕业通道（按需）** | JSONB `translations` 迁移 + backfill + 同步链带上 + 人工校订名单 | 迁移双库 head；抽检达标；只填空语义有 pytest 钉 |

## 6. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 前后端两份 SUPPORTED/LANGS 注册表漂移 | pytest 解析 `i18n.js` 断言 `DICT` 键 ⊇ 后端 SUPPORTED（读文件断言，防两侧分叉） |
| 存量用户 `ct_locale="zh-CN"` 读不中 | `setLocale`/`locale` 读侧统一归一短码 |
| SW 旧缓存字典 | `sw.js VERSION` +1 铁律（H5 既有规矩） |
| 浏览器翻译质量事故（专名错译） | L3 接受；L2 靠 UI 字典保住高频面；投诉集中即触发毕业通道评估 |
| agent 直接生成小语种质量差 | prompt 档逐语言拍板；劣则改「en 生成 + 翻译管线后置翻译」路径 |
| 字典单文件膨胀 | ≥5 语言再拆 `static/i18n/{code}.js` 按需加载（现 2-3 语言不值得拆） |
| 翻译 job Windows 编码坑 | 子进程一律 `encoding="utf-8"`（既有 GBK 教训） |

## 7. 明确解耦：货币 ≠ 语言

`index.html:2081/2270/3246/4915` 的 `usd/cny` 二元判断是**货币债不是语言债**——ja 用户未必想看 JPY 计价。本机制不扩展它：L1 沿用 en→usd / zh→cny 映射，L2/L3 默认 usd；独立货币选择器另行立项，届时把这 4 处收编。

## 8. 与既有设计的关系

- **dual_system_design v1.5**：部署边界（CN/INTL 分库）、参考数据单向同步、`_en` 列语义全部不变；本文只通用化其 §6「两域名均支持手动切换」这一句的开关机制。L2/L3 不新增部署。
- **translation_pipeline（10-30）**：t9n/ASR 多后端解决**输入侧**语言，本文解决**展示侧**，正交；「偶尔其它语言」即 L3 层零成本设计的正当性来源。
- **规划引擎 v1.4 外国游客为中心**：en 作 pivot 的分层与其一致；G1 预约/G2 免签文案属 L1 `_en` 范畴已有覆盖。

---
*生成：2026-11-03 ｜ 决策讨论：本对话（多语言机制 → 用户质疑「是否所有 POI 要加列/能否直接用浏览器翻译」→ 拍板分层 + 零新列）。实施跟踪在下方修订记录追加。*

## 修订记录

- **v1.0（2026-11-03）**：初稿定稿。机制=位置制 `L(*texts)` + requested→en→zh 回退链 + 前端字典回退链 + picker；分层=L1 产品级（既有）/L2 试点级（字典+prompt 档，数据 serve en）/L3 偶发级（零改动）；拍板零新增 POI 列，JSONB `translations` 降级为产品级毕业通道。
