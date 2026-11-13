"""Trip-center three-state items (design v2.4 §5/§4).

One table absorbs every write path — manual form, chat dialog, paste box,
agent recommendation (iron rule 0: single source of truth). An item walks
Wishlist -> Scheduled -> Booked; walking back to wishlist unschedules it.
Pure logic only (store + transition rules): no HTTP imports, so the state
machine is unit-testable directly. Storage is a plain dict;
``state_persist.PersistentTripItemService`` subclasses it with SQLite
write-through so items survive restarts (itinerary-store pattern).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)

STATUS_WISHLIST = "wishlist"
STATUS_SCHEDULED = "scheduled"
STATUS_BOOKED = "booked"
STATUS_UNWANTED = "unwanted"
STATUSES = frozenset(
    {STATUS_WISHLIST, STATUS_SCHEDULED, STATUS_BOOKED, STATUS_UNWANTED}
)

SOURCES = frozenset(
    {"manual", "chat", "paste", "agent_recommend", "plan_delete", "plan"}
)

# Statuses that occupy a (day, position) slot on the timeline.
_TIMELINE_STATUSES = frozenset({STATUS_SCHEDULED, STATUS_BOOKED})


def _as_int(value: object, default: int = 0) -> int:
    """排序键的宽松数值归一：None/缺键/脏字符串一律落 default。

    payload 是读权威，迁移与旁路脚本写进来的 day/position 可能是字符串
    （int 与 str 比较 = TypeError = 看板整块 500）。
    """
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    """同 _as_int：position 的宽松数值归一。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def strip_scheduled_note(note: str | None) -> str:
    """剥掉 note 的「已安排」尾段（带前缀/裸两种形态，中英分隔符）。

    2026-10-31（看熊猫案）：scheduled→wishlist（删行程释放/看板自愈/
    重排回退）后 note 不再声称已安排——保留来源前缀（如「来自聊天」）；
    _sync_wish_rows 重新落排时按新行程重写。裸形态（无来源前缀，如
    「已安排：X（第1天 09:00）」）剥成空串；无尾段原样返回。
    """
    raw = str(note or "")
    for sep in ("｜已安排：", " | Scheduled:"):
        raw = raw.split(sep)[0]
    if raw.startswith(("已安排：", "Scheduled:")):
        raw = ""
    return raw.strip()


class InvalidSourceError(ValueError):
    """Create payload named a source outside the four allowed origins."""


class NotFoundError(KeyError):
    """No item with that id."""


class InvalidTransitionError(ValueError):
    """Requested change violates the three-state machine."""


def _iso_now(now: datetime | None) -> str:
    return (now if now is not None else datetime.now(timezone.utc)).isoformat()


