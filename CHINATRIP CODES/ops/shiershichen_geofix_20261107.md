# 十二时辰坏针修复单（2026-11-07，已执行）

> 案情：show 源行整条地理编码落在长安区政府（韦曲），真身在雁塔区曼蒂广场。依据 amap place/around POI B0IA1HURD6 + geocode 曼蒂广场 + regeo 标准地址交叉定稿。守卫：旧地址含「长安区人民政府」∧ active。备份表 pois_shiershichen_geofix_bak_20261107 + JSON pois_shiershichen_geofix_backup_20261107.json。

执行时刻 2026-11-07T16:04:21

新值：address=陕西省西安市雁塔区大雁塔街道曼蒂广场；district=雁塔区；gcj=(108.966004,34.21198)；wgs=(108.961291,34.213544)

### 回滚语句

```sql
UPDATE pois SET address=(select address from pois_shiershichen_geofix_bak_20261107 where id='11bde382-5242-46fe-b9a2-c59b21b87cb6'), address_en=(select address_en from pois_shiershichen_geofix_bak_20261107 where id='11bde382-5242-46fe-b9a2-c59b21b87cb6'), district=(select district from pois_shiershichen_geofix_bak_20261107 where id='11bde382-5242-46fe-b9a2-c59b21b87cb6'), location=(select location from pois_shiershichen_geofix_bak_20261107 where id='11bde382-5242-46fe-b9a2-c59b21b87cb6'), wgs84_location=(select wgs84_location from pois_shiershichen_geofix_bak_20261107 where id='11bde382-5242-46fe-b9a2-c59b21b87cb6'), updated_at=NOW() WHERE id='11bde382-5242-46fe-b9a2-c59b21b87cb6';
```
