# 自动化续跑待办（2026-10-31 会话收尾，每 5 分钟检查一轮）

> 每轮运行：按顺序找第一个未勾的项做，做完勾掉并在「运行日志」追加一行；全部勾完则只追加「ALL DONE」不再动作。
> 硬规矩：**不 push**；**不删任何文件**（第 7 项杂物清理由用户拍板，不在本自动化范围）；提交只在全量门禁绿时做。
> 并行会话可能同时在改 `app/services/agent/plan.py` 等文件——门禁失败若只落在 plan_agent/plan_api/city_days/engine_constraints 且 `git status` 显示 plan.py 仍在修改中，视为在途干扰：记一次重试，最多 3 次后标 BLOCKED 等人。

## 待办

- [x] **T1 重启 uvicorn 8000 / 8443**（进程早于今天 poi_classify/poi_seed 改动，跑的旧代码）
  - 8000：`cmd /c "D:\chinatrip\dev_server.cmd restart"`，再 `cmd /c "D:\chinatrip\dev_server.cmd status"`
  - 8443：先按命令行匹配杀旧进程（PowerShell：`Get-CimInstance Win32_Process | ? { $_.CommandLine -like '*uvicorn*--port 8443*' } | % { Stop-Process -Id $_.ProcessId -Force }`），再在 `D:\CHINATRIP\CHINATRIP CODES` 目录后台拉起：`.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile D:\chinatrip\h5key.pem --ssl-certfile D:\chinatrip\h5cert.pem`
  - 验证靠响应形状不靠日志：`curl.exe --ssl-no-revoke -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/docs` 与 `https://127.0.0.1:8443/docs` 均 200
- [x] **T2 全量门禁**：`cd "D:/CHINATRIP/CHINATRIP CODES" && .venv/Scripts/python -m pytest -q -p no:cacheprovider --cov=app --cov-fail-under=75`（约 3 分钟）。结果（passed/failed 数、覆盖率、失败清单）写进运行日志。绿 → 勾掉；红且属在途干扰 → 记重试次数不勾；红且失败落在 poi_classify/poi_seed/import_chinatravel/heuristics 相关 → 标 BLOCKED 并把失败断言贴进日志
- [x] **T3 分组提交（仅 T2 绿后；不 push）**，Chinese conventional commit，按仓库近期风格：
  1. `git add "CHINATRIP CODES/app/services/poi_classify.py" "CHINATRIP CODES/app/services/poi_seed.py" "CHINATRIP CODES/app/jobs/import_chinatravel.py" "CHINATRIP CODES/ops/move_rest_to_pois.py" "CHINATRIP CODES/ops/recat_hotels_in_pois.py" "CHINATRIP CODES/tests/test_poi_seed.py" "CHINATRIP CODES/tests/test_heuristics_enrich.py" "CHINATRIP CODES/tests/test_import_chinatravel.py"` → 提交信息主题：`fix(pois): 住宿行归口——poi_classify 住宿名称守卫（hotel 优先于裸「园」hint）、normalize_category 加 hotel 映射、import_chinatravel 住宿名强制 category=hotel 落库（restaurant 侧仍跳过）、move_rest_to_pois kind=hotel 强制、ops/recat_hotels_in_pois 可重跑归类（只改类别不隐藏）；回归：test_accommodation_names_guard_to_hotel / test_is_accommodation_tokens / test_normalize_category_hotel_subtype / test_accommodation_rows_forced_hotel_for_attraction / test_accommodation_rows_skipped_for_restaurant_kind`，正文写清根因（餐厅表搬移链 GLM kind=hotel 的 subtype 经旧 normalize 落 None，再被裸「园」hint 误归 park/nature，单日污染约 1500 行）与存量处置（3,753 行 hotel 全 active；11 项剧场/码头子点位改 entertainment；106 组普通地方性公园软删维持）
  2. `git add "DESIGN/POIS_DATASOURCE.md" "CHINATRIP CODES/ops/parks_ex_major_lists_2026-10-31.md" "CHINATRIP CODES/ops/parks_cleanup_proposal_2026-10-31.md" "CHINATRIP CODES/ops/parks_cleanup_executed_2026-10-31.md" "CHINATRIP CODES/ops/parks_nonpark_cleanup_executed_2026-10-31.md" "CHINATRIP CODES/ops/parks_hotel_recategory_executed_2026-10-31.md" "CHINATRIP CODES/ops/scheduler_todo_2026-10-31.md"` → 主题：`docs(pois): 公园池清洗记录与酒店星级 backlog——四类大名单排除后公园名单/三档清理提案/三份执行记录（含用户口径修正：酒店不隐藏只归类、场馆改娱乐），POIS_DATASOURCE §3.2 #12 旅游星级饭店入 backlog（落点 tags+tags_source、词表 star_N、数据源两轨）`
  - 注意：`git status` 里并行会话在途的 `app/services/pg_state.py`、`app/static/*`、`tests/test_pg_state.py`、`test_rain_swap_hard.py`、`test_state_readthrough.py`、`DESIGN/INDEX.md`、`travel_agent_system_design V2.5.md`、`app/services/agent/plan.py` **一律不加**。`poi_seed.py` 里并行会话加的「酒店/宾馆/民宿」键与本轮改动同文件，随第 1 组一起提交即可（已被测试覆盖）
