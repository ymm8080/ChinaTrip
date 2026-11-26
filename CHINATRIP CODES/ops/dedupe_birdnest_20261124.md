# 鸟巢两行 DEDUP 台账（2026-11-24）

- keeper：`d1da799a-e982-46ae-a228-1b20082a06eb` amap「鸟巢(国家体育场)」→ 继续 active
- loser：`11662ce5-a407-4262-9fa3-9deafbf128f0` baidu「国家体育场·鸟巢」→ status='inactive'
- 依据：源优先级 amap>baidu（S3 先例）、hours 只信高德/携程回源链、下游引用指向 amap 行。
- 用户口径：幸存行必须含两行全部信息；全 78 列逐列处置如下（只列非默认动作）。
- 引用重指向：itinerary_items=0，trip_items=0。
- 快照表：`pois_birdnest_dedup_bak_20261124`（两行全字段）；CSV 台账：`pois_birdnest_dedup_2026-11-24.csv`。

## 逐列处置

| 列 | 动作 | keeper 原值 | 退役行原值 | 说明 |
| --- | --- | --- | --- | --- |
| `phone` | fill |  | 4006002008 | keeper 空 → 取退役行 |
| `tags` | fill |  | ["intl", "layla"] | keeper 空 → 取退役行 |
| `tags_source` | fill |  | layla | keeper 空 → 取退役行 |
| `intro` | concat | 鸟巢即国家体育场，位于北京奥林匹克公园，因独特的鸟巢状钢结构造型得名，是2008年北京奥运会主体育场，也举办了2022年冬奥会开闭幕式，为北 | 国家体育场因独特钢结构外形被称为“鸟巢”，是2008年北京奥运会的主体育场，位于北京奥林匹克公园，现已成为北京地标性建筑和热门旅游景点。 | 两段事实都留在 keeper |
| `intro_source` | fill |  | llm | keeper 空 → 取退役行 |
| `photos` | fill |  | [{"url": "https://p1-q.mafengwo.net/s11/M00/C1/9F/wKgBEFt9JCaAdKC7ABr1 | keeper 空 → 取退役行 |
| `photos_source` | fill |  | mafengwo | keeper 空 → 取退役行 |
| `name_aliases` | fill |  | ["National Stadium", "北京国家体育场"] | keeper 空 → 取退役行 |
| `intro_en` | concat | The Bird's Nest is the National Stadium, located in the Beijing Olympi | The National Stadium, nicknamed the 'Bird's Nest' for its distinctive  | 两段事实都留在 keeper |
| `address_en` | prefer_longer | No. 1 National Stadium South Road, Olympic Park | No. 1 National Stadium South Road, Chaoyang District, Beijing | 退役行更详（61>47） |
| `ta_rating` | keep_scalar | 4.2 | 3.8 | 4.2 |

## name_aliases 最终值（两行名字/英文名变体 + 通行短名）

```json
[
  "Bird's Nest (National Stadium)",
  "国家体育场·鸟巢",
  "Beijing National Stadium",
  "National Stadium",
  "北京国家体育场",
  "鸟巢",
  "国家体育场"
]
```

## 回滚

```bash
.venv/Scripts/python.exe ops/dedupe_birdnest_20261124.py --rollback
```

或直接 SQL（从快照表整行恢复两行）：

```sql
INSERT INTO pois SELECT * FROM pois_birdnest_dedup_bak_20261124 WHERE id IN ('d1da799a-e982-46ae-a228-1b20082a06eb','11662ce5-a407-4262-9fa3-9deafbf128f0')
ON CONFLICT (id) DO UPDATE SET source=EXCLUDED.source, source_poi_id=EXCLUDED.source_poi_id, city=EXCLUDED.city, name_zh=EXCLUDED.name_zh, name_en=EXCLUDED.name_en, category=EXCLUDED.category, status=EXCLUDED.status, location=EXCLUDED.location, wgs84_location=EXCLUDED.wgs84_location, updated_at=EXCLUDED.updated_at, address=EXCLUDED.address, opening_hours=EXCLUDED.opening_hours, hours_source=EXCLUDED.hours_source, hours_updated_at=EXCLUDED.hours_updated_at, phone=EXCLUDED.phone, website=EXCLUDED.website, rating=EXCLUDED.rating, rating_source=EXCLUDED.rating_source, tags=EXCLUDED.tags, tags_source=EXCLUDED.tags_source, intro=EXCLUDED.intro, intro_source=EXCLUDED.intro_source, photos=EXCLUDED.photos, photos_source=EXCLUDED.photos_source, best_visit_time=EXCLUDED.best_visit_time, best_visit_time_source=EXCLUDED.best_visit_time_source, suggested_duration_min=EXCLUDED.suggested_duration_min, origin=EXCLUDED.origin, rating_count=EXCLUDED.rating_count, review_tags=EXCLUDED.review_tags, review_tags_source=EXCLUDED.review_tags_source, ticket_price_min=EXCLUDED.ticket_price_min, ticket_price_max=EXCLUDED.ticket_price_max, ticket_source=EXCLUDED.ticket_source, district=EXCLUDED.district, business_area=EXCLUDED.business_area, indoor=EXCLUDED.indoor, rain_ok=EXCLUDED.rain_ok, name_aliases=EXCLUDED.name_aliases, duration_source=EXCLUDED.duration_source, review_summary=EXCLUDED.review_summary, review_summary_source=EXCLUDED.review_summary_source, reservation_required=EXCLUDED.reservation_required, reservation_advance_days=EXCLUDED.reservation_advance_days, booking_url=EXCLUDED.booking_url, intro_en=EXCLUDED.intro_en, address_en=EXCLUDED.address_en, review_tags_en=EXCLUDED.review_tags_en, review_summary_en=EXCLUDED.review_summary_en, opening_hours_en=EXCLUDED.opening_hours_en, photos_fetched_at=EXCLUDED.photos_fetched_at, photos_fetch_fail=EXCLUDED.photos_fetch_fail, user_family=EXCLUDED.user_family, user_groups=EXCLUDED.user_groups, ta_location_id=EXCLUDED.ta_location_id, ta_geo_id=EXCLUDED.ta_geo_id, ta_fetched_at=EXCLUDED.ta_fetched_at, ta_status=EXCLUDED.ta_status, ta_url=EXCLUDED.ta_url, ta_rating=EXCLUDED.ta_rating, ta_opening_hours=EXCLUDED.ta_opening_hours, ta_suggested_duration_min=EXCLUDED.ta_suggested_duration_min, ta_intro_en=EXCLUDED.ta_intro_en, access_mode=EXCLUDED.access_mode, access_minutes=EXCLUDED.access_minutes, access_gateway=EXCLUDED.access_gateway, access_gateway_minutes=EXCLUDED.access_gateway_minutes, access_note=EXCLUDED.access_note, access_note_en=EXCLUDED.access_note_en, access_source=EXCLUDED.access_source, access_updated_at=EXCLUDED.access_updated_at, access_boarding=EXCLUDED.access_boarding, access_boarding_lon=EXCLUDED.access_boarding_lon, access_boarding_lat=EXCLUDED.access_boarding_lat, access_service_minutes=EXCLUDED.access_service_minutes, access_wait_minutes=EXCLUDED.access_wait_minutes, access_last_mile_minutes=EXCLUDED.access_last_mile_minutes;
```
