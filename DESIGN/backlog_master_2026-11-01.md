# chinatrip POI 数据 — 全需求合并清单（master backlog）

更新:2026-11-01 午 · 分支 feat/v24-trip-center-uat
合并来源:backlog.md(10-31 收口版) + 11-01 别名/地图引擎战报 + 星级饭店拍板(POIS_DATASOURCE.md §3.2 行12) + 11-01 盘库实测新发现
本文件为**唯一权威清单**,吸收并取代 backlog_2026-10-31.md 的 Backlog 段;其「已完成」段并入下方存档。

---

## 一张表看全(按优先级)

| # | 级 | 事项 | 关键数字/证据 | Owner | 状态 |
|---|----|------|--------------|-------|------|
| 1 | **P0** | 错城行修复 | 全库扫描=3 行(同根因:amap 回源同名 POI 错城,坐标对 city 错);已修复落库✅ city:=前缀城,复扫 0 | 数据侧(我) | **已完成 11-01** |
| 2 | **P0** | 长白山 city 回填 | 已完成落库✅ 晚间探针:regeo 三家仍死(baidu 服务禁用/amap 空/tencent 配额尽),但 baidu place/search 可用——search 备路命中「长白山风景区」raw=延边朝鲜族自治州 → poi_city.canonical_city 归一→city='延边'(库内既有 25 行同口径,别名齐:长白山风景区/天池景区/白头山)。至此空 city 债务清零:非归档 0 行,余 8 行全为有意归档系列。脚本=tmp_xian/fill_changbaishan_v2.py | 数据侧(我) | **已完成 11-01** |
| 3 | **P1** | 别名回填接力(name_aliases) | 累计 +1003/12863=9.2%;轮 4 在飞;别名↑=库命中↑=出门烧配额↓ | 别名会话(主线) | 进行中 |
| 4 | **P1** | 4A 坐标定向加速 | 4611/4612 无坐标;配额现实(高德 search 166/日、百度 100-430/日、腾讯 200/日)下正确动作=**「城市热度×tier」优先级队列**喂夜间链/enrich 链,勿批量 geocode | 数据侧(我) | 待开工 |
| 5 | **P1** | 评分定向富化 | 全库 rating 覆盖仅 14.4%;refresh_pois --match --city 西安 先行(兵马俑 5a_296 有坐标可即提);排序当前只能吃 tier 加成 | 数据侧(我) | 待开工,先读接口 |
| 6 | **P1** | 州级城市名归一 | 阿坝藏族羌族自治州等全名 vs KNOWN_CITIES 注册名 | 并行会话 | normalize_poi_city_names.py 在飞 |
| 7 | **P1** | 西安钟楼行建/修+小杂项 | 已完成落库✅ 西安钟楼 manual 行(manual_xian_zhonglou,dur=60,rain=partial,aliases=[钟楼/西安钟鼓楼],GCJ02 108.943/34.261,hours 留回源链);回民街 intl_0077 rain=partial;北京钟楼行归位北京(dur 留 None,代码 90 兕底) | 数据侧(我) | **已完成 11-01** |
| 8 | **P1** | 泛名 unesco 8 行拍板 | 丝绸之路/大运河等跨省系列行;现维持归档(city=''),或拆具体遗产点(75 个具体点已可达) | **blocker=用户拍板** | 挂起 |
| 9 | **P2** | 三 CSV 后续富化 | guobao8 811 / histvillage 484 / relicpark 59 **已落库**(并行会话 P2 导入已收口),坐标/评分全缺 → 并入 #4 优先级队列 | 并入 #4 | 已导入 ✓ |
| 10 | **P2** | 小红书榜单导入拍板 | xlsx 26 行,证据级 B/C,场馆/展品粒度 | blocker=用户 | 挂起 |
| 11 | **P2** | 星级饭店打标 | POIS_DATASOURCE.md §3.2 行12 已固化设计:tags=["star_5"/"star_4"]+tags_source 记体系(对齐 michelin_Nstar 先例);不建骨架行只标库内 hotel(3,753 行全无等级);推荐官方名单 CSV 审阅包轨 | 数据侧 | **用户拍板暂不启动** |
| 12 | **P3** | 餐厅推荐质量 | 新证据:**全库餐厅 0 评分**(上海 585/585、北京 543/543、广州/成都/杭州…全部)——最低评分/名店加权前须先有评分数据;短期可品牌白名单兜底「海底捞当西安推荐」类 | 观察 | 挂起 |
| 13 | **P3** | 新骨架行 address/intro/EN 富化 | nightly 链自动,无需人工 | 自动 | 运行中 |
| 14 | **P3** | 选点毛刺观察 | 秦始皇陵(tier4)已排后,兵马俑博物馆(tier3,2.2km)未跟排 day1——低频,后续实例再验证 | 观察 | 挂起 |

