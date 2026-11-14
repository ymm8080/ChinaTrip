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
        created_by: str | None = None,
        city: str | None = None,
        note: str | None = None,
        poi_id: str | None = None,
        address: str | None = None,
        opening_hours: str | None = None,
        kind: str | None = None,
        duration_minutes: int | None = None,
        tier: int | None = None,
        site_rank: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        rain_ok: str | None = None,
        must_visit: bool = False,
        raw_command: str | None = None,
        # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：规划会话
        # 建的行是草稿——只有点「💾 保存行程」才转正进心愿单
        draft_session_id: str | None = None,
        # 2026-11-14（用户拍板「心愿单/已排期也是 USER ID 的数据」）：登录
        # 账号随行落库——打开看板按用户出内容，换设备登录也能看到
        owner_account_id: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Idempotent create: returns the existing row instead of a new one
        when this trip already holds the same poi_id / name+city (an empty
        city matches any). 2026-10-28 user report (multiple 西湖 on the
        global board): a same-name wishlist row from another trip is the
        same wish too — see _find_duplicate for the exact predicate."""
        if source not in SOURCES:
            raise InvalidSourceError(f"invalid_source:{source}")
        # 2026-11-14：草稿行只在本会话内参与查重——别的未保存会话留下的
        # 草稿不能把新会话的心愿「吸」成一条看不见的行（本会话重说一遍
        # 仍要命中自己的草稿，防重复建行）。
        known = [
            i
            for i in self._items.values()
            if not i.get("draft_session_id")
            or i.get("draft_session_id") == draft_session_id
        ]
        duplicate = self._find_duplicate(
            name,
            source=source,
            itinerary_id=itinerary_id,
            city=city,
            poi_id=poi_id,
            owner_device_id=owner_device_id,
            owner_account_id=owner_account_id,
            items=known,
        )
        if duplicate is not None:
            # Same wish, richer info: fill ONLY empty fields of the existing
            # row (a deliberate 杭州 never becomes 苏州); the row survives
            # with everything the second submission knew.
            self._enrich_duplicate(
                duplicate,
                name=name,
                source=source,
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
            # 非空 = 草稿（未保存行程），看板/视图不返回（2026-11-14）
            "draft_session_id": draft_session_id,
            # USER ID 键（登录账号字符串，与行程头 owner_account_id 同源）
            "owner_account_id": owner_account_id,
            # 2026-11-13 数据库事实化：归属设备随行落库（看板按设备读）
            "owner_device_id": owner_device_id,
            # 心愿单数据库字段（2026-11-13 拍板）：建行人 / 是否排期 /
            # 排除标记——ARRANGED 由「有具体日期时刻」决定（update 维护）
            "created_by": created_by or owner_device_id,
            "arranged": False,
            "exclusion_flag": False,
            # 规划字段（2026-11-13）：建行即记类型与用户原话，排期后补齐
            "kind": kind,
            "duration_minutes": duration_minutes,
            "tier": tier,
            "site_rank": site_rank,
            "latitude": latitude,
            "longitude": longitude,
            "rain_ok": rain_ok,
            "raw_command": raw_command,
            "must_visit": bool(must_visit),
            "pinned": False,
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
        source: str | None = None,
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
        if source in ("manual", "chat", "paste") and item.get("exclusion_flag"):
            # 用户再次明确点名（手动/对话/粘贴）→ 解除排除：排除只是
            # 「删站点后别自动再排」，不是永久黑名单。
            item["exclusion_flag"] = False
            changed = True
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
        owner_account_id: str | None = None,
        *,
        include_drafts: bool = True,
    ) -> dict:
        """Timeline payload (§5): Bookings pinned first, Wishlist stream,
        Scheduled as the third key — each in its documented order.

        2026-11-13（用户拍板「这些应该都是数据库的数据」）：行归属设备
        ——带 owner_device_id 时只回该设备的行；不带（脚本/运维）回全量。
        """
        items = list(self._items.values())
        if not include_drafts:
            # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：草稿行
            # 只在规划引擎内部可见，看板/接口一律不返回
            items = [i for i in items if not i.get("draft_session_id")]
        if owner_device_id is not None or owner_account_id is not None:
            # 2026-11-14（用户拍板「打开行程中心按 USER ID 出内容」）：本
            # 设备的行 + 本登录账号的行（换设备登录也看得到）都算「我的」；
            # 无归属（历史行/脚本建行）仍可见——归属列是新事实，不能让老
            # 数据在升级瞬间集体消失；别人的行（别的设备且别的账号）隐藏。
            def _mine(item: dict) -> bool:
                row_dev = item.get("owner_device_id")
                row_acct = item.get("owner_account_id")
                if row_dev is None and row_acct is None:
                    return True  # 历史无归属行：维持原可见口径
                if owner_device_id is not None and row_dev == owner_device_id:
                    return True
                if owner_account_id is not None and row_acct == owner_account_id:
                    return True
                return False

            items = [i for i in items if _mine(i)]
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
        exclusion_flag: bool | None = None,
        kind: str | None = None,
        duration_minutes: int | None = None,
        must_visit: bool | None = None,
        pinned: bool | None = None,
        tier: int | None = None,
        site_rank: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        planned_date: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
        rain_ok: str | None = None,
        raw_command: str | None = None,
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
            # 回心愿单 = 取消具体日期时刻（ARRANGED 语义）
            item["planned_date"] = None
            item["start_time"] = None
            item["end_time"] = None
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
        for field, value in (
            ("kind", kind),
            ("duration_minutes", duration_minutes),
            ("must_visit", must_visit),
            ("pinned", pinned),
            ("tier", tier),
            ("site_rank", site_rank),
            ("latitude", latitude),
            ("longitude", longitude),
            ("planned_date", planned_date),
            ("start_time", start_time),
            ("end_time", end_time),
            ("rain_ok", rain_ok),
            ("raw_command", raw_command),
        ):
            if value is not None:
                item[field] = value
        # 心愿单数据库字段（2026-11-13 拍板）：ARRANGED = 有具体日期时刻
        # （已排期/已订且天序在）；EXCLUSION = 用户删站点后明确排除，
        # 已排进/已订的行自动解除（它就在行程里）。
        item["arranged"] = target in _TIMELINE_STATUSES and item.get("day") is not None
        if exclusion_flag is not None:
            item["exclusion_flag"] = bool(exclusion_flag)
        elif target == STATUS_UNWANTED:
            item["exclusion_flag"] = True
        elif target in _TIMELINE_STATUSES:
            item["exclusion_flag"] = False
        item["updated_at"] = _iso_now(now)
        return dict(item)

    def _persist(self, item_id: str) -> None:
        """行落库钩子（2026-11-14）：基类按 `_write_through` 约定（PG 子类
        实现）；SQLite 子类覆写为整行 JSON 落盘。无钩子 = 纯内存。"""
        hook = getattr(self, "_write_through", None)
        if callable(hook):
            hook(item_id)

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
        self._persist(item_id)
        return dict(item)

    def delete(self, item_id: str, *, actor: str | None = None) -> None:
        item = self._items.get(item_id)
        if item is None:
            raise NotFoundError(item_id)
        if item["status"] == STATUS_BOOKED:
            # §5 timeline integrity: un-book before removing.
            raise InvalidTransitionError("booked_not_deletable")
        del self._items[item_id]
        logger.info("trip_item_deleted id=%s actor=%s", item_id, actor)

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
        self._persist(item_id)
        return dict(item)

    def release_itinerary(
        self,
        itinerary_id: str,
        *,
        now: datetime | None = None,
        actor: str | None = None,
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
        bound = [
            dict(item)
            for item in self._items.values()
            if item.get("itinerary_id") == itinerary_id
        ]
        released: list[dict] = []
        for item in bound:
            item_id = item["id"]
            status = item.get("status")
            source = str(item.get("source") or "")
            if source == "plan":
                # 引擎补源行不是用户心愿（2026-11-12 拍板）：只软删不重建
                try:
                    self.delete(item_id, actor=actor)
                except InvalidTransitionError:
                    continue
                continue
            if status == STATUS_BOOKED:
                # 真实订单不重建、不删除：只摘行程绑定（订单栏自有真相）
                self.unbind_itinerary(item_id, now=now)
                continue
            if status == STATUS_UNWANTED:
                # 用户明确「不想去」的项不复活：软删留档即可
                try:
                    self.delete(item_id, actor=actor)
                except InvalidTransitionError:
                    continue
                continue
            # 2026-11-13 用户拍板：旧行软删留档（DELETION FLAG + 日期/
            # 时间/人），排期项重建为无行程心愿行（ARRANGED=False → 心愿单）
            raw_note = str(item.get("note") or "")
            base = strip_scheduled_note(raw_note)
            clone_source = source if source in SOURCES else "manual"
            # 用户拍板：删行程时 ARRANGED 取消（已安排 → 心愿单）——旧行先
            # 回心愿单态（清天序/时刻）再软删留档，审计里不会再声称已排期
            try:
                self.update(item_id, status=STATUS_WISHLIST, now=now)
            except InvalidTransitionError:
                pass
            try:
                self.delete(item_id, actor=actor)
            except InvalidTransitionError:
                continue
            try:
                released.append(
                    self.create(
                        str(item.get("name") or ""),
                        source=clone_source,
                        itinerary_id=None,
                        owner_device_id=item.get("owner_device_id"),
                        created_by=item.get("created_by"),
                        city=item.get("city"),
                        note=base or None,
                        poi_id=item.get("poi_id"),
                        address=item.get("address"),
                        opening_hours=item.get("opening_hours"),
                        now=now,
                    )
                )
            except (InvalidSourceError, ValueError):
                logger.warning(
                    "trip_item_release_clone_failed id=%s name=%s",
                    item_id,
                    item.get("name"),
                )
        # 兜底：仍挂着该行程的行（booked/unwanted 之外的异常态）一律解绑，
        # 否则 PG 外键会挡下行程删除（204 后行程复活）。
        for item in list(self._items.values()):
            if item.get("itinerary_id") == itinerary_id:
                self.unbind_itinerary(item["id"], now=now)
        return released

    def commit_drafts(
        self,
        itinerary_id: str,
        session_id: str | None = None,
        owner_account_id: str | None = None,
    ) -> int:
        """保存行程 = 心愿草稿转正（2026-11-14 用户拍板「没保存行程，心愿单
        就不该保存」）：本会话建的草稿行（以及已按名字挂到本行程的草稿行）
        清掉 draft_session_id、补上行程归属——从这一刻起看板/心愿单可见。
        返回转正行数。"""
        if not itinerary_id:
            return 0
        committed = 0
        for item in list(self._items.values()):
            draft_sid = item.get("draft_session_id")
            if not draft_sid:
                continue
            if item.get("itinerary_id") != itinerary_id and draft_sid != session_id:
                continue
            item["draft_session_id"] = None
            if not item.get("itinerary_id"):
                item["itinerary_id"] = itinerary_id
            # 转正即落 USER ID（登录账号）——看板按用户出内容
            if owner_account_id and not item.get("owner_account_id"):
                item["owner_account_id"] = owner_account_id
            item["updated_at"] = _iso_now(None)
            committed += 1
            self._persist(item["id"])
        if committed:
            logger.info(
                "trip_item_drafts_committed itinerary=%s session=%s rows=%d",
                itinerary_id,
                session_id,
                committed,
            )
        return committed

    def dedupe_itinerary_rows(
        self,
        itinerary_id: str,
        *,
        actor: str | None = None,
    ) -> int:
        """同一行程里同名心愿行只留一行（2026-11-14 用户报「已排期里同一个
        心愿出现两三条」的自愈）：历史版本按名字跨会话/跨行程吸收 + 每次
        重新规划新建一行，导致同一 wish 在已排期滚出多行。保留序 = 已排期
        （有 day）优先 → created_at 最早；多余行软删留档（booked 真实订单
        不参与）。返回软删行数。"""
        if not itinerary_id:
            return 0
        rows = [
            item
            for item in self._items.values()
            if item.get("itinerary_id") == itinerary_id
            and item.get("status") != STATUS_BOOKED
        ]
        rows.sort(
            key=lambda r: (
                r.get("status") != STATUS_SCHEDULED,
                str(r.get("created_at") or ""),
            )
        )
        seen: set[str] = set()
        removed = 0
        for item in rows:
            key = _wish_key(str(item.get("name") or ""))
            if key not in seen:
                seen.add(key)
                continue
            try:
                self.delete(item["id"], actor=actor or "wish-dedupe")
            except (InvalidTransitionError, NotFoundError):
                continue
            removed += 1
            logger.info(
                "trip_item_deduped_in_trip itinerary=%s name=%s id=%s",
                itinerary_id,
                item.get("name"),
                item["id"],
            )
        return removed

    def purge_itinerary(
        self,
        itinerary_id: str,
        *,
        now: datetime | None = None,
        actor: str | None = None,
    ) -> list[dict]:
        """删行程 = 名下心愿单一并删除（2026-11-14 用户拍板：
        「当行程被用户删除时，它的相关心愿单没有被删除」）。

        与旧 release_itinerary 的区别：不再把排期项重建回心愿单——心愿单
        随行程走，行程没了就一起走。booked 是真实订单（订单栏自有真相），
        只摘行程绑定、不删；其余状态（wishlist/scheduled/unwanted）一律
        软删留档（DELETION FLAG + 日期/时间/人）。返回被删的行。

        PG 外键兜底同旧法：清完后仍挂着该行程的行一律解绑，否则 DELETE
        /itineraries/{id} 会被 FK 挡下（接口 204、刷新后又复活）。"""
        if not itinerary_id:
            return []
        rows = [
            dict(item)
            for item in self._items.values()
            if item.get("itinerary_id") == itinerary_id
        ]
        purged: list[dict] = []
        for item in rows:
            if item.get("status") == STATUS_BOOKED:
                self.unbind_itinerary(item["id"], now=now)
                continue
            try:
                self.delete(item["id"], actor=actor)
            except (InvalidTransitionError, NotFoundError):
                continue
            purged.append(item)
        for item in list(self._items.values()):
            if item.get("itinerary_id") == itinerary_id:
                self.unbind_itinerary(item["id"], now=now)
        logger.info(
            "trip_itinerary_purged itinerary=%s rows=%d actor=%s",
            itinerary_id,
            len(purged),
            actor,
        )
        return purged

    def mark_excluded(
        self,
        name: str,
        *,
        itinerary_id: str | None = None,
        city: str | None = None,
        draft_session_id: str | None = None,
        owner_account_id: str | None = None,
    ) -> dict:
        """删行程里的站点（2026-11-13 用户拍板）：这一项回心愿单栏并打
        EXCLUSION 标记——用户明确不要它，规划不得自动再排；与「不想去」
        分区不同，心愿单里仍可见、可手动再排期。没有既有行就建一条。"""
        for item in self._items.values():
            if item.get("status") == STATUS_UNWANTED:
                continue
            if itinerary_id and item.get("itinerary_id") != itinerary_id:
                continue
            row_name = _norm(str(item.get("name") or ""))
            if not row_name or row_name != _norm(name):
                continue
            raw_note = str(item.get("note") or "")
            base = strip_scheduled_note(raw_note)
            kwargs: dict = {"exclusion_flag": True}
            if base != raw_note:
                kwargs["note"] = base
            return self.update(item["id"], status=STATUS_WISHLIST, **kwargs)
        created = self.create(
            name,
            source="plan_delete",
            itinerary_id=itinerary_id,
            city=city,
            draft_session_id=draft_session_id,
            owner_account_id=owner_account_id,
        )
        return self.update(created["id"], status=STATUS_WISHLIST, exclusion_flag=True)

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
        owner_account_id: str | None = None,
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
        if owner_device_id is not None or owner_account_id is not None:
            # 2026-11-13：别的用户的同名行不是同一条心愿。2026-11-14（用户
            # 拍板「心愿单按 USER ID 走」）：同一登录账号换设备也认领同一行
            # ——设备或账号任一命中即本人；两者都空（历史行）仍参与查重。
            def _owner_matches(item: dict) -> bool:
                row_dev = item.get("owner_device_id")
                row_acct = item.get("owner_account_id")
                if row_dev is None and row_acct is None:
                    return True
                if owner_device_id is not None and row_dev == owner_device_id:
                    return True
                if owner_account_id is not None and row_acct == owner_account_id:
                    return True
                return False

            active = [i for i in active if _owner_matches(i)]
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
