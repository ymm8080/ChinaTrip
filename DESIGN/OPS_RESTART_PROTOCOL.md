# chinatrip H5 服务重启协议 — http_500 防再发（2026-11-03）

## 事故回放（防的是哪三件事）

1. **裸起进程**：8000 于 18:50 被手动裸起（没走 schtasks 的 cmd，**没有日志重定向**），traceback 无处落盘；静态日志停在 11-02 22:41 造成"服务健康"假象。
2. **坏树加载**：启动时刻恰逢 74fdcb8 误还原 hunks → ce8f2af 三方合并的坏中间态代码，无人拦截就把 WIP 装进了用户在用的端口。
3. **验证只看 /health**：启动后没人发过真实 /plan message——主车道/快车道全 500，直到用户报障才发现。

## 新规（对所有会话生效，含并行会话）

1. **重启必须走脚本，禁止裸起 uvicorn**：

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File "D:\CHINATRIP\CHINATRIP CODES\ops\restart_h5.ps1" [-Tests] [-FullSmoke] [-Force]
   ```

   - 门禁①：树上 `CHINATRIP CODES` 有 **modified .py**（合并/在飞 WIP）→ **拒绝重启**，除非显式 `-Force`。用户在用的端口永远不做"先装再修"。
   - 门禁②（可选 `-Tests`）：动手前先跑 `test_plan_api + test_plan_agent` 定向门禁（163 测，~1 分钟）。
   - 收口：自动跑 `ops/smoke_h5.py`；`-FullSmoke` 会真发 `plan/start → 主车道 message → 快车道 message` 三连（就是本次 500 的车道组合）。
   - 日志带 trail：杀进程前打印 pid + CreationDate，避免陈 PID 误杀。

2. **日志引力法则**：一切 uvicorn 进程必须由 schtasks cmd 起（自动 `>> D:\chinatrip\uvicorn_h5_1018e*.log 2>&1`）。判别法：某端口 health 200 但对应日志在进程启动 1 分钟后仍无新行 → 该进程是裸起，立即杀掉并走脚本重启。

3. **健康 ≠ /health**：/health 只证明进程活着，不证明 message 车道可用。凡用户报"发送失败"，或怀疑服务态，直接跑：

   ```powershell
   python "D:\CHINATRIP\CHINATRIP CODES\ops\smoke_h5.py" --ports 8000 8443 --full
   ```

4. **交付前置**：任何会话改完 plan/solver 运行路径，要么提交+验证，要么明确声明"未验证"且不重启服务；并行协作期间对共享Ports 的重启一律先 commit。

## 辅助监测

- AutoClaw monitor 常驻监听两份 uvicorn 日志中的 usage 5xx 行（`"status_code": 5xx`），命中即通知会话。
- 亦可人工:`ops/smoke_h5.py`（不带 --full 时零 LLM 成本，秒回）。
