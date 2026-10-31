# 七假设 Novelty 审计（R20 前置，批判辩证自审）

- 日期：2026-10-31
- 方法：scout.py 检索层（OpenAlex 精确短语 + arXiv 全词 AND，26 查询 ~170 命中）
  + 全文级验证（scout_pqa `paperqa_cited` 锚点 / 上游代码 README 机械证据）
- 数据：`novelty_probe_results.json`（检索层原始命中）；全文级证据在库：
  `文献收集/SSM2501.14980_rainfall_runoff.pdf`、`discovery_loop/data/conformal-streamflow-camels.zip`
- 词表：novel（未见直接先行）/ partially_tested（邻域密集、核心判定维度未覆盖）/ replication（核心机制已被验证）

## 判定汇总

| 假设 | 判定 | nearest prior（全文级锚点） | 未被覆盖的 delta |
| --- | --- | --- | --- |
| HM5-1 闭合分档约束 | **partially_tested** | 物理约束邻域密集：Differentiable process-based（arXiv 2203.14827）、Mechanism-Dependent Value of Physical Constraints（2026）、MC-LSTM（在库） | "按闭合误差分档差异化约束"未见直接命中；分档对照协议（无/软/严格）+ 闭合-KGE 双判定是我们的增量 |
| HM5-2 SSM 效率 | **partially_tested**（检索层一度判 replication 危险，全文级修正） | S4D vs LSTM，531 CAMELS 流域（arXiv 2501.14980）：median NSE 0.72→0.74，SSM 精度赢；**论文明确无 runtime/memory 测量**（paperqa_cited 锚点 pages 2-3, 7-11）；MC-LSTM 仅作 future work | **训练/推理效率对比**——恰是 HM5-2 判定阈值（训练时间 ≤50% LSTM）所在维度；SSM+闭合约束交叉也空白 |
| HM5-3 MARRMoT 对照 | **replication 倾向** | conceptual vs LSTM 为 Kratzert 组 2018/2019 成熟先例；MARRMoT benchmark 命中弱但概念对照成熟 | MARRMoT 2.0 具体版本×统一协议的对照（弱增量）；建议降级为方法对照臂而非独立假设 |
| HM5-4 GRACE 对照 | **partially_tested** | GRACE+DL 融合成熟（Sun 2019 arXiv 1902.01933 fusing GRACE） | "GRACE 作为对照源进大样本基准协议"角度待全文级确认 |
| HM5-5 conformal 覆盖审计 | **replication（实锤）** | Alsafari & Yafoz 2026（Water 投稿）：672 CAMELS-US 流域，8 种区间方法（split CP/CQR/Mondrian CQR/逐流域 ACI/...）× lead time 1/3/7d × **per-basin coverage 审计**（zenodo 23443077 README 机械证据） | 核心机制已被完整覆盖；仅剩"我们流水线残差的独立复核"价值——降级为方法对照臂 |
| HM5-6 EWS 前兆 | **novel（检索层）** | 水文 streamflow 场景未命中直接工作（"critical slowing down streamflow"=0；catchment 命中为噪声/2018 数据集） | 全文级验证待做（生态/气候 EWS 成熟，水文迁移点在） |
| HM5-7 SINDy | **novel（检索层）** | "SINDy hydrology"仅命中工业物料流（2025）；symbolic regression 命中 2014 遗传编程综述 | 全文级验证待做 |

## 对假设谱系的修正动作

1. **HM5-2 claim 精化**：从"SSM 主干对比 LSTM"收窄为"SSM 主干的**训练/推理效率优势**（精度已被 S4D 论文回答）"——假设更尖锐，实验判定不变（训练时间 ≤50% + 精度不劣化）。
2. **HM5-5、HM5-3 降级**为方法对照臂（不复列为 novelty 假设）；HM5-5 可直接复用 Alsafari 的 8 方法词表做我们残差的对照。
3. **R20 优先级重排**：HM5-1（partially_tested，工具最全，首跑）→ HM5-6/7（novel，残差首验）→ HM5-2（效率维度，等 HM5-1 基线）→ HM5-4（待全文级）。
4. **novelty_probe 进假设谱系闸门**（后续轮）：hyp.proposed 必须附 nearest_prior + delta + verification_status；replication 类假设的 verdict 只能声明独立复核。

## 诚实边界

- OpenAlex 精确短语检索 ≠ 系统覆盖：书脊式漏检（标题不含关键词）可能存在；HM5-6/7 的 novel 判定是检索层证据，未达全文级。
- Alsafari 2026 为"submitted to Water"状态（未同行评审），但其代码+结果文件全在库，机械证据强度足够支撑 replication 判定。
- S2 API 429 限流影响了个别查询的补充验证；OpenAlex 同时段也间歇 429（26 查询批量触发）。

## 再发散半环（2026-10-31 补，novelty 审计后的交叉验证）

从审计空白出发生成三条交叉假设线，发散检索（15 查询，`novelty_cross_results.json`）验证空白：

| 交叉线 | 来源 | 检索结果 | 判定 |
| --- | --- | --- | --- |
| **X1** regime/闭合条件化约束注入 | "Mechanism-Dependent Value of Physical Constraints"（2026 命中）+ S4D 论文的 regime 分异（雪融占优/pluvio-nival 落后） | 5 查询全噪声（无一水文交叉工作） | **空白（检索层）** |
| **X2** 预测区间覆盖 × 闭合误差关联 | Alsafari 做了 per-basin 覆盖但未按闭合质量关联 | "coverage stratified catchment attributes"=0，其余全噪声 | **空白（检索层）** |
| **X3** 前兆统计的稀疏回归自动发现（EWS×SINDy） | HM5-6/7 两条 novel 线交叉 | "SINDy early warning"仅 1 命中且无关（自主驾驶） | **空白（检索层）** |

**新假设候选（H6 草案，未走 hyp.proposed 正式闸门）**：

- **H6-a（X2，最可立即检验）**：预测区间覆盖误差与流域闭合误差正相关——低闭合流域的 conformal 区间系统性欠覆盖（或过宽）。可检验：HM5-1 基线残差 + conformal-mcp，按闭合分档对照覆盖；数据零新增（CAMELS + HM5-1 产出）。
- **H6-b（X1，需 HM5-1 完成后）**：物理约束的价值随水文 regime 系统变化——闭合约束在融雪/间歇 regime 收益最大（呼应 S4D 的 regime 分异与 Mechanism-Dependent 2026）。可检验：HM5-1 三档结果按 regime 分层再分析。
- **H6-c（X3，方法风险最高）**：临界慢化前兆统计可由稀疏回归自动发现（从候选特征库自动选出 AR(1)/std 等前兆组合），替代人工指定。可检验：合成临界慢化原型（ews-mcp 在库）+ sindy-mcp 组合。

三条均为检索层空白（`web_snippet`→检索级），正式化需走 hyp.spine + divergence_audit 闸门（blank_probe 证据已有）。检索质量陷阱留痕：OpenAlex 索引了大量低质量 zenodo 记录（"ALGO/The Theory of..."类），后续检索需加 peer-reviewed/cited_by 过滤。
