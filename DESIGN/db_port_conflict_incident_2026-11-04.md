# 5432 端口抢占事故（2026-11-04 夜）——H5 静默连到 10-29 旧快照

## 事故还原（时间线，CST）

| 时刻 | 事件 |
|---|---|
| 白天全天 | 生产库 = Docker 容器 `chinatripcodes-db-1`（postgis 16.4，卷 `chinatripcodes_pgdata`），H5/日批/各会话全部经 `localhost:5432` 正常读写 |
| 21:42 | Docker Desktop（WSL 后端 VM）挂掉，容器 Exited(255)，5432 失去应答 |
| 22:00:15 | WSL 内**迁移前旧实例 PostgreSQL 18** 随 WSL 启动自启，抢占 5432 |
| 22:00–23:10 | H5（8000/8443）、`backfill_intro_llm` 与本会话的探针**静默连到旧快照**：pois 总量 4,700（vs 生产 14,534）、`hours_source='amap'`=0、数据停在 10-29——全程零报错，只有行数对不上才暴露 |
| 23:14 | 判明后：`pg_dump` 全量备份旧库 → 停 WSL postgres（`wsl -u root service postgresql stop`）→ 拉起 Docker Desktop → `docker start chinatripcodes-db-1` |
| 23:16 | 容器 WAL 崩溃恢复完成，指纹复核通过（见下） |

## 完整性与损失评估

- **今天的营业时间写入全部在位**：`hours_source='amap'` 1,293 行（白天基线 122 + 本日驱动 ~1,170），抽样（平阴县博物馆/西安半坡博物馆/喀什地区博物馆）值与写入时一致。
- 总量 16,825 → 14,534 的差额是**并行会话白天的清理作业**（parks cleanup round4 的 596 行 inactive 存证、retired/duplicate purge、重复行合并），均有 CSV 备份，非本事故损失。
- 旧库 22:00 起**零写入**（审计 `updated_at > 22:00` = 0），`backfill_intro_llm` 当时只是挂着空闲连接。
- 唯一残余风险：23:14 前 intro 作业若在旧库落过行，只存在于备份 `ops/wsl_pg_stale_backup_20261104.dump`（3.0MB，完整 dump），未并入生产库——按 fill-empty 语义重跑即可补。

## 根因

迁移期遗留的**双实例同端口**：WSL 原生 PG18 systemd 自启 + Docker Desktop 不自启（已知问题），后者一挂前者就抢 5432，且旧实例 schema 兼容、查询不报错——**静默换库是最坏失败模式**。

## 已落地的防复发（2026-11-04 夜）

1. `wsl -d Ubuntu -u root systemctl disable postgresql`——旧实例不再自启（服务本体保留，`service postgresql start` 可手动起）。
2. `ops/db_up.cmd` 重写：docker 引擎不在→自动拉起 Docker Desktop（等 ~90s）→`docker start chinatripcodes-db-1`→调 `ops/db_fingerprint.py` 按 pois 行数（阈值 10,000）判别实例身份，命中旧快照/连不上即打 CRITICAL（rc=2/3）。批处理注意：**goto/label 不能放在括号块内**（GBK 代码页下还会把中文注释当代码执行）。
3. 旧库完整备份：`ops/wsl_pg_stale_backup_20261104.dump`。

## 遗留决策（待用户）

- WSL PG18 旧实例是否彻底退役（`pg_dropcluster`）或迁移数据后转正——当前仅禁自启，保留现场。
- Docker Desktop 开机自启是否打开（否则重启后 5432 空窗，依赖 db_up.cmd 自愈，夜批首轮会延迟 ~90s）。
