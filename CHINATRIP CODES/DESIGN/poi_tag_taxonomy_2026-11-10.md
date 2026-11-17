# POI 分类标签体系盘点与建议（景点 / 餐厅）

- 日期：2026-11-10
- 方法：直查本地库 `pois`（14257 行）/ `restaurants`（5088 行）实测分布 + 读下游消费代码（`app/services/agent/plan.py`、`app/services/restaurants.py`、`app/models.py`）
- 调研脚本：`ops/_tmp_tag_survey.py`（可重跑），原始输出 `ops/_tmp_tag_survey.out.txt`

---

## 一、现状：两表各有哪几个"标签维度"

### 景点 `pois` —— 4 个标签维度 + 1 组结构化属性

| 维度 | 存储 | 实测覆盖 | 性质 |
|---|---|---|---|
| 品类 | `category` String(50) 单值 | 26 种（59 行 NULL） | 主分类，规划引擎品类闸依赖 |
| 资质/榜单 | `tags` JSONB 数组 | 7605 行（53%）有值 | **两种性质混装**（见 §二） |
| 体验玩法 | `review_tags` JSONB | 仅 880 行（6%，全部 ctrip 回源） | 对游客的"能干什么" |
| 榜单溯源 | `tags_source` | datasource_csv/cma/mct/mohurd/curated/各国际站 | 写入渠道 |
| 结构化属性 | 独立列 | best_visit_time / indoor / rain_ok / reservation_required / district / business_area / ticket_price_min-max / suggested_duration_min | 不算 tag 但承担分类职能 |

#### 1. `category` 实测 26 种

```
nature 4615 / hotel 3785 / museum 1789 / attraction 1743 / theme_park 586
park 369 / historic 348 / ancient_town 347 / other 171 / entertainment 158
food 47 / citywalk 47 / viewpoint 43 / art 43 / transport 35 / temple 26
gallery 12 / memorial 7 / garden 7 / zoo 6 / ruins 4 / church 4
tea_experience 3 / castle 3 / NULL 59
```

注意：`hotel`(3785)、`food`(47)、`transport`(35) 是服务类混在景点表里——规划引擎按 category 消费（`plan.py` `_UNCAPPED_CATEGORIES` 含 food/entertainment，hotel 有专属分流），属有意设计，但"景点分类标签"讨论时应把这三类拎出去。

#### 2. `tags` 实测全部取值（按性质分四组）

- **景区等级**：`4a`(4402) `5a`(358) `3a`(2)
- **官方挂牌/称号**：国家三级博物馆(662)、国家二级博物馆(384)、国家一级博物馆(245)、中国历史文化名镇(302)、国家级旅游休闲街区(199)、国家重点美术馆(12)、histvillage(477)、relicpark(1)、landmark(1)
- **世界遗产**：`unesco`(93) + 细分 `unesco_ming_tombs`(19) `unesco_silk_road`(17) `unesco_karst`(7) `unesco_yellow_bohai`(4) `unesco_three_parallel_rivers`(3) `unesco_tusi_sites`(3) `unesco_grand_canal`(2)
- **酒店星级**（混在 pois 表的 hotel 行上）：star_5(134) star_4(84) star_3(12)
- **国际荐点/渠道标**（不是主题标签，是"谁推荐过"）：`intl`(281) lp(62) ta(30) sygic(44) tui(30) klook(16) layla(54) mindtrip(21) xiaohongshu(27) culturetrip(4) kkday(3) viator(3) watchmojo(1) wonderplan(1) tiktok(1) labels(3) + 合并/功能标 curated(75) show(49) citywalk(13)

#### 3. `review_tags` 实测 36 种（ctrip 体验标签，全部）

赏花胜地 517、遛娃宝藏地 405、亲子同乐 399、夜游观景 303、历史建筑 253、乘船游览 215、自然山水 196、登高爬山 135、漂流 47、古镇古村 45、城市漫步 43、地标观景 39、清凉漂流 29、海滨玩水 21、园林花园 20、亲近动物 14、科技馆 9、度假村 7、徒步 7、草原采风 7、影视基地 5、沙漠戈壁 5、文化体验 4、泡温泉 4、儿童乐园 3、冰雪乐园 3、滑雪 3、室内滑雪 2、潜水 2、缆车索道 2、亲水乐园 1、冲浪 1、巴士观光 1、户外滑雪 1、游艇帆船 1、跳伞 1、飞行体验 1

覆盖仅 6%（880/14257），且 `review_tags_source` 只有 `ctrip` 一种。

#### 4. 结构化属性的脏数据

- `indoor`：`true/false`(7324/3215) 与 `yes/no`(731/2060) **两套布尔词汇并存**，`partial`(409)
- `rain_ok`：同样 `true/false` 与 `yes/no` 并存（1332/7086 vs 883/127）
- `best_visit_time`：any 14018 / evening 75 / morning 65 / show 45 / sunset 34 / sunrise 13 / afternoon 7
- `reservation_required`：仅 89 行 true，其余 NULL（非 false）

