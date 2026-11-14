"""天安门升（降）旗时刻：官方年度公告页 → 表图 OCR 解析 → 落库 + 快照。

数据源：北京市人民政府天安门地区管理委员会每年发布一次「天安门广场
升（降）国旗时刻表」，正文表格是一张嵌入 PNG（无文字版），因此解析走
OCR（rapidocr-onnxruntime，懒导入——库缺失时抓取降级失败、查询不受影响）。

三段式（2026-11-14 拍板）：
1. 输入公告页 URL（默认官方页）；
2. 下载表图 → OCR 还原 31 行 × 12 月 × 升/降 网格 → 校验闸门（不合格
   不落库不覆盖）→ 落库 + DESIGN 目录快照 CSV；
3. 规划引擎装配期对天安门站点按日查询升旗时刻（get_flag_time），作为
   当日站点开始时间（plan._apply_flag_schedule 打标 fixed_sessions）。

存储（2026-11-14 用户拍板两条）：
- 每次抓取建表插入而非替换：只追加不 UPDATE 不 DELETE，一次抓取=一个
  fetched_at 批次（与 train_cache「留史只追加」同一口径）；读取永远取
  每个 date 的最新 fetched_at 批次，历史批次留档可回溯。
- 本地文件落 DESIGN 目录（数据设计文件夹，照
  reservation_rules_snapshot_2026-11-01.json 命名惯例）：快照 CSV
  flag_schedule_snapshot_<date>.csv，同日重跑幂等覆盖。

降级契约：查询永不抛（库缺/坏行/关开关一律 None→规划按默认日始排）；
抓取失败只记 WARNING、库内旧批次继续可用。
"""

import argparse
import csv
import json
import logging
import re
from collections import defaultdict
from datetime import date as _date
from datetime import datetime, time, timezone
from pathlib import Path

import httpx
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
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from app.config import get_settings
from app.models import Base

logger = logging.getLogger(__name__)

#: 官方年度公告页默认地址（2026 年版）。
DEFAULT_SOURCE_URL = (
    "https://tamgw.beijing.gov.cn/sy/sjqsj/202512/t20251222_4356494.html"
)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
#: 表图文件名形态（政府站 TRS 发布系统 W0 前缀）。
_TABLE_IMAGE_RE = re.compile(r"""W0\d+\.(?:png|jpe?g)""", re.IGNORECASE)
_TITLE_YEAR_RE = re.compile(r"（(\d{4})年）")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_DAY_RE = re.compile(r"^\d{1,2}$")
#: 中文月表头 → 月号（表头横排 一…十二）。
_CN_MONTH_NUM = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}
#: 校验闸门：升/降旗合理区间（分钟）。升旗≈日出 4:45-7:36，降旗≈日落
#: 16:49-19:47（北京全年极值附近留裕量）。
_RISE_WINDOW = (4 * 60, 8 * 60)
_LOWER_WINDOW = (15 * 60 + 30, 20 * 60 + 30)
#: 相邻两天时刻最大漂移（真表 ≤2 分钟/天，留裕量防 OCR 单格误读漏网）。
_MAX_DAY_DRIFT_MINUTES = 3
#: 种子（2026 全年人工逐格核对，744 值；来源见 tmp_flag_table/build_docs.py
#: 与 DESIGN/flag_schedule_snapshot_*.csv）。库表空时自动灌入。
#: 文件落 DESIGN/（随仓库分发；data/ 被 .gitignore 忽略不能放），查询时
#: 依次回退旧 data/ 路径与模块同目录（老部署/打包形态兼容）。
_SEED_CSV_CANDIDATES = (
    "DESIGN/flag_schedule_seed_2026.csv",
    "data/flag_schedule_seed_2026.csv",
    Path(__file__).with_name("flag_schedule_seed_2026.csv"),
)
_SEED_YEAR = 2026
#: 表图原始缓存目录（审计留档；测试重定向 tmp）。
_IMG_CACHE_DIR = Path("data/flag_schedule")


