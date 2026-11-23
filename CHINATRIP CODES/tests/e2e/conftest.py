"""E2E 夹具：真起一个 uvicorn（tests/e2e/server.py）+ 真 Chromium。

设计要点（这几条是「真 E2E」与「写死断言」的分界）：
1. 服务是真进程：走真实中间件、真实静态资源、真实 sqlite/PG，不是 TestClient。
2. 浏览器每个用例一个全新 context：localStorage / Service Worker 不跨用例残留。
   —— 这条正好能抓到「改了前端没 bump SW 版本」这类只在老缓存里复现的问题。
3. 用例可以断言**发出去的报文**（e2e.api_calls），不只看界面表现：
   界面没弹窗但请求里缺字段，属于同一类 bug 的另一半。
4. 失败自动留截图 + 控制台日志到 tests/e2e/artifacts/，别让 E2E 红了没法查。
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ARTIFACTS = HERE / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)

# 仓库自带的浏览器目录（安装时用 PLAYWRIGHT_BROWSERS_PATH=<repo>/.pw-browsers）。
# 不写死 C:\Users\...\ms-playwright：那台机器上装不进去（权限），也污染用户目录。
_LOCAL_BROWSERS = ROOT.parent / ".pw-browsers"
if _LOCAL_BROWSERS.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(_LOCAL_BROWSERS))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_health(base_url: str, proc: subprocess.Popen, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"E2E 服务进程提前退出（code={proc.returncode}），"
                "见 tests/e2e/artifacts/server.log"
            )
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=2) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    raise RuntimeError("E2E 服务 90s 内未起来，见 tests/e2e/artifacts/server.log")


@pytest.fixture(scope="session")
def server_url():
    port = _free_port()
    env = dict(os.environ)
    env.update(
        {
            "E2E_PORT": str(port),
            "PYTHONPATH": str(ROOT),
            "PYTHONUNBUFFERED": "1",
        }
    )
    log_path = ARTIFACTS / "server.log"
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "server.py")],
        cwd=str(ROOT),
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_health(base, proc)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


@pytest.fixture(scope="session")
def _playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def _browser(_playwright):
    # E2E_HEADED=1 → 开有头浏览器，肉眼看它怎么点（排查用）
    headed = os.environ.get("E2E_HEADED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    browser = _playwright.chromium.launch(headless=not headed)
    yield browser
    browser.close()


@dataclass
class E2E:
    """用例拿到的手柄：浏览器页面 + 拿得到的网络/控制台证据。"""

    page: object
    base_url: str
    api_calls: list = field(default_factory=list)
    console_errors: list = field(default_factory=list)
    page_errors: list = field(default_factory=list)

    def goto(self, path: str = "/h5/") -> None:
        self.page.goto(self.base_url + path, wait_until="domcontentloaded")

    def payloads(self, path_contains: str) -> list[dict]:
        out = []
        for call in self.api_calls:
            if path_contains not in call["url"]:
                continue
            try:
                out.append(json.loads(call["body"] or "{}"))
            except json.JSONDecodeError:
                continue
        return out

    def unexpected_console_errors(self) -> list[str]:
        """扣掉「已声明的降级」后的控制台错误。

        E2E 里图商 key 是刻意清空的（否则一条用例要等真实地图外呼，还会烧配额），
        页面启动照例会探 /api/v1/amap/*，拿到 503 是**预期中的降级**，不是缺陷。
        除这个前缀以外的一切报错都必须为零——否则「页面能开」就失去意义。
        """
        out = []
        for err in self.console_errors:
            url = err.get("url") or ""
            if "/api/v1/amap/" in url:
                continue
            out.append(f"{err.get('text')} @ {url}")
        return out


@pytest.fixture
def e2e(_browser, server_url, request):
    # 手机视口：产品主战场是 H5，桌面视口会掩盖换行/遮挡类问题
    context = _browser.new_context(
        viewport={"width": 390, "height": 844},
        is_mobile=True,
        has_touch=True,
        locale="zh-CN",
        device_scale_factor=2,
    )
    page = context.new_page()
    handle = E2E(page=page, base_url=server_url)

    def _on_request(req):
        if "/api/" in req.url:
            handle.api_calls.append({"url": req.url, "body": req.post_data})

    page.on("request", _on_request)
    page.on(
        "console",
        lambda msg: handle.console_errors.append(
            {"text": msg.text, "url": (msg.location or {}).get("url", "")}
        )
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda exc: handle.page_errors.append(str(exc)))

    request.node._e2e_handle = handle
    try:
        yield handle
    finally:
        context.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


@pytest.fixture(autouse=True)
def _artifact_on_failure(request):
    yield
    handle = getattr(request.node, "_e2e_handle", None)
    failed = any(
        getattr(request.node, f"rep_{when}", None) is not None
        and getattr(request.node, f"rep_{when}").failed
        for when in ("setup", "call", "teardown")
    )
    if not failed or handle is None:
        return
    slug = request.node.name.replace("/", "_")
    try:
        handle.page.screenshot(path=str(ARTIFACTS / f"{slug}.png"), full_page=True)
    except Exception:  # noqa: BLE001 - 截图失败不该掩盖真正的失败
        pass
    (ARTIFACTS / f"{slug}.log").write_text(
        "URL: "
        + str(getattr(handle.page, "url", ""))
        + "\n\n-- console errors --\n"
        + "\n".join(
            f"{e.get('text')} @ {e.get('url')}" for e in handle.console_errors
        )
        + "\n\n-- page errors --\n"
        + "\n".join(handle.page_errors)
        + "\n\n-- api calls --\n"
        + json.dumps(handle.api_calls, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
