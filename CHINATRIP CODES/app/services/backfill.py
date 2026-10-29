# -*- coding: utf-8 -*-
"""订单回填三层管道（设计 v2.4 §6.11 体验升级）。

粘贴回填为主 / 返回询问为辅 / 联盟订单同步自动（MVP = 确定性 mock，
无真实联盟 API 调用）。本模块承载 §4 action_handoffs 状态机：

    opened → user_confirmed（用户回填：paste_return / manual）
           → alliance_verified（联盟订单同步匹配）
           → settled（佣金结算）；returned = 退款逆向弧。

口径：
- 只做状态与归因记账，不碰凭据、不代下单；粘贴文本解析后即丢弃，
  store 只落结构化字段。
- parse_order_text 是纯函数（零 IO、零全局状态），独立单测。
- 置信度规则（§6.5：<0.8 不落库进待确认）：解析出 order_ref 且
  （渠道关键词命中 或 记录原 channel 命中）→ 0.9；只有订单号 → 0.75；
  无订单号 → 0。关键词属于纯文本侧；「记录原 channel 命中」需要记录
  上下文，在 apply_paste_return 里补强。
- HandoffStore 为进程内 dict，API 层用 translate.py 式懒单例接法。
"""

import logging
import re
import uuid as _uuid
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

__all__ = [
    "AllianceFeedItem",
    "HandoffNotFoundError",
    "HandoffRecord",
    "HandoffStore",
    "InvalidTransitionError",
    "ParsedOrder",
    "parse_order_text",
    "persist_handoff",
]

# --- §4 action_handoffs 状态机常量 -------------------------------------------

STATUS_OPENED = "opened"
STATUS_USER_CONFIRMED = "user_confirmed"
STATUS_ALLIANCE_VERIFIED = "alliance_verified"  # 联盟弧中间态；sync 一次到位 settled
STATUS_SETTLED = "settled"
STATUS_RETURNED = "returned"

SOURCE_PASTE_RETURN = "paste_return"
SOURCE_MANUAL = "manual"
SOURCE_ALLIANCE_API = "alliance_api"
SOURCE_CALLBACK = "callback"

OUTCOME_SETTLED = "settled"
OUTCOME_REFUNDED = "refunded"

CONFIRM_THRESHOLD = 0.8  # §6.5：置信度 <0.8 不写库，进待确认
CONFIDENCE_HIGH = 0.9
CONFIDENCE_REF_ONLY = 0.75

_UNDOABLE_SOURCES = frozenset({SOURCE_PASTE_RETURN, SOURCE_MANUAL})

# --- parse_order_text：纯函数正则 --------------------------------------------

# 订单号 token：8~20 位大写字母/数字；优先取关键词锚点后的 token
_REF_TOKEN_RE = re.compile(r"[A-Z0-9]{8,20}")
_ANCHORED_REF_RE = re.compile(
    r"(?:订单号|单号|(?i:order))\s*[#：:]?\s*([A-Z0-9]{8,20})"
)

# 金额（元）：三语境取文本序最先命中 —— ¥ 前缀 / 实付·总额·支付语境 / N元 后缀
_AMOUNT_RE = re.compile(
    r"[¥￥]\s*(\d+(?:\.\d{1,2})?)"
    r"|(?:实付款|实付|总额|支付|付款)[^\d¥￥]{0,4}[¥￥]?\s*(\d+(?:\.\d{1,2})?)"
    r"|(\d+(?:\.\d{1,2})?)\s*元"
)

# 渠道关键词（纯函数侧；小写渠道字面量留给「记录原 channel 命中」）
_CHANNEL_KEYWORDS: dict[str, str] = {
    "12306": "12306",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "meituan": "美团",
    "klook": "klook",
}

# 记录原 channel 的别名集（apply 时与粘贴文本小写不敏感比对）
_CHANNEL_ALIASES: dict[str, tuple[str, ...]] = {
    "12306": ("12306",),
    "ctrip": ("携程", "ctrip", "trip.com", "tripcom"),
    "qunar": ("去哪儿", "qunar"),
    "meituan": ("美团", "meituan"),
    "klook": ("klook",),
    "other": ("飞猪", "fliggy"),
}


class ParsedOrder(BaseModel):
    """parse_order_text 的产物（纯文本侧置信度，不含记录上下文）。"""

    order_ref: str | None = None
    channel: str | None = None
    amount_yuan: float | None = None
    confidence: float = 0.0


