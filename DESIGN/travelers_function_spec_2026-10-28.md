# 出行人资料（代客预订客户资料）功能说明

| | |
|---|---|
| 版本 | v1.0（2026-10-28） |
| 状态 | 已实现并验证（全量测试 1383 通过 / 0 失败，连续多轮全绿） |
| 设计依据 | `DESIGN/CLIENT_DATA_REQUIREMENTS.md`（资料需求调研 + 隐私合规设计） |
| 测试文档 | `DESIGN/Testing/travelers_testing_2026-10-28.md` |
| 代码 | `app/services/travelers.py` · `app/api/travelers.py` · H5 个人主页 |

## 1. 功能定位

为「代客预订」（公司运营侧替外国游客下单）提供客户实名资料的**录入、加密保存与按单取用**能力。机票、火车票（12306）、酒店住宿登记、景区预约门票、强实名演出票务五类预订均为实名制，出票时必须提供与证件一致的乘机人/乘车人/入住人信息；此前系统无处保存这些资料，代订只能临时索要。

客户在 **H5 个人主页 →「🪪 出行人资料」分区**自行录入；运营侧代订时按订单需要取用对应出行人条目。

## 2. 各预订类型所需资料（最小必要原则）

| 预订类型 | 必需资料 | 条件性资料 |
|---|---|---|
| ✈️ 机票（国内/国际） | 拼音姓名（与证件一致）、证件类型、证件号、国籍、出生日期、性别 | 证件有效期（国际票）、常旅客号 |
| 🚄 火车（12306） | 证件类型、证件号、姓名、国籍 | 手机号（通知）；外国护照首乘需车站窗口核验 |
| 🏨 酒店（涉外） | 姓名（与证件一致）、国籍 | 证件号（部分酒店）、到店时间 |
| 🎫 景区门票（预约制） | 姓名、证件号、证件类型 | 手机号（预约通知） |
| 🎭 演出票务 | 姓名、证件号、手机号 | 强实名场次按座位实名 |

统一出行人档案 = 姓名（拼音/中文）+ 证件四元组（类型/号/有效期/国籍）+ 出生日期 + 性别 + 手机号 + 邮箱。

## 3. 数据模型

存储：SQLite 写穿（`data/travelers.db`，payments 同款单连接 + Lock 模式），归属 `owner_key`：登录即账号名，未登录为 `device:<id>`（与 itineraries 归属约定一致）。

| 字段 | 说明 |
|---|---|
| label | 备注名（如「本人护照」/「Mom」） |
| full_name_en | 拼音姓名（机票/火车必填，与证件一致） |
| full_name_zh | 中文姓名（可选） |
| doc_type | passport / mainland_id / hkmo_passport / tw_passport / foreign_perm_id |
| doc_number | **Fernet 加密存储**，API 只回脱敏形（如 `E1234**78`） |
| doc_expiry | YYYY-MM-DD（可选） |
| nationality / date_of_birth / gender | 国籍 / 出生日期 / 性别（m/f/x） |
| phone | **Fernet 加密存储**，API 只回脱敏形 |
| email | 可选（出票通知） |
| consent / consent_at | 知情同意标记与时间（必须 true 才能保存） |

每拥有者上限 20 条出行人。

## 4. API（`/api/v1/travelers`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/travelers` | 本人列表（脱敏形 + 同意书文案） |
| POST | `/api/v1/travelers` | 新增（`consent=true` 必须，否则 422） |
| PUT | `/api/v1/travelers/{id}` | 修改（证件号需重填，脱敏形不回填） |
| DELETE | `/api/v1/travelers/{id}` | 删除单条（物理删除） |
| DELETE | `/api/v1/travelers` | 清空本人全部（被遗忘权） |
| GET | `/api/v1/travelers/export` | 明文导出（可携权，唯一明文出口，写审计） |

鉴权同 itineraries.py：`X-Device-ID` 必填；Bearer 登录后归属自动从设备切到账号。错误码：400 `missing_device_id` / 404 `traveler_not_found` / 422 `consent_required`·`invalid_doc_type`·`invalid_gender`·`too_many_travelers`。

## 5. 隐私合规设计（PIPL / GDPR 惯例对齐）

1. **知情同意先行**（PIPL §17 / GDPR Art.7）：不勾同意书直接 422 拒绝保存；同意书文案明确用途、加密、可删除。
2. **最小必要**（PIPL §6 / Art.5）：只存上表字段，不收地址、不收证件照片。
3. **加密存储**（PIPL §51 / Art.32）：敏感字段 Fernet 对称加密；密钥 `data/.traveler_key` 首次自动生成，不入库不入 repo。
4. **默认脱敏**：列表/详情只回脱敏形；短值（≤7 位）全星。
5. **可导出可携**（Art.20）：`/export` 返回本人全部明文 JSON，服务层写审计行。
6. **可删除/被遗忘**（PIPL §47 / Art.17）：单条删除 + 一键清空，物理删除无回收站。
7. **访问审计**（Art.30）：`travel_data_audit` 表只记 (时间， 主体， 动作)，不含任何字段值。
8. **保存期限**（PIPL §19）：保留至用户删除为止；文案明示「可随时在个人主页删除」。
9. **数据不出境**：全量存本服务器 SQLite；未来上云须境内节点（PIPL 跨境条款）。

## 6. 前端（H5 个人主页）

入口：导航「👤 个人主页」→「🪪 出行人资料（代客预订）」分区。

- 表单：备注名 / 拼音姓名 / 中文姓名 / 证件类型（5 种）/ 证件号 / 有效期 / 国籍 / 出生日期 / 性别 / 手机号 / 邮箱
- 同意书勾选（未勾选点保存会被前端拦截，后端双保险 422）
- 列表卡片：脱敏证件号徽章、有效期、国籍/生日/性别/手机（脱敏）/邮箱
- 操作：✏️ 编辑（证件号留空强制重填）、🗑 删除（物理删除提示）、⬇️ 导出明文 JSON、🗑 清空全部（confirm 二次确认）
- 文案走 i18n 双语（zh 内联兜底 + en 词典 `me.tv.*`），H5 静态守门（残留门/词典覆盖门）全绿

## 7. 文件清单

| 文件 | 内容 |
|---|---|
| `app/services/travelers.py` | 加密存储 + 脱敏 + 审计 + 归属 |
| `app/api/travelers.py` | 六个端点 + 错误映射 |
| `app/config.py` | `travelers_db_url` 配置项 |
| `app/main.py` | 路由接线 |
| `app/static/index.html` | 个人主页分区 + JS 逻辑（TV_*） |
| `app/static/i18n.js` | en 词条（me.tv.* 24 条） |
| `ops/check_h5_static.js` | ZH_DATA_NAMES 白名单 + `TV_DOC_ZH` |
| `tests/test_travelers_api.py` | 9 项测试 |
| `requirements.txt` | `cryptography>=42.0` |
| `DESIGN/CLIENT_DATA_REQUIREMENTS.md` | 需求调研 + 合规设计 |
| `DESIGN/Testing/travelers_testing_2026-10-28.md` | 测试文档 |
