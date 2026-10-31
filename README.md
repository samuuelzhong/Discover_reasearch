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
  data/hydro.py     USGS 径流 + NASA POWER/Open-Meteo 气象，磁盘缓存
runs/               8 轮运行台账（state.db + 判定 JSON + 报告）
docs/               调研报告、精读、方案评审、立项叙事、流水线清单
```

## 快速开始

```bash
python discovery_loop/cli.py new --run runs/demo
python discovery_loop/cli.py data --run runs/demo        # 拉取 24 流域数据
python discovery_loop/cli.py papers --run runs/demo      # 文献检索与入库
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
