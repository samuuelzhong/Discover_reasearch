# 领域地图 · run `det-h1`（Stage ①b）

生成原则：所有数字来自本 run 的 209 篇入库文献与本次现场抓取（Semantic Scholar batch 引文扩展 + 类比域检索），不使用模型记忆。

## 1. 引文图
- 送出 153 个唯一 ID（arxiv/doi 去重），S2 命中 110 篇
- 库内引文边（我们的语料互相引用）：**87** 条 — 语料已初步连通成图
- 外部被引经典（语料共同指向的文献，即"大家都在比的对象"）：

- 64 次 — Faster R-CNN: Towards Real-Time Object Detection with Region Proposal Networks
- 61 次 — Microsoft COCO: Common Objects in Context
- 48 次 — Deep Residual Learning for Image Recognition
- 46 次 — Focal Loss for Dense Object Detection
- 37 次 — SSD: Single Shot MultiBox Detector
- 37 次 — Feature Pyramid Networks for Object Detection
- 32 次 — Mask R-CNN
- 32 次 — Fast R-CNN
- 28 次 — End-to-End Object Detection with Transformers
- 27 次 — Rich Feature Hierarchies for Accurate Object Detection and Semantic Segmentation
- 25 次 — YOLO9000: Better, Faster, Stronger
- 23 次 — ImageNet Large Scale Visual Recognition Challenge
- 22 次 — Learning Transferable Visual Models From Natural Language Supervision
- 21 次 — YOLOv3: An Incremental Improvement
- 20 次 — International Journal of Computer Vision manuscript No. (will be inserted by the editor) T

## 2. 流派与影响力

标签法：确定性词表打标（可审计），主标签 = 命中关键词最多的流派。

| 流派 | 篇数 | 占比 | 引用数中位数 |
|---|---|---|---|
| 小目标/航拍 | 33 | 16% | 8 |
| NMS/拥挤遮挡 | 33 | 16% | 29 |
| （未归类） | 28 | 13% | 3 |
| 开放词表/基础模型 | 26 | 12% | 17 |
| 增广/合成数据 | 25 | 12% | 6 |
| one-stage/YOLO系 | 21 | 10% | 430 |
| query-based/DETR系 | 16 | 8% | 40 |
| 3D/点云 | 15 | 7% | 15 |
| 标注噪声/弱监督 | 11 | 5% | 10 |
| two-stage/R-CNN系 | 1 | 0% | 293 |

## 3. 时间脉络（各时期流派篇数，209/209 篇有年份）

| 流派 | ≤2016 | 2017-2019 | 2020-2022 | 2023-2026 | 合计 |
|---|---|---|---|---|---|
| 小目标/航拍 | 2 | 2 | 5 | 24 | 33 (16%) |
| NMS/拥挤遮挡 | 2 | 7 | 13 | 11 | 33 (16%) |
| （未归类） | 6 | 3 | 10 | 9 | 28 (13%) |
| 开放词表/基础模型 | 0 | 0 | 2 | 24 | 26 (12%) |
| 增广/合成数据 | 1 | 2 | 11 | 11 | 25 (12%) |
| one-stage/YOLO系 | 1 | 2 | 1 | 17 | 21 (10%) |
| query-based/DETR系 | 0 | 0 | 12 | 4 | 16 (8%) |
| 3D/点云 | 0 | 0 | 6 | 9 | 15 (7%) |
| 标注噪声/弱监督 | 0 | 1 | 2 | 8 | 11 (5%) |
| two-stage/R-CNN系 | 1 | 0 | 0 | 0 | 1 (0%) |

**范式转移读法**：一列里占比的更替就是范式更替——2017-2019 列 YOLO/两阶段主导、2020-2022 起 DETR 系入场、2023-2026 列开放词表/基础模型与小目标航拍成为新增主力。

## 4. 前沿切片（≥2025 vs 之前，占比变化）

| 流派 | 2025 前 | ≥2025 | 变化 |
|---|---|---|---|
| 小目标/航拍 | 11% | 27% | +17% ↑ |
| one-stage/YOLO系 | 8% | 15% | +6% ↑ |
| 3D/点云 | 7% | 8% | +1% → |
| 开放词表/基础模型 | 12% | 13% | +1% → |
| two-stage/R-CNN系 | 1% | 0% | -1% → |
| 标注噪声/弱监督 | 6% | 3% | -3% ↓ |
| （未归类） | 14% | 11% | -3% ↓ |
| query-based/DETR系 | 9% | 5% | -4% ↓ |
| NMS/拥挤遮挡 | 18% | 11% | -6% ↓ |
| 增广/合成数据 | 14% | 6% | -8% ↓ |

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
