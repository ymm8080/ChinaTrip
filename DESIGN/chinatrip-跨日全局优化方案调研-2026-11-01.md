# 跨日全局优化方案调研——评分驱动 LNS 是否高效通用？有无更优路线？

日期：2026-11-01 · 触发：用户在 S2（LNS 跨天重排）开工前要求先行调研 · 结论直接修订已批设计

## TL;DR

1. **评分驱动 + 邻域搜索正是该问题类的当前最优路线**，不是折中之选。我们的问题在运筹学里早已定型：TTDP（Tourist Trip Design Problem）≈ Orienteering Problem 家族；多日行程 = TOPTW（多路线）/MuPOPTW（跨日分配）。2022 年系统综述（102 篇文献）结论：OP 是 TTDP 最广泛采用的建模方式，解法以启发式/元启发式为主。
2. **TOPTW 基准上最佳已知解比例最高的方法是 ELNS——destroy-repair 型大邻域搜索**（Amarouche et al. 2020 综述原文："the ELNS is currently the approach that provides the largest proportion of best-known solutions for the TOPTW benchmark instances"）。我们已批的 S2 正是这一族的轻量版。
3. **精确法/CP 全局模型不可行是文献共识**：NP-hard，DP/脉冲/B&P/CP 只在百点级小基准可用——与我方 10-31 全局求解器不收敛事故互相印证。
4. **Google Trips 生产实践（WSDM 2018）**给出的不是"更好的算法家族"，而是**更好的目标函数**：贪心逐日排会「第一天全是精华、后面逐日无聊、同街区反复」——与我们 tier 贪心选点的病灶完全一致；他们改为最大化**最差日**的质量（max-min），人工评分接近人类旅行专家。
5. 裁定：**不换道**。吸收三个文献背书的族内升级进 S2/S3：destroy-repair 算子（治互锁日）、max-min 日均衡软惩罚项（治逐日变无聊）、卡局部最优时扰动/多启。

## 1. 问题定型（我们到底是什么问题）

- **TTDP**：给定 POI 集合（收益/建议时长/时间窗/门票），多日预算下选点+排序+排时，最大化总收益。
- 我们 = TOPTW（多路线=多天）+ MuPOPTW（Tricoire et al. 2010 定义跨日维度："visits to customers span a period of time (days)... each customer may be visited on a different day"）+ 侧约束（演出场次、餐窗、雨天、用户钉、预算偏好、16:00 入场闸、转场缓冲、酒店入住地板）。
- 侧约束越多越偏向启发式（时间窗已使启发式设计困难，Gendreau et al. 1998，经 Amarouche 2020 引述）。

## 2. 文献证据

### 2.1 精确法（否决项）

TOPTW 精确解法仅有：DP-DSSR（Righini & Salani 2009，单路线）、pulse（Duque et al. 2015）、Branch & Price（Tae & Kim 2015）、CP（Gedik et al. 2017）——全部只在百点级小基准上报告结果。综述原话："Orienteering problems are well-known NP-hard optimization problems, and solving them within a reasonable amount of time may prove to be rather difficult"。

→ 我方规模（几十 POI × ≤9 天 × 硬侧约束）+ 交互时延要求 + 10-31 全局求解器不收敛事故 = 三重否决。

### 2.2 启发式全景（我们所在的位置）

TOPTW 方法清单（Amarouche 2020 综述章节）：ILS（Vansteenwegen et al. 2009）、VNS（Tricoire et al. 2010）、GRASP+ELS（Labadie et al. 2011）、granularity-VNS、SA（Lin & Yu 2012）、MC-TOP-MTW 的 GRASP+ILS（Souriau et al. 2013——含门票类背包约束+多时间窗，最接近旅游域）、I3CH（Hu & Lim 2014）、ABC、Memetic（giant-tour splitting）、ELNS（Schmid & Ehmke 2017）。

- **ELNS = TOPTW 最佳已知解比例最高**。
- MS-ILS（该文自研）："finds the current best known solutions, or better ones, for 89% of the literature instances within reasonable runtimes"，且比多数 SOTA 更快。
- 共同结构 = **可行解空间内的目标引导邻域移动**——我们的 S1 打分器 + S2 move/swap 与此同构。

### 2.3 生产实践（Google Trips，WSDM 2018）

