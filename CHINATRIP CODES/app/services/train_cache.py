"""火车班次日维度缓存 + 落库记录层（v2.4 行程中心配套）。

痛点：每次规划请求实时打 12306（~20s，且无凭据查询当前必降级 mock），
班次从不落库、无法回看。本模块在 TrainService 外包一层 SQLite 缓存：

- 写路径：inner（数据源链）返回非空班次时整批追加落库（fetched_at 同值
  = 一个日批次）；空批次不落库——链降级与真无票无法区分，都不可信；
- 读路径：(from_city, to_city, query_date) 命中 TTL 内的日批次直接返回，
  零网络；
- 留史只追加：不 UPDATE 不 DELETE，唯一约束保证重跑幂等，读取永远取
  最新 fetched_at 批次，历史批次留档可回溯。

存储走独立 SQLite（settings.train_cache_url，默认 data/train_cache.db），
与 app/db.py 的 PG engine 无关（本机无 Postgres，业务 store 均为内存
实现）；换 PG 时改 DSN 即可，ORM 复用 app/models.py 的同一套 metadata。
同步 SQLAlchemy：表小、毫秒级，异步 search 里直接做 DB IO，不引 asyncio
扩展依赖。
"""

import asyncio
from collections.abc import Callable
from datetime import date as _date
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    func,
    select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.models import Base
from app.services.trains import (
    _MOCK_COVERED_PAIRS,
    MockTrainService,
    TrainOption,
    TrainService,
    _build_remote_chain,
)