def _norm(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().casefold() or None


# 2026-10-28 心愿单去重模糊层：同一意愿的不同写法（看变脸 /
# 变脸表演（川剧）/ 川剧变脸）必须收成一张卡。键 = 剥括号注 + 意图动词
# 前缀 + 通用活动后缀；匹配 = 键相等 或 双向包含（短侧 >= 2 字，POIS
# 数据集同款包含规则）。
_WISH_PAREN_RE = re.compile(r"[（(【\[][^\n（）()【\][]*[）)】\]]")
_WISH_VERB_PREFIX = (
    "想要",
    "想看",
    "想去",
    "想逛",
    "想吃",
    "想喝",
    "想玩",
    "想体验",
    "看看",
    "逛逛",
    "试试",
    "尝尝",
    "参观",
    "游览",
    "打卡",
    "体验",
    "品尝",
    "看",
    "去",
    "吃",
    "喝",
    "逛",
    "游",
    "玩",
)
_WISH_GENERIC_SUFFIX = ("表演", "演出", "体验", "秀", "之旅")


def _wish_key(value: str | None) -> str:
    name = _norm(value)
    if not name:
        return ""
    name = _WISH_PAREN_RE.sub("", name)
    name = re.sub(r"\s+", "", name)
    for _ in range(3):  # 前缀/后缀交替剥，三轮收敛（看看变脸表演→变脸）
        changed = False
        for prefix in _WISH_VERB_PREFIX:
            if name.startswith(prefix) and len(name) > len(prefix):
                name = name[len(prefix) :]
                changed = True
        for suffix in _WISH_GENERIC_SUFFIX:
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                changed = True
        if not changed:
            break
    return name


def _wish_match(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    short, other = (left, right) if len(left) <= len(right) else (right, left)
    return len(short) >= 2 and short in other


class TripItemService:
    """In-memory trip-item store + Wishlist/Scheduled/Booked state machine.

    Invariants enforced after every update:
      * wishlist  -> day/position/booking_id are None
      * scheduled -> day/position set, booking_id None
      * booked    -> day/position/booking_id set
      * unwanted  -> day/position/booking_id are None
    day/position/booking_id are owned by the state machine: values supplied
    for them while the item ends up in wishlist are discarded.
    """

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}

    # --- create / read -------------------------------------------------------

    def create(
        self,
        name: str,
        *,
        source: str,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
        city: str | None = None,
        note: str | None = None,
        poi_id: str | None = None,
        address: str | None = None,
        opening_hours: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Idempotent create: returns the existing row instead of a new one
        when this trip already holds the same poi_id / name+city (an empty
        city matches any). 2026-10-28 user report (multiple 西湖 on the
        global board): a same-name wishlist row from another trip is the
        same wish too — see _find_duplicate for the exact predicate."""
        if source not in SOURCES:
            raise InvalidSourceError(f"invalid_source:{source}")
        duplicate = self._find_duplicate(
            name,
            source=source,
            itinerary_id=itinerary_id,
            city=city,
            poi_id=poi_id,
            owner_device_id=owner_device_id,
        )
        if duplicate is not None:
            # Same wish, richer info: fill ONLY empty fields of the existing
            # row (a deliberate 杭州 never becomes 苏州); the row survives
            # with everything the second submission knew.
            self._enrich_duplicate(
                duplicate,
                name=name,
                note=note,
                city=city,
                poi_id=poi_id,
                address=address,
                opening_hours=opening_hours,
                now=now,
            )
            logger.info(
                "trip_item_deduplicated id=%s name=%s",
                duplicate["id"],
                duplicate["name"],
            )
            return dict(duplicate)
        stamp = _iso_now(now)
        item = {
            "id": uuid4().hex,
            "itinerary_id": itinerary_id,
            # 2026-11-13 数据库事实化：归属设备随行落库（看板按设备读）
            "owner_device_id": owner_device_id,
            "name": name,
            "city": city,
            "note": note,
            "status": STATUS_WISHLIST,
            "source": source,
            "poi_id": poi_id,
            "address": address,
            "opening_hours": opening_hours,
            "day": None,
            "position": None,
            "booking_id": None,
            "created_at": stamp,
            "updated_at": stamp,
        }
        self._items[item["id"]] = item
        logger.info("trip_item_created source=%s", source)
        return dict(item)

    @staticmethod
    def _enrich_duplicate(
        item: dict,
        *,
        name: str | None = None,
        note: str | None,
        city: str | None,
        poi_id: str | None,
        address: str | None,
        opening_hours: str | None,
        now: datetime | None,
    ) -> None:
        """Merge-in place: only fill fields the existing row lacks; record
        a rephrased alias (看变脸 vs 变脸表演（川剧）) in note so a fuzzy
        merge leaves visible trace; bump updated_at when anything changed
        (subclass persistence rides the caller's write-through)."""
        changed = False
        for field, value in (
            ("note", note),
            ("city", city),
            ("poi_id", poi_id),
            ("address", address),
            ("opening_hours", opening_hours),
        ):
            if value and not item.get(field):
                item[field] = value
                changed = True
        alias = (name or "").strip()
        if alias and _norm(alias) != _norm(item.get("name")):
            current = item.get("note") or ""
            if alias not in current:
                merged = f"{current}；别名：{alias}" if current else f"别名：{alias}"
                item["note"] = merged
                changed = True
        if changed:
            item["updated_at"] = _iso_now(now)

    def get(self, item_id: str) -> dict | None:
        item = self._items.get(item_id)
        return dict(item) if item is not None else None

    def list_groups(
        self,
        itinerary_id: str | None = None,
        owner_device_id: str | None = None,
    ) -> dict:
        """Timeline payload (§5): Bookings pinned first, Wishlist stream,
        Scheduled as the third key — each in its documented order.

        2026-11-13（用户拍板「这些应该都是数据库的数据」）：行归属设备
        ——带 owner_device_id 时只回该设备的行；不带（脚本/运维）回全量。
        """
        items = list(self._items.values())
        if owner_device_id is not None:
            # 有归属的按设备隔离；无归属（历史行/脚本建行）仍可见——归属列
            # 是新事实，不能让老数据在升级瞬间集体消失。
            items = [
                i for i in items if i.get("owner_device_id") in (None, owner_device_id)
            ]
        if itinerary_id is not None:
            items = [i for i in items if i.get("itinerary_id") == itinerary_id]

        def timeline_key(item: dict) -> tuple[int, float]:
            # position None 兜底 0.0：库内行可能在状态机外写入（如 SQL
            # 级恢复），裸比较 None vs float 直接 TypeError 把整个
            # list_groups（=每次规划回合的吸收入口）打成 500。
            # day 同款兜底：旧版 H5 迁移/旁路脚本的 payload 可能缺列。
            # 2026-11-13 再补类型归一：迁移/导入入口（import_item）可能把
            # day/position 写成字符串，int 与 str 比较同样 TypeError。
            return (_as_int(item.get("day")), _as_float(item.get("position")))

        def stamp(item: dict, *fields: str) -> str:
            # 2026-11-13 看板 500（KeyError: 'created_at'）：payload 是读
            # 权威，旧版迁移行可能既没有 created_at 也没有 updated_at——
            # 排序键必须容忍缺键，否则整个看板 GET 直接 500。
            for field in fields:
                value = item.get(field)
                if value:
                    return str(value)
            return ""

        return {
            "bookings": sorted(
                (dict(i) for i in items if i.get("status") == STATUS_BOOKED),
                key=timeline_key,
            ),
            "wishlist": sorted(
                (dict(i) for i in items if i.get("status") == STATUS_WISHLIST),
                key=lambda i: stamp(i, "created_at", "updated_at"),
                reverse=True,
            ),
            "scheduled": sorted(
                (dict(i) for i in items if i.get("status") == STATUS_SCHEDULED),
                key=timeline_key,
            ),
            "unwanted": sorted(
                (dict(i) for i in items if i.get("status") == STATUS_UNWANTED),
                key=lambda i: stamp(i, "updated_at", "created_at"),
                reverse=True,
            ),
        }

    # --- update / delete -----------------------------------------------------

    def update(
        self,
        item_id: str,
        *,
        status: str | None = None,
        day: int | None = None,
        position: float | None = None,
        note: str | None = None,
        city: str | None = None,
        booking_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        if status is not None and status not in STATUSES:
            raise InvalidTransitionError(f"unknown_status:{status}")

        current = item["status"]
        target = status if status is not None else current

        if status is not None and status != current:
            self._check_transition(current, target, day=day, booking_id=booking_id)
            if current == STATUS_WISHLIST and target == STATUS_SCHEDULED:
                if position is None:
                    position = self._next_position(item["itinerary_id"], day)
        else:
            # Same-status patch: a day move without explicit position lands
            # at the end of the new day.
            self._check_fields(target, day=day, booking_id=booking_id)
            if (
                target in _TIMELINE_STATUSES
                and day is not None
                and position is None
                and day != item["day"]
            ):
                position = self._next_position(item["itinerary_id"], day)

        item["status"] = target
        if target in (STATUS_WISHLIST, STATUS_UNWANTED):
            item["day"] = None
            item["position"] = None
            item["booking_id"] = None
        else:
            if day is not None:
                item["day"] = day
            if position is not None:
                item["position"] = float(position)
            if booking_id is not None:
                item["booking_id"] = booking_id
            if target == STATUS_SCHEDULED:
                item["booking_id"] = None
        if note is not None:
            item["note"] = note
        if city is not None:
            item["city"] = city
        item["updated_at"] = _iso_now(now)
        return dict(item)

    def link_itinerary(
        self, item_id: str, itinerary_id: str, *, force: bool = False
    ) -> dict | None:
        """补挂/重挂行程归属（2026-10-30 深夜：聊天建行时 plan 未定 →
        itinerary_id=None，行程落定后回挂，行程中心按行程过滤才可见；
        重组行程会换 id，force=True 允许从旧 id 重挂）。只写内存 dict，
        PG 子类通过 _write_through 钩子写穿。"""
        item = self._items.get(item_id)
        if item is None or not itinerary_id:
            return None
        if item.get("itinerary_id") and not force:
            return dict(item)
        if item.get("itinerary_id") == itinerary_id:
            return dict(item)
        item["itinerary_id"] = itinerary_id
        item["updated_at"] = _iso_now(None)
        hook = getattr(self, "_write_through", None)
        if callable(hook):
            hook(item_id)
        return dict(item)

    def delete(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        if item["status"] == STATUS_BOOKED:
            # §5 timeline integrity: un-book before removing.
            raise InvalidTransitionError("booked_not_deletable")
        del self._items[item_id]
        logger.info("trip_item_deleted id=%s", item_id)

    def unbind_itinerary(
        self, item_id: str, *, now: datetime | None = None
    ) -> dict | None:
        """解除行程绑定（2026-11-13 删行程拍板）。

        itinerary_id 是指向 itineraries 的外键列：释放回心愿单的行若仍挂
        被删行程 id，PG 会拿 FK 挡下 DELETE /itineraries/{id}——接口照样
        204、列表读穿透又把它拉回来（删了又复活）。心愿单行不该挂死行程：
        清空 itinerary_id 并写穿（PG 子类落列 + payload）。未绑定/不存在
        幂等返回现状。
        """
        item = self._items.get(item_id)
        if item is None:
            return None
        if not item.get("itinerary_id"):
            return dict(item)
        item["itinerary_id"] = None
        item["updated_at"] = _iso_now(now)
        hook = getattr(self, "_write_through", None)
        if callable(hook):
            hook(item_id)
        return dict(item)

    def release_itinerary(
        self, itinerary_id: str, *, now: datetime | None = None
    ) -> list[dict]:
        """行程被手工删除（2026-10-31 拍板）：名下已排期心愿回到心愿单栏，
        不挂在死行程 id 上——scheduled→wishlist 走状态机（day/position/
        booking_id 清空，note 剥「已安排」尾段），并解除行程绑定（2026-11-13
        用户拍板「删行程时排期部分退回心愿单」：留着死行程 id 会让
        trip_items.itinerary_id 外键挡住行程删除，接口 204 后行程复活）。
        吸收/_sync_wish_rows 仍按名字把心愿行 force 换绑新行程，不靠旧 id
        留痕。booked 行保留真实订单、只摘绑定；wishlist/unwanted 行本就
        在原位。返回被释放的行（PG 子类经 update 写穿落库）。

        2026-11-12 拍板「心愿单只收用户输入」分流：source=plan 的引擎行
        不得落心愿单——死行程时直接删除（2026-11-13 起引擎行不再补源
        重建：已排期只放已排的心愿单），删除留日志；用户来源行
        （chat/manual/paste/agent_recommend）维持回心愿单。"""
        if not itinerary_id:
            return []
        targets = [
            item["id"]
            for item in self._items.values()
            if item["itinerary_id"] == itinerary_id
            and item["status"] == STATUS_SCHEDULED
        ]
        released = []
        for item_id in targets:
            item = self._items.get(item_id) or {}
            if item.get("source") == "plan":
                try:
                    self.delete(item_id)
                except InvalidTransitionError:
                    continue  # booked 行永不到此（status 过滤），保险不炸
                logger.info("trip_item_released_as_deleted id=%s", item_id)
                continue
            raw_note = str(item.get("note") or "")
            base = strip_scheduled_note(raw_note)
            kwargs: dict = {"now": now}
            if base != raw_note:
                kwargs["note"] = base
            released.append(self.update(item_id, status=STATUS_WISHLIST, **kwargs))
        # 2026-11-13（删行程拍板）：释放只翻状态，绑定还必须摘掉——死行程
        # id 留在行上时 PG 外键会把行程删除挡成静默失败（204 后复活）；
        # booked/unwanted 行挂着死 id 同样挡删除，这里一并解绑。
        for item in list(self._items.values()):
            if item.get("itinerary_id") == itinerary_id:
                self.unbind_itinerary(item["id"], now=now)
        # 返回值同步解绑后的现状（调用方拿到的行不再声称挂在死行程上）
        return [self._items.get(r["id"]) or r for r in released]

    def mark_unwanted(
        self,
        name: str,
        *,
        itinerary_id: str | None = None,
        city: str | None = None,
    ) -> dict:
        """Plan-delete path: park the item in the unwanted group (or file a
        fresh unwanted entry when the plan never had one)."""
        for item in self._items.values():
            if item["itinerary_id"] == itinerary_id and item["name"] == name:
                if item["status"] != STATUS_UNWANTED:
                    return self.update(item["id"], status=STATUS_UNWANTED)
                return dict(item)
        created = self.create(
            name, source="plan_delete", itinerary_id=itinerary_id, city=city
        )
        return self.update(created["id"], status=STATUS_UNWANTED)

    # --- rules ----------------------------------------------------------------

    @staticmethod
    def _check_transition(
        current: str, target: str, *, day: int | None, booking_id: str | None
    ) -> None:
        """Legal edges of the state machine (everything else 422):
        wishlist->scheduled (day required), scheduled->booked (booking_id
        required), scheduled/booked->wishlist (un-schedule clears fields),
        wishlist/scheduled/booked->unwanted, unwanted->wishlist (restore).
        """
        if current == STATUS_WISHLIST and target == STATUS_SCHEDULED:
            if day is None or day < 1:
                raise InvalidTransitionError(f"day_required:{day}")
        elif current == STATUS_SCHEDULED and target == STATUS_BOOKED:
            if booking_id is None or not booking_id.strip():
                raise InvalidTransitionError("booking_id_required")
        elif target == STATUS_WISHLIST and current in _TIMELINE_STATUSES:
            pass
        elif target == STATUS_UNWANTED and current != STATUS_UNWANTED:
            pass
        elif current == STATUS_UNWANTED and target == STATUS_WISHLIST:
            pass
        else:
            raise InvalidTransitionError(f"{current}_to_{target}")

    @staticmethod
    def _check_fields(target: str, *, day: int | None, booking_id: str | None) -> None:
        if day is not None and day < 1:
            raise InvalidTransitionError(f"day_invalid:{day}")
        if booking_id is not None and not booking_id.strip():
            raise InvalidTransitionError("booking_id_required")

    def _next_position(self, itinerary_id: str | None, day: int) -> float:
        """Append after the last timeline item of the same trip/day."""
        positions = [
            item["position"]
            for item in self._items.values()
            if item["itinerary_id"] == itinerary_id
            and item["day"] == day
            and item["status"] in _TIMELINE_STATUSES
            and item["position"] is not None
        ]
        return max(positions) + 1.0 if positions else 1.0

    def _find_duplicate(
        self,
        name: str,
        *,
        source: str,
        itinerary_id: str | None,
        city: str | None,
        poi_id: str | None,
        items: Iterable[dict] | None = None,
        owner_device_id: str | None = None,
    ) -> dict | None:
        """Same trip + same thing = one row: poi_id is authoritative when
        both sides carry it, else the wish key (see _wish_key) matched by
        equality or bidirectional containment + city compatibility — a
        missing city never contradicts a known one (chat adds a bare 西湖,
        paste adds 西湖+杭州: same wish). Unwanted rows never match —
        re-adding a rejected item starts a fresh wishlist entry.
        2026-10-28 user report (the global board showed 西湖 once per
        trip): a same-name WISHLIST row from another trip is the same wish
        too. Same-day follow-up (变脸 twice on the board): 看变脸 /
        变脸表演（川剧）/ 川剧变脸 are one wish phrased three ways — hence
        the normalized key + containment layer instead of raw equality.
        Scheduled/booked rows of other trips never match (a new trip files
        its own wish — timeline rows stay per-trip), and the plan_delete
        bookkeeping write never global-merges (un-parking trip B must not
        flip trip A's wish). PgTripItemService feeds advisory-locked DB
        rows straight into this predicate — single implementation, no SQL
        mirror."""
        active = self._items.values() if items is None else items
        if owner_device_id is not None:
            # 2026-11-13：别的设备的同名行不是同一条心愿——各设备各一行
            active = [
                i
                for i in active
                if not i.get("owner_device_id")
                or i.get("owner_device_id") == owner_device_id
            ]
        if poi_id:
            for item in active:
                if (
                    item["itinerary_id"] == itinerary_id
                    and item["status"] != STATUS_UNWANTED
                    and item["poi_id"] == poi_id
                ):
                    return item
        key_name, key_city = _norm(name), _norm(city)
        wish_key = _wish_key(name)
        for item in active:
            if item["status"] == STATUS_UNWANTED:
                continue
            if not (
                _norm(item["name"]) == key_name
                or _wish_match(wish_key, _wish_key(item["name"]))
            ):
                continue
            item_city = _norm(item["city"])
            if key_city is not None and item_city is not None and item_city != key_city:
                continue
            if item["itinerary_id"] == itinerary_id:
                return item
            if source != "plan_delete" and item["status"] == STATUS_WISHLIST:
                return item
        return None
