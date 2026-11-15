# 用户可选二级标签体系（粗颗粒）设计

- 日期：2026-11-10（实施完成 2026-11-11）
- **后续实施与决策以 DESIGN/tag_implementation_decisions_2026-11-12.md 为准**（D1 baidu 价格/时长链、D2 餐厅 hours 灌注、D3 meal_periods、D4 trip.com 正文抽取、D5 景点选择器 w12_0022 + GET /api/pois/tags）。
- 需求（用户拍板）：给**用户选择器**用的标签，现有库内标签太多太细 → 做成**一级大类 + 二级子标签**两层，颗粒度粗；餐段 `meal_periods` 与价位 `price_level` 确认要做；做完后做第三部分 **Review Tag（体验标签）**。
- 设计铁律：每个二级标签必须能从库内现有字段（`category` / `tags` / `review_tags` / `cuisine` / `best_visit_time` / 营业时间）**推导得出**，否则用户选了查询不出结果。映射规则见各表"推导"列。
- 规模控制：景点一级 7 / 二级 25；餐厅一级 6 / 二级 18（§二原计 21 有误，实际 18 组全部有货）；Review Tag 景点 12 / 餐厅 10。对比原库 26 category + 36 review_tags + 575 cuisine 原值，选择器总量从 600+ 收敛到 ~68。

## 实施状态（2026-11-11）

| 步骤 | 状态 | 产出 |
|---|---|---|
| ① 餐厅二级 TAG | ✅ 完成 | alembic w12_0021（cuisine_family/cuisine_group 列+索引）；`app/services/cuisine_taxonomy.py` 规则级联（575 原值→18 组，零漏网，空格归一+特异词优先）；`app/jobs/backfill_cuisine_group.py`（fill-empty-only）；5088 行全回填；tests/test_cuisine_taxonomy.py 5 用例 |
| ② price_level | ✅ 代码完成，实跑待 WAF 冷却 | 携程国内美食页实测 JS 空壳无价格（列表 2MB 零价格键/html5 镜像 146B 壳/详情页 2MB 无 人均），price 走高德腿：`app/services/amap_client.py` `_parse_cost`+`_hours_result`/`place_hours` 带出 `cost` 键；`app/services/price_band.py` 5 档半开区间；`app/jobs/fill_restaurant_price.py`（fill-empty-only+名称双向包含闸+配额/WAF 首撞即停熔断，2026-11-11 试跑熔断语义实测通过）；tests/test_price_band.py 4 用例。amap WAF 2026-11-03 起惩罚期（bixi punish），明日重置后 `python -m app.jobs.fill_restaurant_price` 无损续跑 |
| ③ Review Tag | ✅ 完成 | `app/services/review_tag_coarse.py` 36 细词→12 粗桶（词表即 alias 对照，未知词透传，幂等）；`enrich_ctrip_detail.py` 写入点粗化接入；`app/jobs/backfill_review_tags_coarse.py` 存量重刷 883 行（粗词 12 桶全落位，「城市漫步」唯一透传词保留）；tests/test_review_tag_coarse.py 4 用例 |

回归：tests/test_restaurants.py + test_ctrip_hours.py + test_enrich_variants.py + test_amap.py 112 全绿。

---

## 一、景点二级标签（用户偏好选择）

### 1. 自然山水
| 二级 | 推导（category / review_tags / 名字规则） |
|---|---|
| 山岳登高 | review_tags∈{登高爬山,徒步} ∨ (category=nature ∧ 名字带 山\|峰\|岭) |
| 江河湖泊 | review_tags∈{自然山水,乘船游览} ∨ 名字带 江\|河\|湖\|库 |
| 瀑布溶洞 | 名字带 瀑\|洞\|溶 ∨ tags=unesco_karst |
| 草原沙漠 | review_tags∈{草原采风,沙漠戈壁} |
| 森林湿地 | 名字带 森林\|湿地\|地质公园 |

### 2. 滨海水上
| 二级 | 推导 |
|---|---|
| 海滨海岛 | review_tags=海滨玩水 ∨ 名字带 海\|岛\|湾\|礁 |
| 漂流冲浪 | review_tags∈{漂流,清凉漂流,冲浪,亲水乐园} |
| 游船夜航 | review_tags∈{乘船游览,游艇帆船,游船} |

