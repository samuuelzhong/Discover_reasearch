# Discover_reasearch — 实验发现闭环（Experimental Discovery Loop）

一个 multi-agent 自主科学发现框架在 **CAMELS 径流模拟**任务上的完整落地实现。目标不是"用 AI 解决已有问题"，而是让 agent 闭环走完 **文献 → 假设 → 实验 → 裁决 → 异常回流** 的全过程，做出可核验的陈述型产物。

## 设计原则

- **文献真实**：检索走 arXiv / DataCite 等真实源，每条 claim 带逐字引文与 char offset，机械门控拒绝无据可查的断言（反幻觉四件套）
- **文献即工具**：手写零依赖 MCP server（stdio JSON-RPC），论文的 `check_claim` 接口可被 agent 直接调用
- **预注册裁决**：假设以四元组 `H = (claim, plan, decision_criteria, alternatives)` 预注册，判定交给真实数据，不由模型自己说了算
- **陈述型落点**：分支 2 的产物是一条人类可核对的命题（机制/判据），不是"模型变好了"的黑箱 oracle

## 两条分支

| 分支 | 目标 | 产物形态 | 关键结果 |
|------|------|----------|----------|
| 1 精度 | 径流模拟提精度（岭回归，全程无 LSTM） | 工程/流水线 | val NSE 0.3405 → 0.4305，test 0.3766 → 0.4601（39 次评估可复现） |
| 2 挖掘 | 气候变化下的新自然变化 | 预注册假设 + 判定 | 5 条假设：3 支持 / 2 削弱；1 条伪造假设被机械门控拒绝 |

辅助机制：ShinkaEvolve 风格的算子进化搜索（UCB1 算子老虎机 + 三岛模型，按 val 挑选防 test 泄漏）、留一归因（`pet_roll` 贡献 −0.178 为主力）、稳健 z 异常检测（合成校准 recall 1.0 / precision 0.6）。

## 目录结构

```
discovery_loop/     核心框架（9 模块，约 2000 行）
  core.py           Run 状态与 SQLite 9 表台账
  scout.py          多源文献检索（429 退避 + 引文验证）
  paper_mcp.py      论文 MCP server（check_claim 三档判定）
  hypothesis.py     假设门控与预注册
  experiment.py     岭回归实验（时间切分 60/20/20）
  evolve.py         UCB1 算子进化 + 三岛
  analysis.py       签名表 / 假设判定 / 异常 / 归因
  boss.py           汇总报告
  cli.py            命令行入口（new/data/papers/ask/hyp/evolve/report/…）
  pipeline.py       可执行主线（冷启动+阶段门槛：文献→综合/发散→假设环→实验→p2a）
  hypo_evolve.py    假设池工具层（池按域隔离：hypo_pool_<域>.json）
  agent_round.py    假设环检索执行器（自带主线门槛 guard）
  data/hydro.py     USGS 径流 + NASA POWER/Open-Meteo 气象，磁盘缓存
runs/               8 轮运行台账（state.db + 判定 JSON + 报告）
docs/               调研报告、精读、方案评审、立项叙事、流水线清单
```

## 快速开始

**新领域从零**走可执行主线（强制顺序：文献 → 综合/发散 → 假设环 STOP → 实验 → p2a，禁止跳步）：

```bash
python discovery_loop/pipeline.py newdomain <域>            # 冷启动：路线台账+按域空池（拒绝覆盖已有域）
python -m discovery_loop.scout --run <run> search <query>   # ① 文献检索入库（默认 openalex+arxiv+s2 源）
python discovery_loop/pipeline.py done <域> s1_scout "证据：run_id/查询数/入库数"
python -m discovery_loop.fieldmap --run <run> --domain <域>   # ①b 流派图谱 + ② 跨域发散（类比域抓回入库）
python discovery_loop/pipeline.py done <域> s1b_synthesize "机制图谱要点"
python discovery_loop/pipeline.py done <域> s2_xdomain "类比域与回收动作"
python discovery_loop/agent_round.py r1 --domain <域>       # ③ 假设环：agent 设计计划→真检索→语义判读写回池→三辩证问题 STOP
                                                            #    （自带 guard：s1 未完成则拒绝执行；判读写回一律带 domain=<域>）
python discovery_loop/pipeline.py done <域> s3_hypothesis "STOP 理由见 hypo_evolve_log_<域>.jsonl"
python discovery_loop/pipeline.py gate <域> "三层基线登记"  # ④ 前置门禁：消融臂/SOTA基座(内化来源)/sanity（见下节）
python discovery_loop/pipeline.py done <域> s4_experiment "…"
# ⑤ p2a 内化：SP 类假设前置于实验作基座；SC/SW 类可实验后沉淀资产
```

