# 国际旅行网站中国荐点种子（intl picks）— 2026-10-25

## 背景与用户指令

用户 2026-10-25 指令（三轮追加）：

1. 起草 TripAdvisor + Lonely Planet 上的热门中国景点清单；
2. 扩大到「主流旅行网站/代理商」（TripAdvisor、Lonely Planet、Viator 等）
   的中国推荐榜，**并入 pois 库**；
3. **逐条标注推荐来源**（哪个网站/代理商推荐的）。

引擎定位外国游客，但排序信号此前全是国内体系（unesco/5A/4A/3A）——
intl 种子补上国际游客口碑信号（product_rules 规则 #13 记录的 gap）。

## 榜单来源（实测抓取 2026-10-25）

| 标记 | 来源 | 抓取内容 |
|---|---|---|
| `ta` | TripAdvisor | 中国 Attractions 全国榜（慕田峪 #1、太平山顶、外滩、颐和园、故宫…）+ 北京/上海/广州城市页摘要 |
| `lp` | Lonely Planet | [13 best places to visit in China](https://www.lonelyplanet.com/articles/best-places-to-visit-in-china)（莫高窟/虎跳峡/乐山大佛/兵马俑/张掖丹霞/嘉峪关/龙脊梯田/天门山/冰雪大世界…）+ [8 best things to do](https://www.lonelyplanet.com/articles/top-things-to-do-in-china) + [北京 14](https://www.lonelyplanet.com/articles/top-things-to-do-in-beijing) + [上海 16](https://www.lonelyplanet.com/articles/top-things-to-do-in-shanghai-china) |
| `viator` | Viator | China things-to-do 摘要（黄山、布达拉宫、张家界） |
| `curated` | 通识补全 | 榜单只点到城市（LP「苏州园林运河」「重庆赛博朋克」），具体点位按国际游客通识补全——待回源链核实后自然转正 |

TripAdvisor 页面有 bot 墙（直抓 403/空壳），全国榜 + 城市摘要经搜索
快照取得；LP 文章全文抓取成功。

## 库内交叉核对（探针实测 2026-10-25，pois 全库 4157 行）

98 项荐点：**82 项库内有名可对、16 项全缺**。但 82 项里约 20 项命中的
是**子场所行**而非正名行：

- 颐和园 → 库内只有「颐和园冰雪嘉年华」（theme_park）
- 豫园 → 「豫园星空梦幻馆」；上海迪士尼 → 「梦幻世界(上海迪士尼乐园店)」
- 熊猫基地 → 「熊猫小匠研学体验基地」；都江堰 → 「都江堰西街」
- 拙政园 → 「拙政园VR馆」；苏州博物馆 → 「苏州博物馆-特展厅」
- 广州塔 → 「帷幕开啦（广州塔）蜡像馆」；洪崖洞 → 「重逢1980街区」

规划器按名选点，子场所行顶不了正名——所以导入作业按**规范正名**做
精确匹配：命中正名/别名 → 只追加 `intl` + 来源 tags（不动原 source）；
查无（含只有子场所行的情况）→ 插入 `source='intl'` 骨架正名行，
子场所行一律不碰。

## 导入设计（app/jobs/import_intl_picks.py）

- **source 标注（2026-10-26 用户指令改版：明细站点名，不要笼统 intl）**：
  新骨架行 `source=主站点`（`tripadvisor`/`lonelyplanet`/`viator`/
  `curated`，多站同荐优先级 ta>lp>viator>curated）、`source_poi_id=
  '{主站点}:{城市}:{正名}'`（幂等键）；tags 携带
  `['intl', 'ta'/'lp'/'viator'/'curated', …]` 双榜双标（外滩 =
  `intl+ta+lp`），`tags_source=主站点`。既有行 source 保留原值——
  enrich_amap_detail 只处理 source='amap' 行、tier 名单互含读
  source in (unesco,5a)、refresh 升级键绑定 (source, source_poi_id)，
  覆写断三条活链；明细站点落在 tags + tags_source。旧版（2026-10-25）
  source='intl' 行重跑自动升级为明细站点。同名孪生行（天坛 amap +
  天坛公园 5a）全部统一打标——只标首行会因 PG 行序漂移漏标孪生。
  **tags 打标序（2026-10-26 用户标准：多来源全打、国外榜置前）**：
  ta/lp/viator → intl/curated → unesco → 5a → 4a → 3a → 其余原序
  垫后（例：故宫博物院 = `ta,lp,intl,unesco,5a,国家一级博物馆`）。
- **铁律 #9 合规**：外部源只写骨架（名称/城市/类别/标签），不写坐标、
  营业时间、票价。新行无 opening_hours → 自动进入 refresh_pois 的
  stale 窗口，由高德/携程回源链补全并校验存在性（不存在则被淘汰）。
- **tier 定位**：intl 与 5A 同档（tier 3）。依据：用户拍板的档序
  unesco > 5A > 4A > 3A 未含 intl，但引擎面向外国游客，TA/LP 榜就是
  这类用户的「5A 名单」；且多数双榜点位同时本就是 5A/unesco，intl 档
  主要抬升非 A 级国际人气点（田子坊/武康路/798/潘家园）。
  `poi_details.tier_of` 读时判 `'intl' in tags or source in
  (intl/tripadvisor/lonelyplanet/viator/curated)`；
  标签注入对 intl-only 行打 `intl` 而非 `5a`（不虚标 A 级）。
- **v0 prompt** 同步：「带 unesco/5A/4A/3A/intl 标签的优先…intl=国际
  旅行网站人气榜，对外国游客优先」。

## 名单（98 项）

### Tier A：10 个已覆盖城市（72 项）

| 城市 | 荐点（正名） | 来源 |
|---|---|---|
| 北京 | 故宫博物院、慕田峪长城、八达岭长城、颐和园、天坛公园、天安门广场、景山公园、钟鼓楼、南锣鼓巷、明十三陵、潘家园旧货市场、798艺术区 | ta/lp（798=ta） |
| 上海 | 外滩、豫园、东方明珠、上海中心大厦、田子坊、新天地、武康路、静安寺、南京东路步行街、上海博物馆、M50创意园、上海迪士尼乐园、中共一大纪念馆、朱家角古镇、黄浦江游览 | ta/lp |
| 苏州 | 拙政园、苏州博物馆、平江路历史街区、七里山塘、虎丘山风景名胜区、周庄古镇 | lp（点位 curated） |
| 杭州 | 西湖风景名胜区、灵隐飞来峰、龙井村、清河坊历史街区、拱宸桥·桥西历史文化街区、西溪国家湿地公园 | ta+lp / lp / curated |
| 南京 | 中山陵园风景区、明孝陵、夫子庙秦淮风光带、南京城墙（中华门）、南京总统府、南京博物院、侵华日军南京大屠杀遇难同胞纪念馆 | curated（夫子庙/纪念馆=ta） |
| 广州 | 广州塔、沙面岛、长隆野生动物世界、珠江夜游、陈家祠、光孝寺 | ta（珠江夜游/光孝寺=ta+lp） |
| 深圳 | 世界之窗、华侨城创意文化园、深圳湾公园、大梅沙海滨公园 | curated（OCT-LOFT=lp） |
| 成都 | 成都大熊猫繁育研究基地、宽窄巷子、锦里古街、武侯祠、杜甫草堂、成都市人民公园、金沙遗址博物馆、都江堰景区 | ta+lp / lp / curated |
| 重庆 | 洪崖洞民俗风貌区、长江索道、磁器口古镇、李子坝轻轨站、两江夜游 | ta+lp / ta / curated |
| 武汉 | 黄鹤楼、湖北省博物馆、东湖生态旅游风景区、昙华林 | curated |

### Tier B：库未覆盖城市骨架（26 项，未来城市扩展信号）

| 城市 | 荐点 | 来源 |
|---|---|---|
| 西安（库内仅5行） | 秦始皇帝陵博物院（兵马俑）、西安城墙、大雁塔、回民街、西安钟楼、华清宫 | ta+lp / lp / curated |
| 乐山 | 乐山大佛 | lp |
| 敦煌 | 莫高窟 | lp |
| 张掖 | 张掖七彩丹霞景区 | lp |
| 嘉峪关 | 嘉峪关 | lp |
| 桂林 | 漓江、龙脊梯田 | ta+lp / lp |
| 阳朔 | 遇龙河、阳朔西街 | lp |
| 张家界 | 张家界国家森林公园、天门山 | ta+viator / lp |
| 丽江 | 虎跳峡、丽江古城 | lp |
| 哈尔滨 | 哈尔滨冰雪大世界、圣索菲亚大教堂 | lp |
| 厦门 | 鼓浪屿、福建土楼（永定高北土楼群） | lp |
| 黄山 | 黄山风景区 | ta+viator |
| 拉萨 | 布达拉宫 | ta+viator |
| 香港 | 太平山顶 | ta（TA 全国 #2；大陆行程暂不可达，仅备骨架） |

## 运行

```bash
python -m app.jobs.import_intl_picks --dry-run   # 先看 insert/merge 分布
python -m app.jobs.import_intl_picks             # 落库（幂等可重跑）
```

## 后续

- 回源链自动补全坐标/时长/票价（quota 日配额内消化）；
- curated 项回源核实后即转正，回源失败 = 该点国际榜知名度存疑、自然淘汰；
- 榜单刷新：TA/LP 年更，重跑作业幂等无副作用；后续可加 Viator/
  China Highlights 全量页（当前仅摘要级）。