### 3. 历史人文
| 二级 | 推导 |
|---|---|
| 博物馆 | category∈{museum,gallery,memorial} ∨ tags∋国家[一二三]级博物馆 |
| 古迹遗址 | category∈{historic,ruins} ∨ tags∋unesco* ∨ review_tags=历史建筑 |
| 古镇古村 | category=ancient_town ∨ tags∋{histvillage,中国历史文化名镇} ∨ review_tags=古镇古村 |
| 寺庙教堂 | category∈{temple,church,castle} |
| 纪念场馆 | category=memorial ∧ 名字带 纪念（与博物馆组互斥时归博物馆） |

### 4. 园林街区
| 二级 | 推导 |
|---|---|
| 园林花园 | category∈{garden} ∨ review_tags∈{园林花园,赏花胜地} |
| 城市公园 | category=park |
| 街区漫步 | category=citywalk ∨ source=street ∨ tags∋citywalk ∨ review_tags=城市漫步 ∨ 名字带 街区\|步行街 |
| 地标观景 | category=viewpoint ∨ tags=landmark ∨ review_tags=地标观景 |

### 5. 亲子乐园
| 二级 | 推导 |
|---|---|
| 主题乐园 | category=theme_park |
| 动物水族 | category=zoo ∨ review_tags=亲近动物 |
| 科技探索 | review_tags∈{科技馆,儿童乐园,遛娃宝藏地}（遛娃为弱信号兜底） |

### 6. 演艺夜游
| 二级 | 推导 |
|---|---|
| 演出秀 | category=entertainment ∨ tags=show ∨ best_visit_time=show |
| 夜市夜景 | review_tags=夜游观景 ∨ best_visit_time=evening |

### 7. 休闲度假
| 二级 | 推导 |
|---|---|
| 温泉疗养 | review_tags∈{泡温泉,度假村} |
| 冰雪运动 | review_tags∋滑雪 ∨ review_tags∈{冰雪乐园} |
| 茶室禅意 | category=tea_experience ∨ review_tags=文化体验 |

> 混入 pois 表的 hotel/food/transport 行不进任何用户标签（选择器按 category 排除）。

---

## 二、餐厅二级标签（cuisine 粗化归并，中文为准）

### 1. 中餐经典
| 二级 | 归并现有 cuisine 值 |
|---|---|
| 川湘辣味 | 川菜、湘菜、Sichuan、串串香 |
| 粤式茶点 | 粤菜、Cantonese、Cantonese Cuisine、茶餐厅、Dim Sum、潮汕菜、Chao Zhou |
| 江浙本帮 | 本帮菜、Shanghainese、杭帮菜、苏帮菜、淮扬菜、江浙菜、Zhejiang、Jiangsu Cuisine |
| 北方风味 | 北京菜、京菜、鲁菜、东北菜、烤鸭 |
| 西北面食 | 新疆菜、清真菜、面馆、Noodles、饺子包子 |
| 云贵地方 | 云南菜、贵州菜、湖北菜、家常菜、私房菜、农家菜、创意菜、融合菜、Innovative、中餐、中餐厅、其他 |

### 2. 异国风味
| 二级 | 归并 |
|---|---|
| 日韩料理 | 日料、日料烧肉、日式烧肉、韩国料理 |
| 东南亚菜 | 泰国菜、越南菜、新加坡菜 |
| 西餐 | 西餐、意大利菜、法餐、披萨、俄餐 |

### 3. 火锅烧烤
| 二级 | 归并 |
|---|---|
| 火锅串串 | 火锅、潮汕牛肉火锅、串串香 |
| 烧烤烤鱼 | 烧烤、烤鱼、烤肉、小龙虾 |

### 4. 便捷小吃
| 二级 | 归并 |
|---|---|
| 小吃快餐 | 小吃、小吃快餐 |
| 自助餐 | 自助餐 |

### 5. 轻食茶饮
| 二级 | 归并 |
|---|---|
| 咖啡烘焙 | 咖啡烘焙、烘焙甜品 |
| 茶馆茶楼 | 茶馆 |
| 素食轻食 | 素食、Vegetarian |

### 6. 夜宵酒吧
| 二级 | 归并 |
|---|---|
| 酒吧夜店 | 酒吧 |
| 夜宵排档 | （由 meal_periods=late_night 反推，见 §三） |

> 落库方案：`cuisine` 保留原始值不动（回源链还会写英文），新增列 `cuisine_group`（二级，如"川湘辣味"）+ `cuisine_family`（一级，如"中餐经典"），由清洗任务一次性推导回填；查询层用 group/family，展示用原始 cuisine。

