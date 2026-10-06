# JEV 可评测判定器升级

104条路维光电，全部成功；模型响应为 jev-1.13.0。人工Gold完成0条。两层精度、混淆矩阵、Brier及ECE待标注，不以0冒充测量结果。

新增可插拔SemanticJudge、版本化问题审计、行为特征扩展、独立语言信号与实验融合分数、方向明确性/期限、三类概率权重聚合。融合分数未校准，不能直接称为P(coord)。未集成ASDC、不扩展股票。

本地包含104条空Gold模板及原文预测JSONL；公開只含聚合质量数据。无原文、昵称、评论/用户ID、来源明细、本机路径或密钥。填完真实Gold后可用evaluate-only离线评测。A/C对照需要可比预测，未把现有规则提取冒充LLM结果。

参考 evaluation/JEV_GOLD_GUIDE.md 与 scripts/JEV_PILOT.md。
