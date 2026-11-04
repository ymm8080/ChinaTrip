# 4A / guobao8 / scenic 未审入库批次质检报告（2026-11-03，只读扫描 + 4 处小修）

> 背景：三批名单（4a 4,328 / guobao8 649 / scenic 240）由并行会话 2026-11-02 灌入，
> 超出原「未审不进库」闸。本轮只读质检 + 4 处小修，红色/住宿词扫描与 2026-11-03
> 红色出池两轮口径一致。

## 4A（4,328 行）
- 去重：in-source 同城同名 0；与 5a/scenic 跨级同名 0 ✅
- 红色词表命中 0（已被 11-03 出池两轮覆盖）✅
- category：nature 3,514 / NULL 200 / museum 184 / attraction 182 / park 142 /
  theme_park 104 / hotel 2（修后 0）。nature 占 81% 系名称带 景区/风景名胜区
  标记按 classify 语义归 nature，非缺陷
- 修正 2：大连棒棰岛宾馆景区、浮来青旅游度假区 category hotel→attraction
  （真 4A 景区，上游 type 误标）
- 遗留：37 行无坐标（归并行会话 T2 坐标长尾）；200 行 NULL 分类
  （宁缺毋滥口径，enrich 不强判）

## guobao8（649 行：active 648 + duplicate 1）
- 去重 0、红色 0 ✅
- 修正 2：横道河子机务公寓旧址 category hotel→historic（铁路机务公寓**旧址**，
  国保建筑非住宿）；花洲书院 status duplicate→inactive（并行会话去重标记
  非规范值，收敛为标准软删）

## scenic（240 行）
- 去重 0、红色 0、住宿词 0 ✅ 全绿

## 结论
三批整体干净；未审入库的风险面（红色混入/重复/住宿误标）实测仅 4 处且已修。
4A 若需更深质检（名称与高德真值比对/等级真实性核验），需回源配额，另立项。

## 补记（同日）：relicpark/名村"缺口"证伪 + duplicate 状态全表规范化

- 65 行 relicpark / 488 行 histvillage 名单的编号已耗尽（max seq 65/488），看似缺的
  7+4 行实为**跨源重名去重删副本**：屈家岭/元中都/盘龙城/牛河梁/长沙铜官窑/铜绿山
  6 行在 4a、秦始皇陵 1 行并入博物院行、深澳/芹川/茆坪/大岭 4 行在 chinatravel/amap。
  §3.2 #2/#6 状态改为去重收口，无需补灌。
- `status='duplicate'` 为非规范值且全库无代码引用（grep 证空）：全表 77 行手工标记
  残留统一收敛为 `inactive`（语义等价、可回灌，状态词表收敛为 active/inactive 两值）。