### 餐厅 `restaurants` —— 2 个有值的维度 + 3 个全空设计位

| 维度 | 存储 | 实测覆盖 | 状态 |
|---|---|---|---|
| 菜系 | `cuisine` String(50) 单值 | 全表有值但**严重失范** | 中英混杂、同义不同写、粒度不一 |
| 荣誉 | `tags` JSONB | 580 行（11%） | 仅米其林/黑珍珠 |
| 体验标签 | `review_tags` JSONB | **0** | 管道未回填 |
| 餐段 | `meal_periods` JSONB | **0** | 模型注释设计为「早茶/正餐/夜宵」，未实现 |
| 价位 | `price_level` String(10) | **0** | 模型注释设计分档「<=50/50-100/...」，未实现 |

#### 1. `cuisine` 实测混乱样本（60+ 种）

- **中英双语同义并存**：粤菜(333) = Cantonese(77) = Cantonese Cuisine(17)；川菜(293) = Sichuan(39)；本帮菜(75) = Shanghainese(15)；杭帮菜(71) + 江浙菜(27) + Zhejiang(18) + Jiangsu Cuisine(17)；中餐(158) ≈ 中餐厅(22)
- **英文独立值**：Noodles(50) Dim Sum(16) Vegetarian(15) Innovative(14) Chao Zhou(17)
- **粒度不一**：火锅(422) 下又冒出 潮汕牛肉火锅(16)、串串香(37)；小吃(26) vs 小吃快餐(45)；京菜(42) vs 北京菜(50)；茶馆(36) vs 茶餐厅(23)
- 主要来源：chinatravel(4561) / michelin(389) / black_pearl(138)

#### 2. `tags` 实测全部取值（7 种，纯荣誉）

`bib_gourmand`(245) `black_pearl_1diamond`(201) `michelin_1star`(122) `black_pearl_2diamond`(34) `michelin_2star`(25) `black_pearl_3diamond`(9) `michelin_3star`(4)

---

## 二、下游怎么消费（改词表的约束）

`app/services/agent/plan.py`：

- **品类闸**：`_cat_cap` / `_same_category_full` / `_UNCAPPED_CATEGORIES = ("", "attraction", "sight", "food", "entertainment")` —— category 值一动这里就得动；
- **行程级上限桶** `_ITIN_BUCKET_CAPS = {"museum": 1, "scenic": 1, "citywalk": 2}`：museum 桶含 gallery/memorial/art；scenic 桶 = nature + source=scenic + 「5a/unesco 标 ∧ 名字带 山水语素」；citywalk 桶 = category=citywalk ∨ source=street；
- **体验型下限** `_EXPERIENCE_CATEGORIES = ("entertainment", "tea_experience")`；
- **tags 判定**：演出（tags 含 show / bvt=show / category=entertainment）、unesco 山水（t == "5a" or t.startswith("unesco_")）、curated 孪生标、`catalog_rank(source, tags)` 来源榜排序——**即 tags 里的渠道标（lp/ta/klook…）本身就是排序输入，不能简单清除，只能改名或保留命名空间**。

`app/services/restaurants.py`：

- `amap_category_is_food`：amap typecode「餐饮服务;中餐厅;…」→ 判 food；
- `_allowed_slots_for(opening_hours, best_visit_time)`：由营业时间反推 lunch/dinner 槽位——这正是 `meal_periods` 想要的事的**隐式版**，显式回填后可直接替代。

`app/services/agent/plan.py` 引 `amap_category_is_food`（L135）→ 景点侧也用它排除餐饮骨架行。

## 三、建议的标签体系（"可以给哪些"）

### 景点：5 个正交命名空间

**A. `category` 品类（保留单值，26 → 收敛 20）**

```
自然类:  nature / park / garden / viewpoint / zoo
人文类:  museum / historic / ancient_town / temple / church / castle
         ruins / memorial / gallery / art
娱乐类:  theme_park / entertainment
城市体验: citywalk / tea_experience / other
服务类(混入, 明确不计景点): hotel / food / transport
```

attraction 保留为粗桶兜底（品类闸已按粗桶豁免）。gallery/memorial/art 已被 museum 桶并族计数，可考虑长期并入 museum 但短期不动（下游硬编码依赖）。

**B. `tags`-cert 官方资质标（现有 9 种，可补 3 类）**

已有：3a/4a/5a、国家一/二/三级博物馆、国家重点美术馆、中国历史文化名镇、国家级旅游休闲街区、histvillage、relicpark、unesco(+7 细分)。
可补：全国重点文物保护单位、国家森林公园/地质公园/湿地公园、国家级夜间文旅消费集聚区——均为公开名录，采集成本低。

**C. `review_tags` 体验玩法标（现有 36 种 ctrip 词，建议归并成 ~24 标准词）**

