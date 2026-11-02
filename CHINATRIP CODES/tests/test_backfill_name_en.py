"""backfill_name_en 作业测试（FakeAdapter/FakeFactory，无 DB 无网络）。"""

import asyncio

from app.jobs import backfill_name_en as job
from app.models import Poi


class FakeAdapter:
    def __init__(self, replies: dict[str, str], fail_names: set[str] | None = None):
        self.replies = replies
        self.fail_names = fail_names or set()
        self.calls: list[str] = []

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        user = messages[1].content
        name = [ln for ln in user.splitlines() if ln.startswith("中文名：")][0][4:]
        self.calls.append(name)
        if name in self.fail_names:
            raise RuntimeError("boom")
        return type("R", (), {"content": self.replies.get(name, '{"en":null}')})()


class FakeSession:
    def __init__(self, store):
        self._store = store
        self.committed = False

    def get(self, model, id):
        return self._store.get(id)

    def query(self, model):
        return self

    def filter(self, *a, **kw):
        return self

    def all(self):
        return list(self._store.values())

    def commit(self):
        self.committed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeFactory:
    def __init__(self, rows):
        self._store = {r.id: r for r in rows}

    def __call__(self):
        return FakeSession(self._store)


def _row(**kw):
    base = {
        "id": "x1",
        "source": "histown",
        "city": "苏州",
        "name_zh": "周庄镇",
        "name_en": None,
        "tags": ["中国历史文化名镇"],
        "status": "active",
    }
    base.update(kw)
    r = Poi()
    for k, v in base.items():
        setattr(r, k, v)
    r.id = base["id"]
    return r


def _run(rows, adapter):
    factory = FakeFactory(rows)
    stats = asyncio.run(
        job.backfill_name_en(
            factory, adapter, sources=["histown"], limit=0, concurrency=4
        )
    )
    return stats, factory


def test_fill_and_validate():
    row = _row()
    adapter = FakeAdapter({"周庄镇": '{"en":"Zhouzhuang Town"}'})
    stats, _ = _run([row], adapter)
    assert stats["filled"] == 1 and stats["rejected"] == 0
    assert row.name_en == "Zhouzhuang Town"


def test_reject_cjk_same_and_long():
    rows = [
        _row(id="a", name_zh="某某镇"),
        _row(id="b", name_zh="某某村"),
        _row(id="c", name_zh="某某寨"),
    ]
    adapter = FakeAdapter(
        {
            "某某镇": '{"en":"某某 Town"}',  # CJK → reject
            "某某村": '{"en":"某某村"}',  # same_as_source → reject
            "某某寨": '{"en":"' + "A" * 170 + '"}',  # too_long → reject
        }
    )
    stats, _ = _run(rows, adapter)
    assert stats["filled"] == 0 and stats["rejected"] == 3


def test_only_fill_empty_and_errors_continue():
    row = _row(name_en="Existing Town")
    adapter = FakeAdapter({"周庄镇": '{"en":"Zhouzhuang Town"}'}, fail_names={"周庄镇"})
    stats, _ = _run([row], adapter)
    # 已有 name_en 的行不该发起调用（select 阶段已过滤），fail 也不炸
    assert adapter.calls == [] and stats["errors"] == 0