---

## 三、餐段 `meal_periods`（已确认要做）

| 值 | 含义 | 推导 |
|---|---|---|
| early_tea | 早茶（粤式 06:00–10:30 茶点） | 营业时间 ∧ cuisine_group∈{粤式茶点} ∧ 开门<10:30 |
| breakfast | 早餐 | 营业开始 ≤09:00 |
| lunch | 午市正餐 | 营业覆盖 11:00–14:00 |
| afternoon_tea | 下午茶 | 14:00–17:00 开门 ∧ 咖啡烘焙/茶馆 |
| dinner | 晚市正餐 | 营业覆盖 17:00–21:00 |
| late_night | 夜宵 | 营业结束 ≥24:00 或 ∩02:00 |

槽位对接口径（对接 `app/services/restaurants.py::_allowed_slots_for`）：lunch 槽 ← {early_tea, breakfast, lunch, afternoon_tea}；dinner 槽 ← {dinner, late_night}；`meal_periods` 显式值**优先于**营业时间推断。

---

## 四、价位 `price_level`（已确认要做）

| 档位 | 区间（元/人） |
|---|---|
| budget | ≤50 |
| value | 50–100 |
| mid | 100–200 |
| upper | 200–500 |
| premium | >500 |

推导：`avg_cost` 优先，其次 ctrip 人均（enrich 链已有字段则直取）；`avg_cost` 与档位同任务回填。

---

## 五、第三部分：Review Tag 体验标签（用户可选）

### 景点（36 个 ctrip 词 → 12 个粗标签，保留原词为 alias）

| 粗标签 | 合并原词 |
|---|---|
| 适合带娃 | 亲子同乐、遛娃宝藏地、儿童乐园 |
| 拍照打卡 | 地标观景、夜游观景 |
| 登山徒步 | 登高爬山、徒步 |
| 赏花看园 | 赏花胜地、园林花园 |
| 水上项目 | 乘船游览、漂流、清凉漂流、海滨玩水、潜水、冲浪、游艇帆船、亲水乐园 |
| 亲近动物 | 亲近动物 |
| 怀旧历史 | 历史建筑、古镇古村、影视基地 |
| 刺激冒险 | 跳伞、飞行体验、漂流（与水上重叠时优先水上） |
| 温泉滑雪 | 泡温泉、滑雪、室内滑雪、户外滑雪、冰雪乐园 |
| 自然野趣 | 自然山水、草原采风、沙漠戈壁 |
| 科技探索 | 科技馆 |
| 文化体验 | 文化体验、度假村、巴士观光、缆车索道 |

### 餐厅（全空列起步，两路来源）

**外部可采（ctrip/大众类评论标签）：**
| 粗标签 | 含义 |
|---|---|
| 老字号 | 中华老字号/ decades 店 |
| 本地人常去 | 本地流量占比高 |
| 约会氛围 | 环境/氛围评论高频 |
| 家庭聚餐 | 适合多人/带娃 |
| 商务宴请 | 包间/高端 |
| 江景夜景位 | 景观位 |
| 深夜营业 | 与 meal_periods=late_night 联动 |

**自产独有（poi_reviews 用户标签，2026-10-24 已定调"只有外国游客会给"）：**
| 粗标签 | 含义 |
|---|---|
| 外卡支付 | 可刷境外信用卡 |
| 英文菜单 | 有英文菜单 |
| 英文服务 | 店员可用英文沟通 |
| 免辣可调 | 辣度可调/不辣友好 |
| 护照预订 | 可凭护照预订/入座 |

> 落库：直接写 `restaurants.review_tags`（JSONB，`review_tags_source` 标 ctrip/self_review），粗标签与原词映射关系同景点表做法。

---

## 六、落地顺序

1. ** cuisine 粗化**：新增 `cuisine_group`/`cuisine_family` 列 + 清洗任务（英文值映射回中文组）——plan.py 不读 cuisine，零风险。
2. **meal_periods / price_level 回填**：由营业时间/avg_cost 推导，接口给 `_allowed_slots_for` 用。
3. **review_tags 粗化归并**：36→12 建 alias 映射表（`review_tags` 写粗标签，原词进 alias），旧数据重刷。
4. **选择器接口**：GET /pois/tags 与 /restaurants/tags 返回本设计的一级/二级树，用户勾选后翻译为库里查询条件（映射规则即本文档各"推导"列）。