- [x] **T4 补 NULL 分类**：`cd "D:/CHINATRIP/CHINATRIP CODES" && .venv/Scripts/python -m app.jobs.enrich_heuristics --dry-run --limit 5` 先看样例合理，再 `.venv/Scripts/python -m app.jobs.enrich_heuristics --limit 2000`；之后 `.venv/Scripts/python ops/recat_hotels_in_pois.py` 扫一遍。把 stats 与 `select category, count(*) from pois where status='active' group by 1` 前后对比写进日志
- [x] **T5 餐厅搬移清零**：`cd "D:/CHINATRIP/CHINATRIP CODES" && .venv/Scripts/python ops/move_rest_to_pois.py --concurrency 2`（剩 3 个目标，需 .env 里 GLM key）；完成后再跑一次 `ops/recat_hotels_in_pois.py`；日志记 `select count(*) from restaurants where source='chinatravel' and cuisine is null` 前后值

不在本自动化范围（用户另行拍板）：第 6 项酒店星级打标（已入 DESIGN backlog）、第 7 项仓库根杂物清理（删除类操作）。

## 运行日志

- 2026-11-02 23:16 run#1 **T1 DONE**：8000 经 dev_watch.py restart 重启（旧树 16608/26400 已杀，新 detached pid 10380，监听 pid 20892）；8443 经 PowerShell 内联杀旧进程后同参数拉起（新树 8812→10740，监听 pid 10740；`powershell -File` 在本机静默返回 -1 但动作已生效，改用 `-Command` 内联验证）。验证：`/docs` 8000 ×3 = 200、8443 = 200，8000 openapi 100 路由。cmd 包装 `dev_server.cmd restart` 在 Git Bash 下不传参，直接调 `.venv/Scripts/python.exe ../scripts/dev_watch.py restart` 可用。
- 2026-11-02 23:25 run#1 **T2 重试 1/3（在途干扰）**：8 failed / 1990 passed，覆盖率 82.54%（≥75 过线）。失败全在并行会话活跃区——test_plan_agent ×2（cityless wishlist 吸收/钉选）、test_link_sites ×3（十八梯心愿项为 None，经 PlanningAgent 走同一心愿流）、test_priority_early ×3（抵离城救援 tier1 梯度，对应刚提交的 747ddc9/d0c7441 系列）；`git status` 在途仅 plan.py/solver.py/test_plan_agent.py，plan.py 于测试运行中 23:23:50 又被改写。无一失败触及 poi_classify/poi_seed/import_chinatravel/heuristics。**T3 受「T2 绿」闸门不动**。
- 2026-11-02 23:25 run#1 **T3 范围修订**：并行会话同步提交 7b70bf4 已收编本轮代码+测试（poi_classify 守卫 / poi_seed hotel 映射 / import_chinatravel / 三个测试文件）与 DESIGN（POIS_DATASOURCE §3.2 #12），并注明「未跟踪文件（ops 工具脚本/parks_*.md 运维记录）一律不动」。T3 第 1 组只剩 `ops/move_rest_to_pois.py`（已跟踪、kind=hotel 强制改动）+ `ops/recat_hotels_in_pois.py`（未跟踪）；第 2 组只剩 5 份 parks_*.md 记录 + 本进度档。门禁绿后按此缩减范围提交。
- 2026-11-02 23:47 run#2 **T2 GREEN（第 2 次）**：2024 passed / 0 failed，覆盖率 81.74%（≥75）。重试 1/3 的 8 个失败已被并行会话 plan 修复提交（50a2f1f 第1天无安排收口、d6a6daf 异地命中四路收口）清除。T3 闸门放行。
- 2026-11-02 23:52 run#2 **T3 DONE（范围缩至零 + 进度档）**：发现并行会话 23552b5 已把 parks_* 记录 + 六个 ops 工具脚本（含 recat_hotels_in_pois、move_rest_to_pois，工作树对 HEAD 干净）收编落库，7b70bf4 已收编代码+测试+DESIGN——T3 原两组全部被收编，仅剩本进度档未跟踪，以 44c6e91 提交（未 push）。另注：并行会话 bc8df97（23:42）已实现星级饭店打标 job（star_5/star_4 互斥 + mct 权威闸），POIS_DATASOURCE §3.2 #12 backlog 项已在另一会话落地中；其原始数据 _src/mct_star*_raw.json 等未跟踪文件属该会话，本自动化不碰。
- 2026-11-02 23:58 run#2 **T4 DONE（正确零写入）**：库里又进一大波导入（active 总量涨至 ~13k，nature 4961/park 599——非本自动化范围，为别会话导入波）。enrich 实跑 targets=836、filled={}：全量核查 NULL 池 848 行，842 行名称规则判不了（红色旅游旧址/泛化名，产品规则本就不进候选），仅 6 个名称误报全是餐饮行（海底捞→nature 系「海」字触发）且被作业的 _FOOD_NAME_MARKS 拦截器正确排除——零写入是正确行为。recat 清扫 scanned=9755、新命中 0：新导入的住宿行走修复后的导入路径已自带 category='hotel'（hotel active 3758 全部干净，带住宿词行在 hotel 类外的数量=0）。
- 2026-11-02 23:59 run#2 **T5 DONE**：`restaurants where source='chinatravel' and cuisine is null` 前值已为 0（3 个遗留目标已被并行会话的搬移进程消化），本轮 mover 复跑 targets=0 零动作确认；按规程补跑 recat 清扫一遍，0 新命中，hotel active 3758 维持干净。

**T1-T5 全部完成（2026-11-02 23:59 run#2）。后续运行只追加 ALL DONE。**
范围外遗留（供人拍板，本自动化不动）：①别会话导入波新增的 park 行未过普通公园清洗（park active 393→599，可复用 parks_cleanup_proposal 规则再扫）；②848 行 NULL 分类中红色旅游旧址按产品规则应出池（过滤属独立工作项）；③仓库根杂物清理（h5_*.html/ti_*.json 等）；④酒店星级打标已由并行会话 bc8df97 实现 job、其名单数据源仍在准备中。
- 2026-11-03 00:04 run#3 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:09 run#4 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:14 run#5 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:19 run#6 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:24 run#7 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:29 run#8 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:34 run#9 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:39 run#10 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:44 run#11 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。
- 2026-11-03 00:49 run#12 **ALL DONE**：T1-T5 已全部勾完，本轮零动作。自动化 12 轮额度用尽，就此收官；T1-T5 完成于 run#2（2026-11-02 23:47–23:59）。
- 2026-11-03 00:54 run#13 **ALL DONE**：T1-T5 已全部勾完，本轮零动作（额度注释后自动化仍在触发，继续按规程记录）。