```
亲子类:  亲子同乐 / 儿童乐园（合并 遛娃宝藏地）
夜游类:  夜游观景 / 夜间演艺
山水类:  自然山水 / 登高爬山 / 徒步 / 沙漠戈壁 / 草原
水上游:  乘船游览 / 漂流（合并 清凉漂流）/ 海滨玩水 / 潜水 / 冲浪 / 游艇帆船
园林类:  园林花园 / 赏花胜地
人文类:  历史建筑 / 古镇古村 / 文化体验 / 影视基地 / 科技馆
动物类:  亲近动物
休闲类:  泡温泉 / 度假村 / 缆车索道 / 巴士观光
极限类:  滑雪（合并 室内/户外滑雪）/ 跳伞 / 飞行体验
城市类:  城市漫步 / 地标观景
```

同义词合并时保留 ctrip 原词为 alias（回源链还会再写入）。

**D. 结构化属性（已有列，先清脏再谈扩展）**

- best_visit_time：any/morning/afternoon/evening/sunrise/sunset/show（词汇表已稳定）
- indoor / rain_ok：**统一为 yes/no/partial**，把 true/false 双写迁移掉（计划查询两套都写就白搭）
- reservation_required / reservation_advance_days / booking_url：预约制约束

**E. `tags`-intl 国际荐点标（渠道性质，建议加前缀或挪列）**

lp / ta / sygic / tui / klook / layla / mindtrip / xiaohongshu / culturetrip / kkday / viator / curated / show / intl / landmark / watchmojo / wonderplan / tiktok / labels —— 这些与 B 组资质标混在同一数组里，且 `catalog_rank` 拿它们当排序输入。建议：短期在文档里明确"tags = 资质标 + 荐点标"两命名空间；长期加前缀（`intl_lp` / `intl_ta`）或拆独立列 `intl_lists`，改造时同步 `catalog_rank`。

### 餐厅：5 个正交维度（3 个是现成空位，等于"设计已批、数据未灌"）

**A. `cuisine` 菜系（清洗为受控词表，~30 值，中文为准 + `cuisine_en` 列已有）**

```
八大菜系: 粤菜 川菜 湘菜 苏菜 浙菜 闽菜 鲁菜 徽菜
地方菜:   本帮菜 杭帮菜 京菜 潮汕菜 客家菜 新疆菜 湖北菜 云南菜 东北菜 西北菜
异国风味: 日料 韩国菜 泰国菜 东南亚菜 印度菜 意大利菜 法国菜 西餐 俄餐
形态类:   火锅(含 潮汕牛肉火锅/串串香 归入子标) 烧烤 烤肉 自助餐 小吃快餐
          面馆 饺子包子 茶餐厅 咖啡烘焙 茶馆 酒吧 素食 海鲜 清真菜 创意融合
```

清洗规则：英文值映射回中文（Cantonese→粤菜、Dim Sum→粤菜/点心、Noodles→面馆…）；粒度细值（潮汕牛肉火锅）降为 cuisine=火锅 + review_tags 补充。

**B. `tags` 荣誉标（现有 7 种已规范，可扩）**

michelin_1/2/3star、bib_gourmand、black_pearl_1/2/3diamond（已上线）；可扩：米其林入选（非星）、必吃榜、黑珍珠年度入围。

**C. `meal_periods` 餐段（设计位已有，回填）**

`early_tea(早茶) / breakfast / lunch / afternoon_tea / dinner / late_night`——由营业时间 + amap「宜」字段推导（`_allowed_slots_for` 的显式化），支撑晚餐槽位选点与"老广早茶"类体验。

**D. `price_level` 价位（设计位已有，回填）**

按模型注释分档：`<=50 / 50-100 / 100-200 / 200-500 / >500`（元/人，来源 avg_cost 或 ctrip 人均）。

**E. `review_tags` 体验/场景标（全空，最值钱的一块——入境客视角）**

两类来源：
1. ctrip 餐厅评论标签（同景点管道可采）：老字号、适合约会、家庭聚会、商务宴请、景观餐厅、深夜营业、本地人常去…
2. **自产评论独有标签**（`poi_reviews` 设计注释 2026-10-24 已定调）：外卡支付、英文菜单、英文服务、护照可预订、适配外国口味——主要客户是外国入境游客，这类标签只有自家用户会给，是差异化资产。

---

## 四、落地顺序建议

1. **清洗**（不动下游）：indoor/rain_ok true/false → yes/no 统一双写；cuisine 英文值映射回中文（纯 UPDATE，plan.py 不读 cuisine）。
2. **回填空位**（不动下游）：restaurants.meal_periods / price_level / review_tags 由现有 enrich 管道推导回填。
3. **词表归并**（带 alias 兼容）：review_tags 36 → 24 标准词。
4. **命名空间改造**（动 plan.py `catalog_rank`，单独立项）：pois.tags 拆 cert / intl 两个命名空间。