- 实时性是硬要求（原文："the algorithm must be sufficiently responsive to compute new itineraries in real time even running locally on a mobile device"）——生产解 = 快速单日子程序（GreedyTSPCost，50ms 级）+ 组合层，与我们插入式求解器 5ms/日同量级。
- 贪心逐日的病理（原文）："the first day of a visit might cover all the best destinations, then each subsequent day might visit places one tier more boring than the day before. Worse yet, each of these days may revisit the same neighborhoods"——**正是我们分配层 tier 贪心的病灶**；并点名补丁式启发（re-order days、penalize re-visits）"difficult to tune appropriately across the wide range of cities"——与我们三个硬编码修复算子的困境一致。
- 解法 = 目标函数改造：**max-min**（"maximizing the benefit of the worst day rather than maximizing the sum of benefits"），附带治好街区聚类（一天集中一片、隔天换片）。
- 效果：5 天行程最差日价值平均翻倍、总收益不损；人工评分 "only slightly below the itineraries created by human travel experts"。

### 2.4 效率与通用性裁定（对我们）

- **效率**：我方规模（≤几十 POI、≤9 天；评估 = 兜底重排亚毫秒 / 插入求解 5ms/日）→ 100-200 次评估 ≈ 1-2 秒，远优于文献 "reasonable runtimes"（百点规模、秒-分钟级）。不是瓶颈。
- **通用性**：目标函数 = 一切拍板的容器（雨/预算/餐/场次/入场闸已各自成项；每条新规则 = 一行惩罚）。这与 OP 家族 "profit/score" 建模同构（Souriau 2013 的门票背包约束、Google 的 max-min 目标都是往目标/约束里加项）。
- **硬/软分层接受准则**（硬惩罚不加重才接受）= 层级约束处理标准做法。

## 3. "更好的方案"盘点与裁定

| 候选 | 文献地位 | 裁定 |
|---|---|---|
| 全局 CP/ILP 精确模型 | 仅小基准可用 | ❌ 规模+时延+失败模式不透明（三重否决，含我方 10-31 实证） |
| GA/ACO/ABC/Memetic | 均有文献 | ❌ 更重、不更好；giant-tour splitting 对多城转场不自然 |
| SA/模拟退火接受 | Lin & Yu 2012 | △ 作 strict-improvement 卡住时的升级开关（S2.3） |
| **ELNS destroy-repair** | **TOPTW 最佳已知解比例最高** | ✅ **S2.1 吸收**：加「拆一日重插」算子，治互锁日（day4 三秀） |
| **max-min 最差日目标** | Google 生产实证 | ✅ **S2.2 吸收**：打分器加 worst-day 均衡软项 |
| 分数驱动构造（重写选点层） | 构造+改进两段式是标准 | △ 不必：贪心构造（tier 尊重、确定性、可解释）+ LNS 改进 = 标准两段式，重写性价比低 |

## 4. 对已批 S2 的修订（增量，不推翻）

- **S2 主干不变**：打分器 + move/swap + 兜底评估器 + strict-improvement + 只挪不删守卫。
- **S2.1（新算子）** destroy-repair：把信号日的非钉条目全部摘下、按评分增益/成本贪心重插（含跨日）；一轮 = 一次大邻域跳跃，对单点 move/swap 解不开的互锁日有效。
- **S2.2（打分器加项）** day_balance 软惩罚：最差活动日负载距 180 分钟的缺口 × 小系数（max-min 的轻量实现），治「tier 贪心逐日变无聊」。
- **S2.3（可选）** 连续 N 轮无改进时小扰动重启（ILS shake），预算内保 best。
- **S3 不变**：指标面板 + 坏例回归。

## 5. 引用

1. Ruiz-Meza, J. & Hickman, R.J. (2022). *A systematic literature review for the tourist trip design problem*. Operations Research Perspectives（开放获取；102 篇文献系统综述）。
2. Amarouche, Y., Guibadj, R.N., Chaalal, E., Moukrim, A. (2020). *Effective neighborhood search with optimal splitting and adaptive memory for the team orienteering problem with time windows*. Computers & Operations Research 123, 105039（HAL hal-02890475 开放获取；含 TOPTW 全景综述章节）。
3. Friggstad, Z., Gollapudi, S., Kollias, K., Sarlós, T., Swamy, C., Tomkins, A. (2018). *Orienteering Algorithms for Generating Travel Itineraries*. WSDM 2018（Google Trips 生产系统）。
4. 间接（经 2/3 引用）：Vansteenwegen et al. 2011 与 Gunawan et al. 2016 综述；Schmid & Ehmke 2017（ELNS）；Tricoire et al. 2010（MuPOPTW）；Souriau et al. 2013（MC-TOP-MTW）；Gedik et al. 2017（CP for TOPTW）。
