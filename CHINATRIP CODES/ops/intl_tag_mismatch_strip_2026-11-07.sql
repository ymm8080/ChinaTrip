-- intl 标签错配剥离（2026-11-07，配套 ops/intl_tag_mismatch_backup_2026-11-07.txt）
-- 根因：import_intl_platforms 双向包含匹配把街区荐点（宽窄巷子/春熙路/
-- 锦里/田子坊/新天地/南京路步行街/昙华林/王府井/迪士尼/上海中心/钟楼）
-- 错挂到分支名嵌地标的酒店/体验门店上。733c596 只清了磁器口；本次全库
-- 复扫 19 行剥标（含 amap/baidu 源——首查被 source='chinatravel' 滤掉），
-- 匹配闸（_STAY_FOOD 扩词+尾缀「店」+尾括号含「店」）同拍收口防重跑回污。
-- 保留不动：李子坝轻轨站(curated 正经荐点)、失重餐厅(环球中心店)/红鼎宴
-- (_CURATED_PICKS 有意收录的餐厅荐点, import_intl_picks.py L342/L353)。
UPDATE pois
SET tags = tags - 'intl' - 'sygic' - 'layla' - 'kkday' - 'xiaohongshu' - 'mindtrip',
    tags_source = CASE
        WHEN tags_source IN ('intl','sygic','layla','kkday','xiaohongshu','mindtrip')
        THEN NULL ELSE tags_source END
WHERE id IN (
  'dbba1c59-a1d7-4345-baa8-773bbbdab275',  -- 上海 丽呈别院(新天地旅游度假区店) hotel
  'fc5f290d-0cdd-4a74-a179-82783f0950dc',  -- 上海 独角兽星空艺术馆 田子坊旗舰店
  '881079cc-00d0-4116-94e3-adde929f8b0b',  -- 上海 锦江都城(新天地田子坊店) hotel
  '1071158f-727f-4f89-820b-28cbc72f411c',  -- 上海 飞跃上海(南京路来福士店)
  '3a20d9ae-1c11-406c-b459-49a071eb1131',  -- 成都 悬空飞越剧场(春熙路茂业百货店)
  '7fb4a3b3-4c8f-4f74-b6b5-b3e4f19ebade',  -- 成都 易宁阁宽窄别院(宽窄巷子地铁站店) hotel
  'b455767f-e741-4924-99d4-09fac736b398',  -- 成都 梵隐·花间庭院villa朴墅(春熙路太古里店) hotel
  '24302d8c-e855-4190-8cc8-e5769d396255',  -- 成都 汤悦温泉(春熙路)店
  'a7e6f1f3-5890-4d46-8e58-e4b4978bf6fd',  -- 成都 沐云紫汉服体验写真(武侯锦里店)
  '5a9a3270-6076-4738-947f-67d60caf740a',  -- 成都 西金中心·云曦天际S公馆 hotel
  'a86c61cc-64fb-4834-aecd-3d8b318939f2',  -- 成都 长藤鬼校(春熙路IFS店)
  '6588ae82-b714-4cb7-94d8-96579f6ad67f',  -- 武汉 隐居伴山(黄鹤楼昙华林店) hotel
  '257cbf7b-4c6c-4e44-9205-97315d154604',  -- 上海 天时632艺术空间(上海中心大厦店)
  '905694cb-96a8-4433-aa39-1d2c81f073e4',  -- 上海 梦幻世界(上海迪士尼乐园店)
  '846c0ff8-0183-4d01-80b5-f8f7b80326c4',  -- 北京 梵高星空艺术馆（王府井旗舰店）
  'e9c52b1e-2a6c-4656-9761-142e47a642c1',  -- 成都 梵高星空艺术馆（成都春熙路旗舰店）
  '5274f25f-9e09-4733-a1bf-202583d3d10f',  -- 成都 飞跃四川(春熙路茂业百货店) amap源
  'aac6e134-459d-45b0-b9ad-943623b8b9de',  -- 成都 成都失恋博物馆(春熙路旗舰店)
  '44202eb5-1af6-4efa-9857-7544176b34aa'   -- 西安 崇辉澄城水盆羊肉(钟楼西一路总店) 733c596 前遗留
);
