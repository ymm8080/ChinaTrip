# 秦岭四宝科学公园 curated 入库单（2026-11-07，已执行）

> 案情：心愿「看熊猫」被跨程 backfill 毒城成都而蒸发；西安库内无熊猫行。引擎宽恕链+别名通道已修，本脚本补数据面。针址 amap geocode 实测（adcode=610124 周至县，level=兴趣点），gcj=(108.323692,34.060743)。

执行时刻 2026-11-07T22:40:16

行：curated:西安:秦岭四宝科学公园｜aliases=['西安熊猫馆', '秦岭大熊猫研究中心', '秦岭四宝']｜zoo｜240min｜票30｜bvt any｜rain_ok partial｜hours 旺季(03-01至11-30)周一至周日09:00-17:00

### 回滚语句

```sql
DELETE FROM pois WHERE source='curated' AND source_poi_id='curated:西安:秦岭四宝科学公园';
```