def _utcnow() -> datetime:
    """naive UTC：sqlite DateTime 列读写均为 naive，统一 naive UTC 存取，
    避免 tz-aware 与 naive 直接比较抛 TypeError。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TrainScheduleRecord(Base):
    """火车班次落库行（表 train_schedule_cache）。

    日批次 = fetched_at 同值的一批行；只追加不改写，读取永远取
    (from_city, to_city, query_date) 最新 fetched_at 批次。
    """

    __tablename__ = "train_schedule_cache"
    __table_args__ = (
        # 批次身份 = fetched_at：同批（同 fetched_at）重跑幂等被 INSERT OR
        # IGNORE 吞掉；跨批次全量快照留史——同车次在新批次再记一行，取消的
        # 车次随旧批次整体被"最新批次"读取自然淘汰。fetched_at 不进键则新
        # 批次里与旧批次重复的车次被误吞，下批读取会丢班次（512→513 测中
        # G1 丢失即此）。
        UniqueConstraint(
            "from_city",
            "to_city",
            "query_date",
            "train_no",
            "dep_time",
            "from_station",
            "fetched_at",
            name="uq_train_schedule_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_city: Mapped[str] = mapped_column(String(50), index=True)
    to_city: Mapped[str] = mapped_column(String(50), index=True)
    query_date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    train_no: Mapped[str] = mapped_column(String(20))
    dep_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    arr_time: Mapped[str] = mapped_column(String(5))  # "HH:MM"
    duration_minutes: Mapped[int] = mapped_column(Integer)
    from_station: Mapped[str] = mapped_column(String(50))
    to_station: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(20))  # 12306|mock|chain|...
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


def _resolve_query_date(date: str) -> str:
    """非空日期原样返回；空则 today+3（与 Train12306Source 同一占位规则：
    规划场景的班次表日内基本稳定，用近端日期查询）。"""
    stripped = date.strip()
    if stripped:
        return stripped
    return (_date.today() + timedelta(days=3)).isoformat()


def _record_to_option(record: TrainScheduleRecord) -> TrainOption:
    """落库行 -> TrainOption（时刻以 "HH:MM" 字符串存取）。"""
    return TrainOption(
        train_no=record.train_no,
        dep_time=time.fromisoformat(record.dep_time),
        arr_time=time.fromisoformat(record.arr_time),
        duration_minutes=record.duration_minutes,
        from_station=record.from_station,
        to_station=record.to_station,
        from_city=record.from_city,
        to_city=record.to_city,
        date=record.query_date,
    )


class CachedTrainService(TrainService):
    """TrainService 装饰器：SQLite 日批次缓存挡在数据源链前面。

    读命中（TTL 内日批次）零网络；miss/过期才打 inner，非空结果整批追加
    落库（空结果不落库）。inner 抛错时回退库内旧批次（哪怕已过期——旧
    班次好过没班次）；库里也空才把异常放出去。
    """

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        inner: TrainService,
        ttl_hours: float = 24.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._inner = inner
        self._ttl_hours = ttl_hours
        self._clock = clock or _utcnow

    async def search(
        self, from_city: str, to_city: str, date: str
    ) -> list[TrainOption]:
        qdate = _resolve_query_date(date)
        if from_city == to_city:
            return []
        now = self._clock()
        stale = self._latest_batch(from_city, to_city, qdate)
        if stale and now - stale[0].fetched_at <= timedelta(hours=self._ttl_hours):
            return [_record_to_option(record) for record in stale]
        try:
            # 传 qdate 而非原始 date：inner（含 12306 源）拿到确定日期，
            # 返回的 TrainOption.date 也即 qdate，读缓存/落库键一致。
            options = await self._inner.search(from_city, to_city, qdate)
        except Exception:
            if stale:
                return [_record_to_option(record) for record in stale]
            raise
        if options:
            self._write_batch(from_city, to_city, qdate, options, now)
        return options

    def _latest_batch(
        self, from_city: str, to_city: str, qdate: str
    ) -> list[TrainScheduleRecord]:
        """库内 (pair, qdate) 最新 fetched_at 批次的全部行；无记录返回 []。"""
        pair_filter = (
            TrainScheduleRecord.from_city == from_city,
            TrainScheduleRecord.to_city == to_city,
            TrainScheduleRecord.query_date == qdate,
        )
        with self._session_factory() as session:
            latest = session.execute(
                select(func.max(TrainScheduleRecord.fetched_at)).where(*pair_filter)
            ).scalar_one_or_none()
            if latest is None:
                return []
            return list(
                session.execute(
                    select(TrainScheduleRecord)
                    .where(*pair_filter, TrainScheduleRecord.fetched_at == latest)
                    .order_by(TrainScheduleRecord.dep_time)
                )
                .scalars()
                .all()
            )

    def _write_batch(
        self,
        from_city: str,
        to_city: str,
        qdate: str,
        options: list[TrainOption],
        now: datetime,
    ) -> None:
        """整批追加落库（fetched_at=now，日批次语义）；唯一约束冲突静默忽略。"""
        # 来源标记：RemoteTrainService.last_source=命中源名（含 "mock"）；
        # inner 没有该属性（纯 mock/测试桩）时退 "chain"。
        source = getattr(self._inner, "last_source", None) or "chain"
        rows = [
            {
                "from_city": from_city,
                "to_city": to_city,
                "query_date": qdate,
                "train_no": option.train_no,
                "dep_time": option.dep_time.strftime("%H:%M"),
                "arr_time": option.arr_time.strftime("%H:%M"),
                "duration_minutes": option.duration_minutes,
                "from_station": option.from_station,
                "to_station": option.to_station,
                "source": source,
                "fetched_at": now,
            }
            for option in options
        ]
        # 换 PG 时改 postgresql_insert(...).on_conflict_do_nothing(...)，
        # 语义相同；本任务只跑 sqlite。
        stmt = sqlite_insert(TrainScheduleRecord).values(rows)
        stmt = stmt.on_conflict_do_nothing()
        with self._session_factory() as session:
            session.execute(stmt)
            session.commit()


_train_cache_engine: Engine | None = None


def get_train_cache_engine(settings) -> Engine:
    """进程级单例缓存引擎；sqlite 相对路径时自动建父目录。"""
    global _train_cache_engine
    if _train_cache_engine is None:
        url = settings.train_cache_url
        if url.startswith("sqlite:///"):
            db_path = Path(url[len("sqlite:///") :])
            db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            # sqlite 需要 check_same_thread=False：uvicorn 的依赖注入与事件
            # 循环可能在不同线程碰同一连接池；PG 无此参数。
            connect_args=(
                {"check_same_thread": False} if url.startswith("sqlite") else {}
            ),
        )
        # 只建本模块的表：Base.metadata 其余表是 PG 专属类型，sqlite 建不了。
        Base.metadata.create_all(engine, tables=[TrainScheduleRecord.__table__])
        _train_cache_engine = engine
    return _train_cache_engine


def _select_inner(settings) -> TrainService:
    """inner 与 get_train_service 同门：远程关（测试/离线）用 Mock，
    开着用完整数据源链。"""
    if settings.train_remote_enabled:
        return _build_remote_chain(settings)
    return MockTrainService()


def create_cached_train_service(settings) -> CachedTrainService:
    """装配 CachedTrainService（get_train_service 与刷新作业共用）。"""
    return CachedTrainService(
        session_factory=sessionmaker(bind=get_train_cache_engine(settings)),
        inner=_select_inner(settings),
        ttl_hours=settings.train_cache_ttl_hours,
    )


def _default_refresh_pairs(
    session_factory: Callable[[], Session],
) -> list[tuple[str, str]]:
    """默认刷新范围：库内已有 distinct pair ∪ mock 覆盖的核心 pair。

    核心对直接读 trains._MOCK_COVERED_PAIRS（单一事实源，勿复制粘贴清单）；
    并入库内 pair 保证用户新查过的城市对次日也被刷新。
    """
    with session_factory() as session:
        stored = session.execute(
            select(
                TrainScheduleRecord.from_city, TrainScheduleRecord.to_city
            ).distinct()
        ).all()
    pairs = {tuple(row) for row in stored} | set(_MOCK_COVERED_PAIRS)
    return sorted(pairs)


def refresh_train_cache(
    settings,
    pairs: list[tuple[str, str]] | None = None,
    date: str | None = None,
) -> dict:
    """日刷新作业核心：逐 (pair, date) 走一遍缓存 search，miss 自然触发
    拉取 + 落库（供 CLI app/jobs/refresh_trains 调）。

    date 缺省 None -> today+3；query_date 每日向前滚，新日期天然 miss，
    每日刷新必落新批次。返回 JSON 可序列化汇总：refreshed=无错 pair 数、
    pairs=本次覆盖的 pair、rows_written=各 pair 返回班次行数合计（TTL 内
    幂等重跑=读回同批，行数不变、不重复落库）、errors={pair: 报错}。
    """
    session_factory = sessionmaker(bind=get_train_cache_engine(settings))
    if pairs is None:
        pairs = _default_refresh_pairs(session_factory)
    service = CachedTrainService(
        session_factory=session_factory,
        inner=_select_inner(settings),
        ttl_hours=settings.train_cache_ttl_hours,
    )
    refreshed = 0
    rows_written = 0
    errors: dict[str, str] = {}
    for from_city, to_city in pairs:
        label = f"{from_city}->{to_city}"
        try:
            options = asyncio.run(service.search(from_city, to_city, date or ""))
        except Exception as exc:  # 单对失败不拖垮整批作业
            errors[label] = str(exc)
            continue
        refreshed += 1
        rows_written += len(options)
    return {
        "refreshed": refreshed,
        "pairs": [list(pair) for pair in pairs],
        "rows_written": rows_written,
        "errors": errors,
    }
