# 领域地图 · run `det-r0`（Stage ①b）

生成原则：所有数字来自本 run 的 72 篇入库文献与本次现场抓取（Semantic Scholar batch 引文扩展 + 类比域检索），不使用模型记忆。

## 1. 引文图
- 送出 66 个唯一 ID（arxiv/doi 去重），S2 命中 45 篇
- 库内引文边（我们的语料互相引用）：**22** 条 — 语料已初步连通成图
- 外部被引经典（语料共同指向的文献，即"大家都在比的对象"）：

- 25 次 — Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks
- 22 次 — Deep Residual Learning for Image Recognition
- 18 次 — Microsoft COCO: Common Objects in Context
- 17 次 — Focal Loss for Dense Object Detection
- 16 次 — End-to-End Object Detection with Transformers
- 14 次 — Feature Pyramid Networks for Object Detection
- 14 次 — SSD: Single Shot MultiBox Detector
- 13 次 — You Only Look Once: Unified, Real-Time Object Detection
- 12 次 — Deformable DETR: Deformable Transformers for End-to-End Object Detection
- 12 次 — Fast R-CNN
- 11 次 — FCOS: Fully Convolutional One-Stage Object Detection
- 10 次 — Mask R-CNN
- 10 次 — Cascade R-CNN: Delving Into High Quality Object Detection
- 9 次 — Very Deep Convolutional Networks for Large-Scale Image Recognition
- 8 次 — International Journal of Computer Vision manuscript No. (will be inserted by the editor) T

## 2. 流派与影响力

标签法：确定性词表打标（可审计），主标签 = 命中关键词最多的流派。

| 流派 | 篇数 | 占比 | 引用数中位数 |
|---|---|---|---|
| （未归类） | 13 | 18% | 325 |
| 小目标/航拍 | 12 | 17% | 352 |
| 增广/合成数据 | 12 | 17% | 20 |
| 标注噪声/弱监督 | 11 | 15% | 26 |
| query-based/DETR系 | 8 | 11% | 7 |
| 3D/点云 | 7 | 10% | 103 |
| NMS/拥挤遮挡 | 5 | 7% | 75 |
| one-stage/YOLO系 | 3 | 4% | 29 |
| two-stage/R-CNN系 | 1 | 1% | 30 |

## 3. 时间脉络（各时期流派篇数，72/72 篇有年份）

| 流派 | ≤2016 | 2017-2019 | 2020-2022 | 2023-2026 | 合计 |
|---|---|---|---|---|---|
| （未归类） | 0 | 7 | 4 | 2 | 13 (18%) |
| 小目标/航拍 | 1 | 1 | 4 | 6 | 12 (17%) |
| 增广/合成数据 | 0 | 1 | 5 | 6 | 12 (17%) |
| 标注噪声/弱监督 | 0 | 4 | 4 | 3 | 11 (15%) |
| query-based/DETR系 | 0 | 0 | 2 | 6 | 8 (11%) |
| 3D/点云 | 0 | 0 | 5 | 2 | 7 (10%) |
| NMS/拥挤遮挡 | 1 | 0 | 2 | 2 | 5 (7%) |
| one-stage/YOLO系 | 0 | 0 | 0 | 3 | 3 (4%) |
| two-stage/R-CNN系 | 0 | 0 | 1 | 0 | 1 (1%) |

**范式转移读法**：一列里占比的更替就是范式更替——2017-2019 列 YOLO/两阶段主导、2020-2022 起 DETR 系入场、2023-2026 列开放词表/基础模型与小目标航拍成为新增主力。

## 4. 前沿切片（≥2025 vs 之前，占比变化）

| 流派 | 2025 前 | ≥2025 | 变化 |
|---|---|---|---|
| one-stage/YOLO系 | 0% | 19% | +19% ↑ |
| 小目标/航拍 | 14% | 25% | +11% ↑ |
| query-based/DETR系 | 9% | 19% | +10% ↑ |
| NMS/拥挤遮挡 | 5% | 12% | +7% ↑ |
| two-stage/R-CNN系 | 2% | 0% | -2% → |
| 增广/合成数据 | 18% | 12% | -5% ↓ |
| 标注噪声/弱监督 | 18% | 6% | -12% ↓ |
| 3D/点云 | 12% | 0% | -12% ↓ |
| （未归类） | 21% | 6% | -15% ↓ |

## 5. 跨域发散（关切 → 机制抽象 → 类比域，类比域论文已抓取入库）

- **关切** 拥挤场景 NMS 误删邻近真目标 (H-OD3)
  - 机制抽象：空间邻近实体间共享检测资源的分配冲突
  - 类比域：神经科学 spike sorting（重叠尖峰分拣）；天文测光 source deblending（密集星源分离）
  - 落地：已抓取 10 篇；证据："Simulated data are used to illustrate the performance of the method and to show that it can easily cope with neurons gen…"（arxiv:q-bio/0405012v1）
- **关切** 基准 GT 自带标注错误 (H-OD2)
  - 机制抽象：参考真值本身是含噪观测，需要从多观测重建共识真值
  - 类比域：医学影像多阅片者共识真值（STAPLE 等算法）
  - 落地：已抓取 12 篇；证据："Our method employs a consensus network to aggregate annotations into a unified representation, guiding the main arousal-…"（arxiv:2505.21196v1）
- **关切** Copy-Paste 增广的多样性从哪来 (H-OD1)
  - 机制抽象：用既有样本重组制造受控多样性
  - 类比域：语音拼接合成（concatenative synthesis，单元选取重组）
  - 落地：已抓取 9 篇；证据："Existing Arabic speech synthesis solutions are slow, of low quality, and the naturalness of synthesized speech is inferi…"（arxiv:2007.11541v1）

## 6. 局限（与地图同页出现）
1. 语料按本 run 的查询召回，覆盖有偏：适合回答"我们检索过的脉络"，不是全领域普查。
2. S2 引文扩展对部分 Zenodo/数据集记录无匹配（未命中即如实计为 unmapped）。
3. 词表打标是粗粒度主标签，一篇论文可属多流派；schools.csv 保留每条标签可供人工复核。
4. 经典基线识别基于"语料共同引用"，语料外的真实引用量以引文数中位数作代理，非排行榜名次。