## 待用户侧(解锁他人主线)

| # | 事项 | 解锁什么 |
|---|------|---------|
| U1 | 百度/腾讯个人开发者认证 | enrich_baidu_map 续跑(今日 +303 后 302 熔断,断点无损)、enrich_tencent_map(121 行待解锁);认证后一条命令续 |
| U2 | 高德升企业档 | enrich_amap_detail + business_area 启用 |

---

## 已完成存档(勿重做)

- **10-31 收口 8 件**(backlog.md):空 city 回填 86→1、CSV 统一导入 +4872、跨省系列归档 8 行、05/09 名单对账 missing=0、澳门归一、庐山错配修正、兵马俑三叫法可检索、门禁全绿。
- **11-01 上午**:午餐 ±30 落地(cda5585 链)、PR2 插入式排时(4f3f3f4)、PR3 时间戳守卫(f19827a)、兜底 v2.2(6cbdab8)、城市解析器工具链(10fd0d3:poi_city+city_index.json+GB/T 2260 源)。
- **11-01 战报收口**:公园池清洗(普通公园软删 106 组保留)、住宿归口(3,753 行 hotel 全 active)、场馆改 entertainment(11 项)、四处代码防线(classify 守卫/normalize 映射/导入强制 hotel/搬移强制 hotel)、测试与 ruff 全绿、星级饭店设计入 §3.2 行12。
- **11-01 并行会话**:P2 三 CSV(03/06/07)已导入落库、别名 +1003(轮 4 在飞)、map_provider 分池引擎(search=amap→tencent→baidu,regeo=baidu→amap→tencent,latch 降级,1555 测试绿)、地址回填单日 89.2%。
- **11-01 盘库确认**:小雁塔补录生效(4A 唯一有坐标行)、西安池 68 行、rating 覆盖大头在 5a/amap/unesce 源。

## 本日盘库新发现(已并入上表)

1. 错城行 2 例实锤(#1)——ct_北京_165 的 aliases=[北京钟楼,钟鼓楼] 却挂 city=西安,坐标在北京;污染西安池距离闸。
2. fill_all 盲跑坑(#2)——backlog 原指令写于系列行归档前,直接执行会解封 8 行泛名。
3. 餐厅零评分(#12)——评分加权路线的数据前提不存在,先有数据再谈加权。
4. chinatravel 源 4222/5902 无坐标——多为 source 升级 amap 后的 origin 行,活跃度待核,暂不单列(疑与 amap 行重叠)。
5. intl 19/20、scenic 240、show 42 无坐标——并入 #4 队列一起排。

## 运维备忘(沿用+新增)

- 数据操作即生效,无需重启;批量 UPDATE 必逐条 commit;pois.city NOT NULL(空=空串)。
- **新增坑**:①空 city 现含 8 行有意归档系列——任何「只碰空 city」的回填脚本都必须排除 source='unesco',或按 id 白名单跑;②跑库脚本必须 cwd=D:\CHINATRIP\CHINATRIP CODES(get_settings 的 .env 相对路径,从工作区 cwd 启动会拿到空 key 链);③SQLAlchemy text() 里 ":param::jsonb" 不转换绑定,用 "CAST(:param AS jsonb)"。
- 配额矩阵(实测):高德 search 166/日、基础 LBS 15万/月;百度 search 100-430/日、regeo 宽裕;腾讯 search 200/日。POIS 表唯一真相、读路径零图商。
- 可复跑脚本存工作区 tmp_xian/(全幂等);archive_series_unesco.py 勿重跑。