# ---------------------------------------------------------------- ORM

def _utcnow() -> datetime:
    """naive UTC（sqlite DateTime 列 naive 存取，见 train_cache._utcnow）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FlagScheduleRecord(Base):
    """升（降）旗时刻落库行（表 flag_schedule）。

    批次 = fetched_at 同值的一批行；只追加不改写，读取取每个 date 的
    最新 fetched_at 批次（同批重跑幂等由唯一约束 + INSERT OR IGNORE 吞掉）。
    """

    __tablename__ = "flag_schedule"
    __table_args__ = (
        UniqueConstraint(
            "date",
            "rise_time",
            "lower_time",
            "fetched_at",
            name="uq_flag_schedule_row",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, index=True)
    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    rise_time: Mapped[str] = mapped_column(String(8))  # "H:MM"
    lower_time: Mapped[str] = mapped_column(String(8))  # "H:MM"
    source: Mapped[str] = mapped_column(String(20))  # seed|ocr
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


_flag_engine = None


def get_flag_schedule_engine(settings=None):
    """进程级单例引擎；sqlite 相对路径自动建父目录（照 train_cache）。"""
    global _flag_engine
    if _flag_engine is None:
        settings = settings or get_settings()
        url = settings.flag_schedule_db_url
        if url.startswith("sqlite:///"):
            db_path = Path(url[len("sqlite:///"):])
            db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            connect_args=(
                {"check_same_thread": False} if url.startswith("sqlite") else {}
            ),
        )
        # 只建本模块的表：Base.metadata 其余表是 PG 专属类型，sqlite 建不了。
        Base.metadata.create_all(engine, tables=[FlagScheduleRecord.__table__])
        _flag_engine = engine
    return _flag_engine


# ------------------------------------------------------- 查询（读路径）

_flag_cache: dict[str, tuple[str, str]] = {}
_flag_cache_generation: int | None = None


def _load_latest_rows(session: Session) -> dict[str, tuple[str, str]]:
    """每个 date 取最新 fetched_at 批次（只追加模型的读口径）。

    全表量小（一年 365 行 × 批次数），按 fetched_at 升序扫一遍、晚行
    覆盖早行即得「每日期最新批次」映射。"""
    rows = session.execute(
        select(FlagScheduleRecord).order_by(FlagScheduleRecord.fetched_at)
    ).scalars()
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        out[r.date] = (r.rise_time, r.lower_time)
    return out


def _flag_map(settings=None) -> dict[str, tuple[str, str]]:
    """进程内缓存：表有新批次（max(id) 变化）才重扫全表。"""
    global _flag_cache, _flag_cache_generation
    settings = settings or get_settings()
    if not settings.flag_schedule_enabled:
        return {}
    try:
        engine = get_flag_schedule_engine(settings)
        with Session(engine) as session:
            gen = session.execute(func.max(FlagScheduleRecord.id)).scalar() or 0
        if gen != _flag_cache_generation or not _flag_cache:
            _ensure_seed(session_factory=sessionmaker(bind=engine))
            with Session(engine) as session:
                _flag_cache = _load_latest_rows(session)
                _flag_cache_generation = session.execute(
                    func.max(FlagScheduleRecord.id)).scalar() or 0
    except Exception:  # noqa: BLE001 —— 降级契约：读失败返回现有/空缓存
        logger.warning("flag_schedule 读库失败，沿用进程内缓存", exc_info=True)
    return _flag_cache


def get_flag_time(
    date_iso: str, category: str = "morning", *, settings=None
) -> time | None:
    """按日期 + 类别查升降旗时刻。

    category：morning/升旗 → 升旗时刻；evening/降旗 → 降旗时刻。
    查不到（无数据/关开关/坏行）恒 None —— 规划侧按默认日始排，不报错。
    """
    cat = str(category or "").strip().lower()
    if cat in ("morning", "升旗", "rise"):
        idx = 0
    elif cat in ("evening", "降旗", "lower", "striking"):
        idx = 1
    else:
        return None
    row = _flag_map(settings).get(date_iso)
    if row is None:
        return None
    raw = row[idx]
    m = _TIME_RE.match(raw)
    if not m:
        return None
    try:
        return time(int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


# ------------------------------------------------- 种子（库表空时灌入）

def _seed_rows(settings=None) -> list[dict]:
    """读种子 CSV（2026 全年人工核对值）：候选路径依次回退。"""
    del settings  # 种子路径与库位解耦（DESIGN/ 随仓库分发）
    path = next((p for p in _SEED_CSV_CANDIDATES if Path(p).exists()), None)
    if path is None:
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append({
                "year": int(row["year"]),
                "date": row["date"],
                "rise_time": row["rise_time"],
                "lower_time": row["lower_time"],
            })
    return out


def _ensure_seed(*, session_factory=None, settings=None) -> int:
    """表内没有种子年份的行时灌一次种子批次（source=seed，只追加）。

    幂等：已有该年份任何批次则跳过。"""
    if session_factory is None:
        session_factory = sessionmaker(
            bind=get_flag_schedule_engine(settings))
    rows = _seed_rows(settings)
    if not rows:
        return 0
    seed_year = rows[0]["year"]
    with session_factory() as session:
        exists = session.execute(
            select(func.count(FlagScheduleRecord.id)).where(
                FlagScheduleRecord.year == seed_year)
        ).scalar()
        if exists:
            return 0
        return insert_batch(rows, source="seed", session=session)


# ----------------------------------------------------- 抓取（写路径）

def _http_get(url: str, *, timeout: float, follow_redirects: bool = True) -> bytes:
    """浏览器 UA GET（政府站对脚本 UA 有 WAF，照 amap_client 口径）。"""
    resp = httpx.get(
        url,
        headers=_BROWSER_HEADERS,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )
    resp.raise_for_status()
    return resp.content


def _extract_table_image_url(html: bytes, page_url: str) -> str:
    """从公告页 HTML 提取表图 URL（TRS W0 前缀，相对页面目录）。"""
    text = html.decode("utf-8", errors="replace")
    m = _TABLE_IMAGE_RE.search(text)
    if not m:
        raise ValueError("公告页未找到嵌入表图（W0*.png/jpg）")
    base = page_url.rsplit("/", 1)[0]
    return f"{base}/{m.group(0)}"


def _ocr_image(image_path: Path) -> list[tuple[float, float, str]]:
    """OCR 表图 → [(x_center, y_center, text)]。rapidocr 懒导入。

    纵向分带跑：检测器对高图上半区整片漏检（1042×673 官图整幅跑只出
    下半，2026-11-14 实测），带间 10% 重叠 + 量化 (x,y,text) 去重拼回
    全表。2x 放大（LANCZOS）改善小字号识别；白底黑字印刷体免二值化。
    """
    from rapidocr_onnxruntime import RapidOCR  # 延迟导入：查询路径零依赖
    from PIL import Image
    import numpy as np

    img = Image.open(image_path)
    if img.width < 2000:
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    ocr = RapidOCR()
    raw: list[tuple[float, float, str]] = []
    h = img.height
    band = max(1, int(h * 0.55))
    step = max(1, int(h * 0.45))
    y0 = 0
    while y0 < h:
        y1 = min(h, y0 + band)
        crop = img.crop((0, y0, img.width, y1)).convert("RGB")
        result, _ = ocr(np.array(crop))
        for box, text, score in result or []:
            if not text or not str(text).strip():
                continue
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            raw.append((
                sum(xs) / len(xs),
                sum(ys) / len(ys) + y0,
                str(text).strip(),
            ))
        if y1 >= h:
            break
        y0 += step
    # 跨带去重：重叠带同一单元格会被两条带各识别一次（中心差几像素）——
    # 同文本且 (x,y) 近距（<8px）合并，否则保留。
    cells: list[tuple[float, float, str]] = []
    for x, y, t in raw:
        if any(
            ot == t and abs(ox - x) < 8 and abs(oy - y) < 8
            for ox, oy, ot in cells
        ):
            continue
        cells.append((x, y, t))
    return cells


def parse_grid_cells(
    cells: list[tuple[float, float, str]],
) -> list[dict]:
    """OCR 单元格 → [{month, day, rise, lower}]（"H:MM" 串）。

    纯函数（测试友好）。网格还原（2026-11-14 官图实测口径）：
    - 列定位以表头「升」「降」单元格为准（12 列升序 = 1-12 月）——
      月名（一…十二）OCR 误读率高（一 漏检、十→+），只作位置参考；
    - 缺位的升/降表头列按已检出列的月序线性回归补位（OCR 漏检容错）；
    - 数据行按 y 簇分行（日列数字锚行），行内按 x 归入升/降列簇；
    - 短月空格 = 无单元格（OCR 不吐空盒），按月天数校验阶段裁决。
    """
    if not cells:
        raise ValueError("OCR 未识别到任何文本")
    xs = sorted(c[0] for c in cells)
    ys = sorted(c[1] for c in cells)
    # 聚簇容差取「中位相邻距 × 0.4」：同行/同列内 OCR 盒中心抖动（几个
    # 像素）吸进一簇，行距/列距（中位距本身）保分开——容差大于行距会把
    # 相邻两行并成一行，小于抖动会把一行拆成多行。
    gaps = sorted(b - a for a, b in zip(xs, xs[1:]) if b - a > 1)
    y_gaps = sorted(b - a for a, b in zip(ys, ys[1:]) if b - a > 1)
    x_tol = (gaps[len(gaps) // 2] if gaps else 30.0) * 0.4
    y_tol = (y_gaps[len(y_gaps) // 2] if y_gaps else 20.0) * 0.4

    def _cluster(values: list[float], tol: float) -> list[float]:
        """一维聚簇，返回每簇中心（升序）。"""
        centers: list[list[float]] = []
        for v in sorted(values):
            if centers and v - centers[-1][-1] <= tol:
                centers[-1].append(v)
            else:
                centers.append([v])
        return [sum(c) / len(c) for c in centers]

    col_centers = _cluster([c[0] for c in cells], x_tol)
    row_centers = _cluster([c[1] for c in cells], y_tol)

    def _nearest(centers: list[float], v: float) -> int:
        return min(range(len(centers)), key=lambda i: abs(centers[i] - v))

    # 网格坐标：cell -> (行簇, 列簇)
    grid: dict[tuple[int, int], str] = {}
    for x, y, text in cells:
        grid[(_nearest(row_centers, y), _nearest(col_centers, x))] = text

    # 表头行 = 含 升/降/月/日 表头字的行簇（图最上缘区）
    header_rows = {
        r
        for (r, _c), t in grid.items()
        if t in ("月", "日", "升", "降")
    }
    if not header_rows:
        raise ValueError("未识别到表头（升/降/月/日），网格还原失败")

    def _header_cols(char: str) -> list[int]:
        """表头字（升/降）所在列簇号按 x 升序 = 1-12 月。

        OCR 漏检个别表头时：已检出列的 x 与其月序做最小二乘，缺位按
        回归期望值找最近未占用列簇补位（容差 = 0.6 个月距）。"""
        cs = sorted({
            c for (r, c), t in grid.items()
            if r in header_rows and t == char
        })
        if not cs:
            raise ValueError(f"表头未识别到任何「{char}」列")
        xs_det = [col_centers[c] for c in cs]
        n = len(xs_det)
        mean_i = (n - 1) / 2
        mean_x = sum(xs_det) / n
        var_i = sum((i - mean_i) ** 2 for i in range(n)) or 1.0
        cov = sum((i - mean_i) * (x - mean_x) for i, x in enumerate(xs_det))
        slope = cov / var_i  # 每月列距（px）
        intercept = mean_x - slope * mean_i
        full: list[int] = []
        used: set[int] = set()
        for m in range(12):
            expected = slope * m + intercept
            best = min(
                (c for c in cs if c not in used),
                key=lambda c: abs(col_centers[c] - expected),
                default=None,
            )
            if best is not None and abs(
                col_centers[best] - expected
            ) <= abs(slope) * 0.6:
                full.append(best)
                used.add(best)
                continue
            cand = min(
                (c for c in range(len(col_centers)) if c not in used),
                key=lambda c: abs(col_centers[c] - expected),
                default=None,
            )
            if cand is None or abs(col_centers[cand] - expected) > abs(
                slope
            ) * 0.6:
                raise ValueError(
                    f"表头「{char}」列缺位且无法补位（{m + 1}月）")
            full.append(cand)
            used.add(cand)
        return full

    rise_cols = _header_cols("升")
    lower_cols = _header_cols("降")
    if len(rise_cols) != 12 or len(lower_cols) != 12:
        raise ValueError("升/降表头列不足 12 个")

    # 日列 = 表头区以下、全图最左的数字列簇
    data_row_max = max(header_rows)
    day_col = min(
        c
        for (r, c), t in grid.items()
        if r > data_row_max and _DAY_RE.match(t) and t.isdigit()
    )
    # 日行定位（2026-11-14 官图实测）：OCR 会整格漏检个别日号（5/25/26/27
    # 四行日号全漏），但行序=日序——用「日号-行 y」线性回归给每个含时刻
    # 的行定日，漏号行照样还原；回归残差异常由校验闸门兜底。
    day_anchors = [
        (row_centers[r], int(t))
        for (r, c), t in grid.items()
        if c == day_col and r > data_row_max and t.isdigit()
    ]
    if len(day_anchors) < 2:
        raise ValueError("日列锚点不足，无法定位数据行")
    # 稳健回归：日号单元格偶发误读（2026-11-14 实测「26」→「2」）会把
    # 斜率拉平、相邻行四舍五入撞同一天——迭代剔残差（>0.6 天）重拟合。
    anchors = list(day_anchors)
    for _ in range(3):
        n_a = len(anchors)
        mean_y = sum(y for y, _ in anchors) / n_a
        mean_d = sum(d for _, d in anchors) / n_a
        var_y = sum((y - mean_y) ** 2 for y, _ in anchors) or 1.0
        cov_yd = sum((y - mean_y) * (d - mean_d) for y, d in anchors)
        slope_d = cov_yd / var_y
        intercept_d = mean_d - slope_d * mean_y
        keep = [
            (y, d)
            for y, d in anchors
            if abs(slope_d * y + intercept_d - d) <= 0.6
        ]
        if len(keep) == len(anchors) or len(keep) < 2:
            break
        anchors = keep
    if len(anchors) < 2:
        raise ValueError("日列锚点剔除误读后不足，无法定位数据行")

    time_by_row: dict[int, dict[int, str]] = defaultdict(dict)
    for (r, c), t in grid.items():
        if r > data_row_max and _TIME_RE.match(t):
            time_by_row[r][c] = t
    rows_out: list[dict] = []
    seen_md: dict[tuple[int, int], dict] = {}
    for r in sorted(time_by_row):
        day = round(intercept_d + slope_d * row_centers[r])
        if not 1 <= day <= 31:
            continue
        row_cells = time_by_row[r]
        for month in range(1, 13):
            rise = row_cells.get(rise_cols[month - 1])
            lower = row_cells.get(lower_cols[month - 1])
            # 时刻字形已在收集时过滤（_TIME_RE），非时刻文本（OCR 误读
            # 如「一」）不进行组——短月空格与误读统一交校验阶段按日历
            # 裁决（缺日→抓取失败，旧数据继续服务），绝不把脏文本落库。
            if rise is None and lower is None:
                continue
            key = (month, day)
            prev = seen_md.get(key)
            if prev is None:
                seen_md[key] = {
                    "month": month, "day": day,
                    "rise": rise, "lower": lower,
                }
            else:
                # 行簇拆分残留：同月日互补缺字段（回归残差极小下罕见，
                # 一旦发生以字段互补合并而非丢弃）。
                if prev["rise"] is None and rise is not None:
                    prev["rise"] = rise
                if prev["lower"] is None and lower is not None:
                    prev["lower"] = lower
    return list(seen_md.values())


def validate_rows(rows: list[dict], year: int) -> list[dict]:
    """校验闸门：不合格抛 ValueError（调用方不落库，旧数据继续可用）。"""
    import calendar

    by_month: dict[int, dict[int, dict]] = defaultdict(dict)
    for r in rows:
        m = r["month"]
        d = r["day"]
        if not 1 <= m <= 12 or not 1 <= d <= 31:
            raise ValueError(f"非法月日 {year}-{m}-{d}")
        if d in by_month[m]:
            raise ValueError(f"重复月日 {year}-{m}-{d}")
        by_month[m][d] = r

    def _try_parse(raw, win):
        """解析失败/越界 → None（交单格修复，不立即判死）。"""
        m = _TIME_RE.match(str(raw or ""))
        if not m:
            return None
        mins = int(m.group(1)) * 60 + int(m.group(2))
        return mins if win[0] <= mins <= win[1] else None

    repaired: list[str] = []
    parsed: dict[tuple[int, int], tuple[int | None, int | None]] = {}
    for month in range(1, 13):
        days = by_month.get(month, {})
        expect = calendar.monthrange(year, month)[1]
        missing = [d for d in range(1, expect + 1) if d not in days]
        if missing:
            raise ValueError(f"{year}-{month} 缺日: {missing[:5]}")
        extra = [d for d in days if d > expect]
        if extra:
            raise ValueError(f"{year}-{month} 多余日: {extra}")
        for d in range(1, expect + 1):
            r = days[d]
            parsed[(month, d)] = (
                _try_parse(r["rise"], _RISE_WINDOW),
                _try_parse(r["lower"], _LOWER_WINDOW),
            )

    # 单格修复（2026-11-14 官图实测「6:01」→「10:9」形态）：某日某字段
    # 解析失败/越界，且相邻两日同字段都在且互差 ≤ 2×日漂移上限（相邻
    # 真值变化平缓），取左邻值补格——漂移闸门随后照常整体复检。修不了
    # 仍然判死不落库。
    def _repair(month, d, idx, win, what):
        v = parsed[(month, d)][idx]
        if v is not None:
            return v
        left = parsed[(month, d - 1)][idx] if d - 1 >= 1 else None
        right = (
            parsed[(month, d + 1)][idx]
            if d + 1 <= calendar.monthrange(year, month)[1]
            else None
        )
        if left is not None and right is not None and abs(left - right) <= (
            _MAX_DAY_DRIFT_MINUTES * 2
        ):
            repaired.append(f"{year}-{month}-{d} {what}←{left}")
            return left
        raise ValueError(
            f"{year}-{month}-{d} {what} 无法解析且不可修复: "
            f"{by_month[month][d][('rise', 'lower')[idx]]!r}"
        )

    total = 0
    for month in range(1, 13):
        prev_rise = prev_lower = None
        for d in range(1, calendar.monthrange(year, month)[1] + 1):
            rise = _repair(month, d, 0, _RISE_WINDOW, "升旗")
            lower = _repair(month, d, 1, _LOWER_WINDOW, "降旗")
            if prev_rise is not None:
                if abs(rise - prev_rise) > _MAX_DAY_DRIFT_MINUTES:
                    raise ValueError(
                        f"{year}-{month}-{d} 升旗漂移 {abs(rise - prev_rise)}min")
                if abs(lower - prev_lower) > _MAX_DAY_DRIFT_MINUTES:
                    raise ValueError(
                        f"{year}-{month}-{d} 降旗漂移 {abs(lower - prev_lower)}min")
            prev_rise, prev_lower = rise, lower
            parsed[(month, d)] = (rise, lower)
            total += 1
    if total != sum(calendar.monthrange(year, m)[1] for m in range(1, 13)):
        raise ValueError(f"总行数不符: {total}")
    if repaired:
        logger.warning(
            "flag_schedule: OCR 单格修复 %d 处: %s",
            len(repaired), "; ".join(repaired),
        )
    # 中间结构 → 落库行（分钟 → "H:MM"）
    def _fmt(mins):
        return f"{mins // 60}:{mins % 60:02d}"

    out = []
    for month in range(1, 13):
        for d in sorted(k[1] for k in parsed if k[0] == month):
            rise, lower = parsed[(month, d)]
            out.append({
                "year": year,
                "date": _date(year, month, d).isoformat(),
                "rise_time": _fmt(rise),
                "lower_time": _fmt(lower),
            })
    return out


def insert_batch(
    rows: list[dict], *, source: str,
    session: Session | None = None, settings=None,
) -> int:
    """只追加写入一个批次（fetched_at 同值）；同批重跑幂等（OR IGNORE）。"""
    own = session is None
    if own:
        session = Session(get_flag_schedule_engine(settings))
    try:
        fetched_at = _utcnow()
        n = 0
        for r in rows:
            stmt = sqlite_insert(FlagScheduleRecord).values(
                year=r["year"],
                date=r["date"],
                rise_time=r["rise_time"],
                lower_time=r["lower_time"],
                source=source,
                fetched_at=fetched_at,
            ).on_conflict_do_nothing()
            result = session.execute(stmt)
            n += result.rowcount or 0
        session.commit()
        return n
    finally:
        if own:
            session.close()


def write_snapshot(rows: list[dict], settings=None) -> Path:
    """DESIGN 目录快照 CSV（同日重跑幂等覆盖；只追加口径在库不在文件）。"""
    settings = settings or get_settings()
    snap_dir = Path(settings.flag_schedule_snapshot_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"flag_schedule_snapshot_{_date.today().isoformat()}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["year", "date", "rise_time", "lower_time", "source"])
        for r in sorted(rows, key=lambda x: x["date"]):
            w.writerow([r["year"], r["date"], r["rise_time"], r["lower_time"],
                        r.get("source", "ocr")])
    return path


def fetch_and_store(url: str | None = None, *, settings=None) -> dict:
    """抓取公告页 → 表图 OCR → 校验 → 落库（新批次）+ DESIGN 快照。

    任何一步失败抛异常（调用方/CLI 捕获记 WARNING）；校验不过不落库，
    库内旧批次继续服务。返回摘要 dict（CLI 打印）。
    """
    settings = settings or get_settings()
    url = url or settings.flag_schedule_source_url
    timeout = settings.flag_schedule_timeout_seconds
    html = _http_get(url, timeout=timeout)
    year_m = _TITLE_YEAR_RE.search(html.decode("utf-8", errors="replace"))
    year = int(year_m.group(1)) if year_m else _date.today().year + 1
    img_url = _extract_table_image_url(html, url)
    img_bytes = _http_get(img_url, timeout=timeout)
    cache_dir = _IMG_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    img_path = cache_dir / f"{year}_{img_url.rsplit('/', 1)[-1]}"
    img_path.write_bytes(img_bytes)

    cells = _ocr_image(img_path)
    parsed = parse_grid_cells(cells)
    rows = validate_rows(parsed, year)
    inserted = insert_batch(rows, source="ocr", settings=settings)
    snapshot = write_snapshot([{**r, "source": "ocr"} for r in rows],
                              settings=settings)
    return {
        "year": year,
        "image": str(img_path),
        "rows": len(rows),
        "inserted": inserted,
        "snapshot": str(snapshot),
    }


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="天安门升（降）旗时刻抓取入库（官方公告页 → 表图 OCR → 落库）")
    parser.add_argument("url", nargs="?", default=None,
                        help="公告页 URL（默认 settings.flag_schedule_source_url）")
    args = parser.parse_args(argv)
    n = _ensure_seed()
    if n:
        print(f"seed inserted: {n} rows")
    try:
        summary = fetch_and_store(args.url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("flag_schedule 抓取失败：库内旧批次继续可用", exc_info=True)
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
