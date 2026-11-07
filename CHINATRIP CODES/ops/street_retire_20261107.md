# 街道行退役处置单（2026-11-07，已执行）

> 用户拍板：街 + 街上有站点 → 留站点、街行退役。v2 判定：站点「在街上」= address/name 提及街名核（3-12 字以街|巷|坊结尾子串），距离仅 5km 封顶（>1.5km 标旗）；退役目标剔场馆类别与镇/村/景区尾；成员剔街名行（街不退役街）。回民街为点名件。退役=status='inactive' 软删+hours_updated_at 冷却（防 refresh 换键复活）。快照表 pois_street_sweep_bak_20261107 + CSV streets_retired_backup_2026-11-07.csv。

处置时刻 2026-11-07T14:37:52；街道候选 317 行，退役 13 行，保留（无在街站点）304 行。

退役分城：

| 城市 | 退役数 |
|---|---|
| 北京 | 2 |
| 苏州 | 2 |
| 贵阳 | 1 |
| 南京 | 1 |
| 三明 | 1 |
| 拉萨 | 1 |
| 扬州 | 1 |
| 成都 | 1 |
| 西安 | 1 |
| 重庆 | 1 |
| 广州 | 1 |

## 退役清单（含在街站点证据）

| 城市 | 街道行 | source | 在街站点（近→远，km，经名/经址） |
|---|---|---|---|
| 贵阳 | 贵州省贵阳市花溪区青岩古镇南北明清街旅游休闲街区 | street | 花溪区青岩古镇景区(0.00,addr:明清街) |
| 南京 | 夫子庙步行街 | street | 外秦淮河画舫(0.36,addr:步行街) |
| 三明 | 福建省三明市泰宁县尚书街旅游休闲街区 | street | 泰宁县博物馆(0.02,addr:尚书街) |
| 拉萨 | 西藏自治区拉萨市城关区八廓街 | street | 城关区大昭寺景区(0.33,addr:自治区拉萨市城关区八廓街)；吞达村(0.48,addr:自治区拉萨市城关区八廓街) |
| 扬州 | 江苏省扬州市广陵区东关街 | street | 个园(0.82,addr:江苏省扬州市广陵区东关街) |
| 成都 | 锦里古街 | amap | 武侯祠·锦里(0.29,addr:锦里古街)；刘湘墓(0.31,addr:锦里古街) |
| 西安 | 回民街 | lonelyplanet | 西安钟楼(1.23,addr:回民街) |
| 重庆 | 磁器口街区 | street | 磁器口转运楼(0.24,addr:磁器口街)；宝轮寺(0.53,addr:磁器口街) |
| 广州 | 永庆坊 | amap | 荔枝湾涌(0.70,addr:永庆坊)；广州荔枝湾游船(0.75,addr:永庆坊) |
| 北京 | 老北京风情街 | chinatravel | 天安门广场(1.33,addr:老北京风情街) |
| 苏州 | 山塘街 | chinatravel | 山塘昆曲馆(1.22,addr:山塘街)；苏州市七里山塘景区(1.22,addr:山塘街) |
| 苏州 | 观前街 | amap | 城隍庙(0.02,addr:观前街)；苏州山塘江南织造漫心府(0.70,addr:观前街) |
| 北京 | 前门大街 | amap | 纪晓岚故居(0.98,addr:前门大街) |

## 距离标旗（1.5-5km，名/址提及但针远——只标旗不退役）

| 城市 | 街道行 | 站点 | 距离km |
|---|---|---|---|
| 杭州 | 大兜路历史文化街区 | 宝石流霞 | 4.63 |
| 杭州 | 大兜路历史文化街区 | 岳飞墓 | 4.76 |
| 北京 | 长安街 | 国家大剧院 | 3.02 |
| 北京 | 长安街 | 中国国家博物馆 | 2.50 |
| 北京 | 长安街 | 人民大会堂 | 2.39 |
| 北京 | 长安街 | 中国钱币博物馆 | 2.73 |
| 杭州 | 清河坊历史文化街区 | 宝石流霞 | 2.70 |
| 杭州 | 清河坊历史文化街区 | 云松书舍 | 3.40 |
| 杭州 | 清河坊历史文化街区 | 岳飞墓 | 2.40 |
| 杭州 | 湖滨路步行街 | 香积寺 | 4.53 |
| 广州 | 沙面街文化站 | 沙面堂 | 1.59 |
| 杭州 | 北山街历史文化街区 | 黄龙洞景区 | 4.73 |
| 杭州 | 北山街历史文化街区 | 宝石流霞 | 4.31 |
| 杭州 | 北山街历史文化街区 | 双峰插云 | 3.44 |
| 杭州 | 北山街历史文化街区 | 云松书舍 | 3.49 |
| 杭州 | 北山街历史文化街区 | 岳飞墓 | 4.31 |
| 苏州 | 山塘街 | 虎丘山风景名胜区 | 3.56 |
| 北京 | 东交民巷 | 中国钱币博物馆 | 2.55 |

### 回滚语句（逐行）

```sql
UPDATE pois SET status='active', updated_at=NOW() WHERE id='131136b7-4335-4347-b663-409982155656' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='131136b7-4335-4347-b663-409982155656' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='2b85a1a3-4f37-4b72-9e0a-d3d7c4f05de8' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='2b85a1a3-4f37-4b72-9e0a-d3d7c4f05de8' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='31953f79-5aef-4698-977d-b4090a7ae611' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='31953f79-5aef-4698-977d-b4090a7ae611' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='3cb546d5-891d-46fc-a2ce-64524bff7305' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='3cb546d5-891d-46fc-a2ce-64524bff7305' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='3f918380-dae0-4b53-afa5-6b7eea9da48c' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='3f918380-dae0-4b53-afa5-6b7eea9da48c' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='8dfd7dc1-022c-4998-b55a-95c765823bb7' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='8dfd7dc1-022c-4998-b55a-95c765823bb7' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='964743f1-13c9-4bf5-9271-a6326d7735fe' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='964743f1-13c9-4bf5-9271-a6326d7735fe' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='af9bc78c-d253-499e-84e4-44626d80271f' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='af9bc78c-d253-499e-84e4-44626d80271f' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='c1ac5ade-8ab8-4398-8daa-9161f86345ed' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='c1ac5ade-8ab8-4398-8daa-9161f86345ed' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='c20231d3-1ee4-4bb4-95f8-9add49989daf' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='c20231d3-1ee4-4bb4-95f8-9add49989daf' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='d98e007e-d1cd-4a60-a880-b230fd2c6c8d' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='d98e007e-d1cd-4a60-a880-b230fd2c6c8d' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='ec7aab8f-6df7-4a44-b3b7-6e4badfe3339' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='ec7aab8f-6df7-4a44-b3b7-6e4badfe3339' AND b.status<>'active');
UPDATE pois SET status='active', updated_at=NOW() WHERE id='fd1dec76-8ef6-47e3-a538-786df862d0a9' AND NOT EXISTS (SELECT 1 FROM pois_street_sweep_bak_20261107 b WHERE b.id='fd1dec76-8ef6-47e3-a538-786df862d0a9' AND b.status<>'active');
```