**基础链条 ≠ 检索边界**：六阶段只是"首次覆盖"的最低门槛（guard 只拦跳步）。
文献检索/跨域发散/引文回调是**全阶段常驻服务**——知识综合、假设优化、实验
验证与分析的任何时刻都可以再调研、换角度补查、回调源论文。假设环每轮本身就是
新的检索计划；循环之外的补查用 `pipeline.py refine <域> "为何补查/换了什么角度"`
登记入台账（status 可见补查历史），留痕可审计。

**实验门禁与基座纪律**（2026-11-01 用户裁决，防误判基础设施——实验不得在无基座/基线时开展）：

- **基座门禁**：`guard s4` 要求台账已 `gate` 登记三层基线，缺一不可——
  消融基线（证明机制存在，对照臂来自假设环锁定的 nearest_prior）、
  SOTA 外部基线（证明性能领先，**内化自关键论文复现，含完整评测协议**）、
  sanity 基线（climatology/线性回归，防所有臂都不比 chance 好）。
- **为什么**：不内化基座则增益与种子/协议抖动统计不可分（LSTM 在 CAMELS 上种子间 NSE ±0.01-0.02，与多数真实改进同量级）；评测协议细节（分割年份/warm-up/标准化/流域子集）可制造 0.05 级假差异——内化基座 = 内化完整协议，不是只搬模型权重；半合成实验必须用真实论文的过程模型注入信号，自建模型注入 = 循环验证。
- **p2a 按假设类型分裂**：性能声明类（"超越主流"）必须先 p2a 内化基座再实验；反演/计量类可先轻量试错、幸存者再内化沉淀。
- **假设→实验设计五总则**：(1) 拆分断言，每条独立可证伪；(2) 对照即 delta——claim 声称"X 优于 Y"，Y 必须是真实对照臂；(3) claim 中的限定词（"集中于尾部""在气候位移段"）直接转为分层评估维度；(4) 归因/反演类先在真值已知的半合成数据上验证；(5) 预注册失败判据（含效应量阈值与混杂控制），禁止事后解释。
- **领域无关（通用性声明）**：本节纪律不绑定径流/CAMELS——迁移到任何领域时，把"SOTA 基座"换成该领域的公认主流（医学影像 nnU-Net、NLP 任务榜模型、物理仿真标准求解器等），把"种子/协议抖动"换成该领域的复现噪声源（随机种子/超参搜索/数据版本/标注者差异），门禁逻辑、三层基线与五总则原样适用。

**遗留 CAMELS 单任务路径**（历史 runs 台账，`--domain hydro` 时假设环警告放行）：

```bash
python discovery_loop/cli.py new --run runs/demo
python discovery_loop/cli.py papers --run runs/demo      # 文献检索与入库（在数据之前——README 明文规矩）
python discovery_loop/cli.py data --run runs/demo        # 拉取 24 流域数据
python discovery_loop/cli.py evolve --run runs/demo      # 算子进化搜索
python discovery_loop/cli.py analyze --run runs/demo     # 签名 + 假设判定 + 异常
python discovery_loop/cli.py report --run runs/demo      # 生成 REPORT.md
```

依赖极简：标准库 + numpy / pandas。第一圈完整记录见 `runs/hydro-r1/REPORT.md`。

## 数据说明

- 径流：USGS（公有领域），`runs/hydro-r1/artifacts/data/` 存有 24 流域快照
- 气象：NASA POWER（主）/ Open-Meteo（备）
- 下载缓存不入库，重新运行 `data` 命令即可重建

## 文档

详见 `docs/`：从 100+ 脚注的多智能体科学发现调研、DiscoveryRSI 精读、方案评审，到五点立项叙事与流水线输入输出清单。
