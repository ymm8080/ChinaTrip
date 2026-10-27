# 代客预订客户资料需求 + 隐私合规设计（2026-10-27）

调研结论：各类预订（机票/火车/酒店/景区/演出）所需客户资料的最小集，
以及个人主页录入 + 后台保存的隐私合规设计。对应实现：
`app/services/travelers.py` + `app/api/travelers.py` + H5 个人主页「出行人资料」分区。

## 1. 各预订类型所需资料（按最小必要原则）

| 预订类型 | 必需 | 条件性 | 依据 |
|---|---|---|---|
| ✈️ 机票（国内/国际） | 姓名拼音（与证件完全一致）、证件类型、证件号、国籍、出生日期、性别 | 证件有效期（国际票）、常旅客号、儿童/婴儿类型 | 民航实名制，出票即锁定乘机人 |
| 🚄 火车（12306） | 证件类型、证件号、姓名（中文或拼音）、国籍 | 外国护照首乘需车站窗口核验；手机号（接收通知） | 12306 外国护照身份核验说明（官方 2023-11） |
| 🏨 酒店（涉外） | 姓名（与证件一致）、国籍 | 证件号（部分酒店登记）、到店时间 | 《出境入境管理法》§39 + 治安管理住宿登记：境外人员入住须登记，通常每人一证 |
| 🎫 景区门票（预约制） | 姓名、证件号、证件类型 | 手机号（预约通知） | 故宫/国博等实名预约制，一证一票 |
| 🎭 演出票务 | 姓名、证件号、手机号 | （强实名演出按座位实名） | 大麦/猫眼强实名场次 |

**结论**：统一出行人档案 = 姓名（拼音/中文）+ 证件四元组（类型/号/有效期/国籍）+ 出生日期 + 性别 + 手机号 + 邮箱。证件号、手机号属**敏感个人信息**（PIPL 定级），必须加密存储、展示脱敏、访问留痕。

## 2. 隐私合规设计（PIPL / GDPR 惯例对齐）

1. **知情同意先行**（PIPL §17 / GDPR Art.7）：首次录入前必须勾选同意书
   （说明收集范围、用途=代客预订、保存期限、撤回方式）；`consent=false` 直接 422。
2. **最小必要**（PIPL §6 / GDPR Art.5 data minimisation）：只存上表字段，无地址、无身份证照片。
3. **加密存储**（PIPL §51 安全措施 / GDPR Art.32）：`doc_number` / `phone` 用
   Fernet 对称加密（密钥 `data/.traveler_key` 首次自动生成，不入库不入 repo）。
4. **默认脱敏展示**：列表/读取返回 `doc_number_masked`（如 `E1234**56`）、
   `phone_masked`；明文只经显式导出端点。
5. **可导出/可携**（GDPR Art.20）：`GET /api/v1/travelers/export` 返回本人全部明文数据（JSON 下载）。
6. **可删除/被遗忘**（PIPL §47 / GDPR Art.17）：单条 DELETE + `DELETE /api/v1/travelers`（清空），
   删除即物理删除，无回收站。
7. **访问留痕/审计**（GDPR Art.30 / 等保惯例）：`travel_data_audit` 表记录
   每次创建/修改/导出/删除（时间、动作、主体），**不记数据内容**。
8. **保存期限**（PIPL §19）：资料保留至用户删除为止（用户主权数据，非业务强制留存）；
   同意书文案明确「可随时在个人主页删除」。
9. **数据不出境承诺**：当前全量存本服务器 SQLite；未来上云须选境内节点
   （PIPL 跨境条款）；代订交给渠道时仅按单笔订单最小披露，不批量共享。

## 3. 数据模型（travelers，SQLite h5 同款写穿模式）

```
owner_key          归属（username 或 device:<id>，登录即账号、未登录即设备）
traveler_id        trv_<hex>
label              备注名（如 "本人护照" / "Mom"）
full_name_en       拼音姓名（机票/火车必填，与证件一致）
full_name_zh       中文姓名（持中国证件时）
doc_type           passport | mainland_id | hkmo_passport | tw_passport | foreign_perm_id
doc_number         ***加密***（明文永不回 API 列表）
doc_expiry         YYYY-MM-DD（可选）
nationality        ISO 国家码或自由文本
date_of_birth      YYYY-MM-DD
gender             m | f | x
phone              ***加密***
email              可选（出票通知）
consent            bool（必须 true）
consent_at         ISO 时间
created_at/updated_at
```

### API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/travelers` | 本人列表（证件号/手机号脱敏） |
| POST | `/api/v1/travelers` | 新增（consent 必须 true） |
| PUT | `/api/v1/travelers/{id}` | 修改 |
| DELETE | `/api/v1/travelers/{id}` | 删除单条 |
| DELETE | `/api/v1/travelers` | 清空本人全部 |
| GET | `/api/v1/travelers/export` | 明文导出（审计留痕） |

鉴权同 itineraries.py：X-Device-ID 必填；Bearer 登录后归属自动从设备切到账号。
