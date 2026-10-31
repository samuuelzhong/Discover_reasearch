

<!-- writer=boss ts=2026-10-27T10:26:01+00:00 -->
# Run smoke01
Boss: discovery_loop.boss；阶段：①Scout ②假设 ③实验 ④分析 → 异常通道回流。


<!-- writer=boss ts=2026-10-27T10:26:03+00:00 -->
## ③a 数据 (真实观测)
来源：synthetic (calibration only)；流域 6 个；期段 n/a；数据哈希 `215e185e0d18`。
字段：P/T/PET/SNOW/Q(mm·d⁻¹)，与 CAMELS 命名兼容（可用 `data --source local` 换成官方 CAMELS/CARAVAN 文件）。


<!-- writer=boss ts=2026-10-27T10:26:11+00:00 -->
## ③a 数据 (真实观测)
来源：synthetic (calibration only)；流域 6 个；期段 n/a；数据哈希 `337d02240d3c`。
字段：P/T/PET/SNOW/Q(mm·d⁻¹)，与 CAMELS 命名兼容（可用 `data --source local` 换成官方 CAMELS/CARAVAN 文件）。


<!-- writer=boss ts=2026-10-27T10:26:23+00:00 -->
## ③b 分支1：精度（可验证的硬指标）
21 次评估 / 2 代 / 3 岛；最佳设计 val NSE=0.9508，test NSE=0.9526（KGE 0.9596），6 个特征；算子策略终值 {'add': 0.9, 'remove': 0.475, 'tweak': 0.58, 'swap': 0.533}。


<!-- writer=boss ts=2026-10-27T10:26:29+00:00 -->
## ④ 分析层
流域签名表 6 行；异常通道标记 3 条（|robust z| ≥ 2.5）。
按 regime 中位数：
```
        runoff_ratio  elasticity  delta_elasticity
regime                                            
dry            0.100       1.002            -0.103
snow           0.099      -0.384             0.136
```