def parse_order_text(text: str) -> ParsedOrder:
    """粘贴文本 → 结构化订单线索（纯函数：零 IO、零全局状态）。

    - 订单号：[A-Z0-9]{8,20}，优先「订单号/单号/order」锚点后的 token，
      无锚点则取全文第一个 8+ 位字母数字串（纯数字噪声也走这条 fallback，
      靠 <0.8 置信度在 apply 时拦截）。
    - 金额：¥ 前缀 / 实付·总额·支付语境 / N元 后缀，取文本序最先命中。
    - 渠道：文本含 12306/携程/去哪儿/美团 关键词（剔除订单号本身后扫描，
      防止 ref 子串误命中渠道）。
    """
    order_ref = _extract_order_ref(text)
    scan_text = text.replace(order_ref, " ", 1) if order_ref else text
    channel = _detect_channel(scan_text)
    if order_ref and channel:
        confidence = CONFIDENCE_HIGH
    elif order_ref:
        confidence = CONFIDENCE_REF_ONLY
    else:
        confidence = 0.0
    return ParsedOrder(
        order_ref=order_ref,
        channel=channel,
        amount_yuan=_extract_amount(text),
        confidence=confidence,
    )


def _extract_order_ref(text: str) -> str | None:
    anchored = _ANCHORED_REF_RE.search(text)
    if anchored:
        return anchored.group(1)
    fallback = _REF_TOKEN_RE.search(text)
    return fallback.group(0) if fallback else None


def _detect_channel(text: str) -> str | None:
    low = text.lower()
    for channel, keyword in _CHANNEL_KEYWORDS.items():
        if keyword in text or keyword in low:
            return channel
    return None


def _extract_amount(text: str) -> float | None:
    match = _AMOUNT_RE.search(text)
    if match is None:
        return None
    value = next(g for g in match.groups() if g is not None)
    return float(value)


def _record_channel_hit(text: str, channel: str, order_ref: str | None) -> bool:
    """「记录原 channel 命中」：粘贴文本出现该 handoff 渠道的别名。"""
    if order_ref:
        text = text.replace(order_ref, " ", 1)
    lowered = text.lower()
    return any(alias in lowered for alias in _CHANNEL_ALIASES.get(channel, ()))


# --- 记录与 store -------------------------------------------------------------


class HandoffRecord(BaseModel):
    """§4 action_handoffs 单条记录（进程内；id = uuid4 hex）。"""

    id: str
    action_type: str  # train | flight | hotel | site_ticket
    channel: str  # 12306 | qunar | ctrip | meituan | klook | other
    url: str
    status: str = STATUS_OPENED
    order_ref: str | None = None
    source_channel: str | None = None
    refund_summary: str | None = None
    created_at: datetime
    updated_at: datetime


class AllianceFeedItem(BaseModel):
    """联盟订单同步 feed 的单条（MVP 确定性 mock 输入）。"""

    order_ref: str = Field(min_length=1, max_length=64)
    outcome: str = Field(pattern="^(settled|refunded)$")


class HandoffNotFoundError(KeyError):
    """handoff id 不存在（API 层映射 404）。"""


class InvalidTransitionError(ValueError):
    """状态机守卫拦截（API 层映射 422 invalid_transition）。"""


