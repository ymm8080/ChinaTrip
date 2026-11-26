# 真实 E2E（真浏览器 + 真服务）

单测钉的是函数契约，这里钉的是**用户点下去之后会发生什么**。两者不互相替代：
`tests/test_*.py` 继续跑逻辑，`tests/e2e/` 负责回答「浏览器里真的对吗」。

## 一条命令

```bash
bash ops/e2e.sh                 # 全部用例
bash ops/e2e.sh -k plan_flow    # 挑着跑
E2E_HEADED=1 bash ops/e2e.sh    # 看着它点（排查用）
```

首次运行会装 Chromium（已装在 仓库根 `../.pw-browsers`，约 250MB，已 gitignore）。
单测默认**不跑** e2e（`pyproject.toml` 里 `addopts = -m 'not e2e'`），耗时和机器要求差两个量级。

## 什么是真的，什么是桩

| 环节 | E2E 里 | 说明 |
|---|---|---|
| Chromium / DOM / CSS / 事件 | **真的** | Playwright，手机视口 390×844 |
| Service Worker / 缓存 | **真的** | 每个用例全新 context，不跨用例复用缓存 |
| uvicorn / 中间件 / 路由 | **真的** | 独立进程，不是 `TestClient` |
| 静态页 `/h5/` | **真的** | 直接读 `app/static/`，改前端立刻反映 |
| 行程求解器 / 数据库 | **真的** | 真实 cpsat + 真实 sqlite 状态库（独立的 `data/e2e_state.db`，不碰真实库） |
| LLM | **桩**（`tests/e2e/server.py`） | 恒定 JSON。真模型会 429、会抖，让 E2E 变成噪声 |
| 高德/腾讯/百度 | **关掉** | 空 key ⇒ 走 DB POI，正好覆盖降级路径；页面探 `/api/v1/amap/*` 的 503 已在允许清单里 |

要验「真模型下也走得通」：`E2E_LLM=live bash ops/e2e.sh`（慢很多，别放进日常回归）。

## 怎么加一条用例（后续都按这个形状）

1. 打开 `tests/e2e/test_plan_flow.py`，照现有用例写：

```python
def test_xxx(e2e):
    e2e.goto()  # 打开 /h5/
    page = e2e.page
    page.fill("#planInput", "杭州 3 天，12月5日出发")
    page.click("#planSend")

    # ① 界面断言：用户看得见的东西
    expect(page.locator("#intakeModal")).to_be_hidden()
    page.wait_for_function(
        "n => document.querySelectorAll('#flow-plan .day-h').length >= n",
        arg=3,
        timeout=180_000,
    )

    # ② 报文断言：界面对了但请求缺字段，也是 bug 的另一半
    payloads = e2e.payloads("/api/v1/plan/start")
    assert payloads, "没发请求"

    # ③ 失败时的证据已自动落盘（截图 + 控制台 + 全部请求）
```

2. 新开一个文件也行：`tests/e2e/test_<流程>.py`，开头 `pytestmark = pytest.mark.e2e`，
   并保留 `pytest.importorskip("playwright.sync_api")`（没装浏览器的机器不该让整个 `tests/` 收集失败）。

3. 跑 `bash ops/e2e.sh -k 新用例名`，绿了再提交。

## 写法上必须守的三条

1. **必须有负例。** 只写「信息给足 → 不弹卡」会诱导把闸门改松到永不追问；
   配套写一条「信息不足 → 必须追问」，两条一起才叫需求被钉住。
2. **断言落在用户看得见的地方**（天头日期、卡片数量、按钮可见），
   或者落在发出去的报文上；不要去断言内部变量、DOM class 细节、接口字段顺序。
3. **不要 sleep。** 用 `expect(...)` / `wait_for_function`，Playwright 自带轮询。
   写死 `sleep(5)` 的用例在慢机器上必然假红。

## 失败怎么查

`tests/e2e/artifacts/` 下按用例名留三样：

- `<用例>.png` —— 失败瞬间的整页截图
- `<用例>.log` —— 页面 URL、控制台错误、JS 异常、本次全部 API 请求
- `server.log` —— 后端进程日志（起不来时先看这个）

## 已知边界

- 只跑 Chromium。Safari/iOS WebView 的差异（日期控件、SW 行为）不在覆盖内——
  移动端真机问题仍需要真机复现。
- 不覆盖支付、短信、外部跳转（需要真实外部账号/回调）。
- 后端 LLM 是桩：**模型话术类**问题（回复措辞、抽取质量）E2E 测不出来，仍靠单测 + 人工。
