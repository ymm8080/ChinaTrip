-- 人工定值评分台账（manual overrides）
--
-- 为什么不只在库里改：rating 是回源链维护的列，改库不进仓库，换环境/重建库就丢。
-- 本文件是这些人工定值的唯一可重放记录；每加一条，附上日期、口径来源与旁证。
--
-- 语义约定（与 ops/set_poi_rating.py 一致）：
--   rating        = 人工定值
--   rating_source = 'manual'
-- 打 manual 后两条回源链都不再覆盖本行：
--   app/jobs/enrich_ctrip_detail.py  只在 rating IS NULL 或 rating_source='amap' 时写
--   app/jobs/refresh_pois.py         只写图商回值（不读 manual 行）
-- 因此重放本文件是幂等的：重复执行只是把同一值再写一次。
--
-- 重放：psql -h localhost -U chinatrip -d chinatrip -f ops/poi_rating_overrides.sql
-- 或热改单条：python ops/set_poi_rating.py <城市> <精确名> <分值> --note "..."

BEGIN;

-- 2026-11-22 用户令：「慕田峪评分设为 4.9」。
-- 行：source=amap / ct_北京_8（原 rating NULL，选点层「同档名声分」= 0，
--     排序中被故宫/颐和园压住，导致整天被顶掉）。
-- 旁证：同城 5A 行「八达岭慕田峪长城旅游区」携程 4.8；索道滑道行 4.8；
--      TripAdvisor 3.8（TA 对国内景区普遍偏低，不作主标尺）。
-- 影响：site_rank 仍为 0（unesco 标已定档），quality 由 0.0 → 4.9，与故宫并列。
UPDATE pois
   SET rating = 4.9,
       rating_source = 'manual',
       updated_at = NOW()
 WHERE city = '北京'
   AND name_zh = '慕田峪长城'
   AND status = 'active';

COMMIT;

-- 核验：应返回 rating=4.9 / rating_source=manual 的一行
-- SELECT source, name_zh, rating, rating_source
--   FROM pois WHERE city='北京' AND name_zh='慕田峪长城' AND status='active';