class HandoffStore:
    """进程内 store + 状态机规则。API 层单例接法（懒初始化），
    多进程部署需换共享存储——规则全在本类，替换不动端点。

    可选 persistence 钩子（attach_persistence）：每次状态推进后
    best-effort 写穿 PG action_handoffs（重启不丢账）；钩子异常只留
    日志不回滚内存态（内存是运行时真相，PG 是留痕账本）。
    """

    def __init__(self) -> None:
        self._records: dict[str, HandoffRecord] = {}
        self._persist: Callable[[HandoffRecord], None] | None = None

    def attach_persistence(self, fn: Callable[[HandoffRecord], None]) -> None:
        self._persist = fn

    def _persist_safe(self, record: HandoffRecord) -> None:
        if self._persist is None:
            return
        try:
            self._persist(record)
        except Exception:
            logger.warning(
                "handoff_persist_failed id=%s status=%s",
                record.id,
                record.status,
                exc_info=True,
            )

    # -- 基础读写 -------------------------------------------------------------

    def create(
        self,
        *,
        action_type: str,
        channel: str,
        url: str,
        refund_summary: str | None = None,
    ) -> HandoffRecord:
        """跳转埋点：新建 opened 记录，不推进状态。"""
        now = datetime.now(timezone.utc)
        record = HandoffRecord(
            id=uuid4().hex,
            action_type=action_type,
            channel=channel,
            url=url,
            status=STATUS_OPENED,
            refund_summary=refund_summary,
            created_at=now,
            updated_at=now,
        )
        self._records[record.id] = record
        self._persist_safe(record)
        return record

    def get(self, record_id: str) -> HandoffRecord | None:
        return self._records.get(record_id)

    def list_records(self, status: str | None = None) -> list[HandoffRecord]:
        if status is None:
            return list(self._records.values())
        return [r for r in self._records.values() if r.status == status]

    def _require(self, record_id: str) -> HandoffRecord:
        record = self._records.get(record_id)
        if record is None:
            raise HandoffNotFoundError(record_id)
        return record

    @staticmethod
    def _touch(record: HandoffRecord) -> None:
        record.updated_at = datetime.now(timezone.utc)

    # -- 主通道：粘贴回填 ------------------------------------------------------

    def apply_paste_return(
        self, record_id: str, text: str
    ) -> tuple[HandoffRecord, ParsedOrder, bool, str | None]:
        """opened → user_confirmed（置信度闸门 §6.5）。

        返回 (record, parsed, applied, reason)。conf ≥0.8：写入
        order_ref + source_channel=paste_return；conf <0.8：记录不动，
        applied=False + reason="needs_confirm"。解析在守卫之后——非法
        状态先 422，不烧解析。
        """
        record = self._require(record_id)
        if record.status != STATUS_OPENED:
            raise InvalidTransitionError(
                f"paste_return requires opened, got {record.status}"
            )
        parsed = parse_order_text(text)
        confidence = parsed.confidence
        if (
            parsed.order_ref
            and parsed.channel is None
            and _record_channel_hit(text, record.channel, parsed.order_ref)
        ):
            confidence = CONFIDENCE_HIGH
            parsed = parsed.model_copy(update={"confidence": confidence})
        if confidence < CONFIRM_THRESHOLD:
            return record, parsed, False, "needs_confirm"
        record.status = STATUS_USER_CONFIRMED
        record.source_channel = SOURCE_PASTE_RETURN
        record.order_ref = parsed.order_ref
        self._touch(record)
        self._persist_safe(record)
        return record, parsed, True, None

    # -- 兜底通道：手动标记 ----------------------------------------------------

    def apply_manual(self, record_id: str, order_ref: str) -> HandoffRecord:
        """opened → user_confirmed，source_channel=manual（用户自己抄单号）。"""
        record = self._require(record_id)
        if record.status != STATUS_OPENED:
            raise InvalidTransitionError(f"manual requires opened, got {record.status}")
        record.status = STATUS_USER_CONFIRMED
        record.source_channel = SOURCE_MANUAL
        record.order_ref = order_ref
        self._touch(record)
        self._persist_safe(record)
        return record

    # -- 可撤销 ---------------------------------------------------------------

    def undo(self, record_id: str) -> HandoffRecord:
        """user_confirmed → opened：清 order_ref + source_channel。

        只有 paste_return / manual 来源的用户回填可撤（撤销的是用户的
        输入）；alliance_api 推进的（已 settled / returned）不许撤。
        """
        record = self._require(record_id)
        if record.status != STATUS_USER_CONFIRMED or (
            record.source_channel not in _UNDOABLE_SOURCES
        ):
            raise InvalidTransitionError(
                f"undo requires user_confirmed via paste_return/manual, "
                f"got {record.status}/{record.source_channel}"
            )
        record.status = STATUS_OPENED
        record.order_ref = None
        record.source_channel = None
        self._touch(record)
        self._persist_safe(record)
        return record

    # -- 自动通道：联盟订单同步（MVP 确定性 mock） -----------------------------

    def alliance_sync(self, feed: list[AllianceFeedItem]) -> dict:
        """user_confirmed → settled / returned（经 alliance_verified 一次到位）。

        对每条 feed 找 status=user_confirmed 且 order_ref 匹配的记录：
        outcome=settled → settled；outcome=refunded → returned；两者
        source_channel 都改 alliance_api。找不到/状态不符 → skipped。
        """
        matched = 0
        advanced: list[str] = []
        skipped = 0
        for item in feed:
            record = next(
                (
                    r
                    for r in self._records.values()
                    if r.status == STATUS_USER_CONFIRMED
                    and r.order_ref == item.order_ref
                ),
                None,
            )
            if record is None:
                skipped += 1
                continue
            matched += 1
            record.status = (
                STATUS_SETTLED if item.outcome == OUTCOME_SETTLED else STATUS_RETURNED
            )
            record.source_channel = SOURCE_ALLIANCE_API
            self._touch(record)
            self._persist_safe(record)
            advanced.append(record.id)
        return {"matched": matched, "advanced": advanced, "skipped": skipped}


def persist_handoff(record: HandoffRecord) -> None:
    """写穿 PG action_handoffs（database_design §4.4 账本表）。

    insert-or-update by id（record.id = uuid4 hex 可直接 UUID() 解析）。
    DB 缺席时由调用方（_persist_safe）留日志降级——服务器重启前内存
    态仍在，账本尽力而为。
    """
    from app.db import get_session_factory
    from app.models import ActionHandoff

    row_id = _uuid.UUID(record.id)
    with get_session_factory()() as session:
        row = session.get(ActionHandoff, row_id)
        if row is None:
            session.add(
                ActionHandoff(
                    id=row_id,
                    action_type=record.action_type,
                    channel=record.channel,
                    deeplink=record.url,
                    status=record.status,
                    order_ref=record.order_ref,
                    source_channel=record.source_channel,
                    refund_policy=(
                        {"summary": record.refund_summary}
                        if record.refund_summary
                        else None
                    ),
                )
            )
        else:
            row.status = record.status
            row.order_ref = record.order_ref
            row.source_channel = record.source_channel
            row.updated_at = datetime.now(timezone.utc)
        session.commit()
