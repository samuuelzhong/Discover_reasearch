

<!-- writer=boss ts=2026-10-27T10:26:35+00:00 -->
# Run hydro-r1
Boss: discovery_loop.boss；阶段：①Scout ②假设 ③实验 ④分析 → 异常通道回流。


<!-- writer=boss ts=2026-10-27T10:26:44+00:00 -->
## ① 文献层 (Scout)
检索 3 条查询、6/查询，入库 18 篇真实文献（OpenAlex/arXiv，均存 URL + 检索时间 + 原文哈希）。


<!-- writer=boss ts=2026-10-27T10:28:56+00:00 -->
## ① 文献层 (Scout)
检索 1 条查询、6/查询，入库 0 篇真实文献（OpenAlex/arXiv，均存 URL + 检索时间 + 原文哈希）。


<!-- writer=boss ts=2026-10-27T10:30:04+00:00 -->
## ① 文献层 (Scout)
检索 2 条查询、6/查询，入库 12 篇真实文献（OpenAlex/arXiv，均存 URL + 检索时间 + 原文哈希）。


<!-- writer=boss ts=2026-10-27T10:30:36+00:00 -->
## ①b 论文工具化
1 篇本地 PDF 已抽文并入库（cite_id: pdf:f9df65e4c750）。


<!-- writer=boss ts=2026-10-27T10:34:21+00:00 -->
## ② 假设层
提交 5 条，结构门控通过 5 条，拒绝 0 条。
- `H-I1` [interpretation] 通过
- `H-I2` [interpretation] 通过
- `H-I3` [interpretation] 通过
- `H-I4` [interpretation] 通过
- `H-A1` [accuracy] 通过


<!-- writer=boss ts=2026-10-27T10:46:49+00:00 -->
## ③a 数据 (真实观测)
来源：USGS NWIS dv 00060 (mean daily cfs) + ERA5-Land via Open-Meteo；流域 24 个；期段 ['1990-01-01', '2022-12-31']；数据哈希 `9fe32642b145`。
字段：P/T/PET/SNOW/Q(mm·d⁻¹)，与 CAMELS 命名兼容（可用 `data --source local` 换成官方 CAMELS/CARAVAN 文件）。


<!-- writer=boss ts=2026-10-27T10:50:59+00:00 -->
## ④ 分析层
流域签名表 45 行；异常通道标记 9 条（|robust z| ≥ 2.5）。
按 regime 中位数：
```
        runoff_ratio  elasticity  delta_elasticity
regime                                            
dry            0.281       1.482            -0.511
rain           0.282       1.454             0.079
snow           0.462       1.163            -0.254
```


<!-- writer=boss ts=2026-10-27T10:53:01+00:00 -->
## ④ 分析层
流域签名表 21 行；异常通道标记 6 条（|robust z| ≥ 2.5）。
按 regime 中位数：
```
        runoff_ratio  elasticity  delta_elasticity
regime                                            
dry            0.268       1.590            -0.779
rain           0.864       0.778             0.079
snow           0.462       1.300             0.119
```


<!-- writer=boss ts=2026-10-27T10:53:42+00:00 -->
## ④ 分析层
流域签名表 21 行；异常通道标记 6 条（|robust z| ≥ 2.5）。
按 regime 中位数：
```
        runoff_ratio  elasticity  delta_elasticity
regime                                            
dry            0.268       1.590            -0.779
rain           0.864       0.778             0.079
snow           0.462       1.300             0.119
```


<!-- writer=boss ts=2026-10-27T10:54:14+00:00 -->
## ③b 分支1：精度（可验证的硬指标）
39 次评估 / 3 代 / 3 岛；最佳设计 val NSE=0.4305，test NSE=0.4601（KGE 0.4669），7 个特征；算子策略终值 {'add': 0.86, 'remove': 0.417, 'tweak': 0.417, 'swap': 0.562}。


<!-- writer=boss ts=2026-10-27T10:54:30+00:00 -->
## ④→① 回流（异常通道）
提升 4 条异常为第 2 轮观察：usgs-12449950/rr_trend, usgs-09171100/delta_elasticity, usgs-09169500/delta_elasticity, usgs-14243000/rr_trend


<!-- writer=boss ts=2026-10-27T10:55:21+00:00 -->
## ①b 论文工具化
1 篇本地 PDF 已抽文并入库（cite_id: pdf:863c8e683d91）。


<!-- writer=boss ts=2026-10-27T10:55:53+00:00 -->
## ①b 论文工具化
1 篇本地 PDF 已抽文并入库（cite_id: pdf:f89e14b0f5a3）。


<!-- writer=boss ts=2026-10-27T10:56:57+00:00 -->
## ③b 分支1：精度（可验证的硬指标）
39 次评估 / 3 代 / 3 岛；最佳设计 val NSE=0.4305，test NSE=0.4601（KGE 0.4669），7 个特征；算子策略终值 {'add': 0.86, 'remove': 0.417, 'tweak': 0.417, 'swap': 0.562}。


<!-- writer=boss ts=2026-10-27T12:49:25+00:00 -->
## ③b 分支1：精度（可验证的硬指标）
39 次评估 / 3 代 / 3 岛；最佳设计 val NSE=0.4305，test NSE=0.4601（KGE 0.4669），7 个特征；算子策略终值 {'add': 0.86, 'remove': 0.417, 'tweak': 0.417, 'swap': 0.562}。


<!-- writer=boss ts=2026-10-27T14:18:23+00:00 -->
## ④ 分析层
流域签名表 21 行；异常通道标记 6 条（|robust z| ≥ 2.5）。
按 regime 中位数：
```
        runoff_ratio  elasticity  delta_elasticity
regime                                            
dry            0.268       1.590            -0.779
rain           0.864       0.778             0.079
snow           0.462       1.300             0.119
```
