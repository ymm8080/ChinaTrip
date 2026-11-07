# 金沙博物馆退役处置单（2026-11-07，已执行）

用户指令：成都金沙博物馆设为 inactive。退役=软删让位（status='inactive'），可逆。

处置时刻 2026-11-07T04:26:04Z。

## 退役行

| 城市 | 名 | id | source | source_poi_id | 原 status |
|---|---|---|---|---|---|
| 成都 | 成都金沙遗址博物馆 | `85ecd165-107d-411c-9b8b-5b1e6eda1096` | museum1 | `m1_2ba589381932` | active |

## 未动行（同查同现，仅供复核）

| 名 | id | source | status | 说明 |
|---|---|---|---|---|
| 金沙遗址博物馆-遗迹馆 | `652d5dc6-16c9-42d7-98a5-c04e6538f5f6` | chinatravel (`ct_成都_206`) | active | 子馆行，坐标偏东~0.9km（金牛区同友路地址），错针形态嫌疑；主馆退役后其为同馆唯一 active 行，可能被引擎接位 |
| 金沙大酒店(成都建设路店) | `bd480667-efc8-41a1-9305-0b01d17f5826` | chinatravel | active | 酒店，异实体，不相关 |

## 回滚语句

```sql
UPDATE pois SET status='active', updated_at=NOW() WHERE id='85ecd165-107d-411c-9b8b-5b1e6eda1096' AND status='inactive';
```
