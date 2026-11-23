"""规划主链路的真实 E2E（真浏览器 + 真 uvicorn + 真求解器）。

这一批用例是**基础设施的样板**：后续任何前端/接口改动，按同样的形状往下加
（见 README「怎么加一条用例」）。它们刻意不复刻单测的实现细节，只钉三件事：

1. 页面在真浏览器里能起来、没有 JS 报错；
2. 用户点下去之后，**发出去的请求**里带全了信息，界面真的出了行程；
3. 反面：信息不足时该问还得问——防止「修一个弹窗」把闸门改松到永不追问。
"""

import time

import pytest

# 没装 Playwright 的机器（大多数单测环境）不该让整个 tests/ 收集失败
pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Error as PlaywrightError  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

pytestmark = pytest.mark.e2e

PLAN_TIMEOUT = 180_000  # 求解器 + DB 冷启动，给足；超时说明真有问题


def _wait_days(page, count: int, timeout: int = PLAN_TIMEOUT) -> None:
    page.wait_for_function(
        "n => document.querySelectorAll('#flow-plan .day-h').length >= n",
        arg=count,
        timeout=timeout,
    )


def test_h5_boots_without_js_errors(e2e):
    e2e.goto()
    expect(e2e.page.locator("#planStart")).to_be_visible()
    # 城市下拉来自 PLAN_CITIES，真渲染出来才算页面可用
    expect(e2e.page.locator("#planStartCity option")).not_to_have_count(0)
    assert e2e.page_errors == [], f"页面抛异常：{e2e.page_errors}"
    assert e2e.unexpected_console_errors() == [], (
        f"控制台报错：{e2e.unexpected_console_errors()}"
    )


def test_form_start_renders_itinerary_and_sends_date(e2e):
    """表单路线 + 日期齐全：不弹行前卡，出行程，且请求里真的有 start_date。"""
    e2e.goto()
    page = e2e.page
    page.select_option("#planStartCity", "上海")
    page.select_option("#planEndCity", "杭州")
    page.fill("#planEndDays", "2")
    page.fill("#planStartDate", "2026-12-05")
    page.click("#planStart")

    expect(page.locator("#intakeModal")).to_be_hidden(timeout=10_000)
    _wait_days(page, 2)

    starts = [p.get("start_date") for p in e2e.payloads("/api/v1/plan/start")]
    assert "2026-12-05" in starts, f"请求未带表单日期，实际 payload: {starts}"


def test_text_start_with_date_skips_intake(e2e):
    """纯文字开局（城市/天数/日期都在句子里）：同样不该弹卡。"""
    e2e.goto()
    page = e2e.page
    page.fill("#planInput", "杭州 2 天，12月5日出发")
    page.click("#planSend")

    expect(page.locator("#intakeModal")).to_be_hidden(timeout=15_000)
    _wait_days(page, 2)

    # 文字开局的日期允许后端从句子里解析（请求里不一定带 start_date），
    # 所以断言落在**用户看得见的地方**：第 1 天天头就是句子里那天。
    head = page.locator("#flow-plan .day-h").first.inner_text()
    assert "2026-12-05" in head, f"第 1 天没落在文字给的日期上：{head}"


_SW_STATE_JS = """async () => {
    const res = await fetch('/h5/sw.js', {cache: 'no-store'});
    const text = await res.text();
    const m = text.match(/const VERSION\\s*=\\s*'([^']+)'/);
    return {version: m ? m[1] : null, caches: await caches.keys()};
}"""


def _wait_controller(page, timeout: int = 30_000) -> None:
    """等 SW 接管页面，且**容忍接管瞬间的整页重载**。

    产品在 controllerchange 时会 location.reload() 换新壳（见 index.html 里
    swReloading 那段）。重载会把当前执行上下文销毁，evaluate 抛
    "Execution context was destroyed" —— 那是预期行为，等新上下文即可。
    """
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        try:
            if page.evaluate(
                "() => !!(navigator.serviceWorker"
                " && navigator.serviceWorker.controller)"
            ):
                return
        except PlaywrightError:
            try:
                page.wait_for_load_state("load", timeout=10_000)
            except PlaywrightError:
                pass
        page.wait_for_timeout(200)
    raise AssertionError("Service Worker 30s 内未接管页面")


def _read_sw_state(page, attempts: int = 20) -> dict:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            state = page.evaluate(_SW_STATE_JS)
            if state.get("version"):
                return state
        except PlaywrightError as exc:
            last = exc
            try:
                page.wait_for_load_state("load", timeout=10_000)
            except PlaywrightError:
                pass
        page.wait_for_timeout(200)
    raise AssertionError(f"读不到 sw.js 的 VERSION（最后一次错误：{last}）")


def test_service_worker_precaches_current_shell(e2e):
    """Service Worker 真的注册成功、预缓存真的建起来了。

    这一层以前完全没测：改完前端不 bump `sw.js` 的 VERSION，老壳会一直赖在
    用户浏览器里 —— 单测和 API 测试都看不见。这里至少钉住「SW 能装、缓存名
    与服务端当前版本一致」；VERSION 该不该 bump 仍需人工判断（见 README）。
    """
    e2e.goto()
    page = e2e.page
    _wait_controller(page)
    state = _read_sw_state(page)
    version = state["version"]
    cache_keys = state["caches"]
    assert f"chinatrip-h5-{version}" in cache_keys, (
        f"当前版本 {version} 的缓存没建起来，实际：{cache_keys}"
    )
    assert e2e.unexpected_console_errors() == [], (
        f"控制台报错：{e2e.unexpected_console_errors()}"
    )


def test_text_start_without_date_still_asks(e2e):
    """负例：只给城市和天数、没有任何日期 → 必须弹行前卡。

    没有这条，闸门被改松（永不追问）也不会被发现。
    """
    e2e.goto()
    page = e2e.page
    page.fill("#planInput", "杭州 2 天")
    page.click("#planSend")

    expect(page.locator("#intakeModal")).to_be_visible(timeout=30_000)
    # 卡上要能改日期，否则「追问」也没用
    expect(page.locator("#intakeArrDate")).to_be_visible()
