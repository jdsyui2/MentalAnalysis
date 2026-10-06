# JEV 104 条人工评测

当前 Gold 完成数为零。原文、行为特征和逐条预测仅在本地忽略目录保存；公开仓库发布汇总、代码与标注规范。

运行：

```sh
python -m scripts.jev_benchmark --output-dir local/jev_benchmark_20261006
```

本地交付 `jev_gold_104.jsonl`、`jev_predictions_104.jsonl`、两层 confusion、calibration、error_cases 和 summary。复用成功缓存；输入或配置改变必须另建目录。请求问题变化形成不同缓存键。原有 Pilot 和 v2 结果保留。

## 人工标注

标注前隐藏预测，独立查看原文和样本行为特征。缺少账号或历史不能强猜真实身份，允许 UNCERTAIN。

- `gold_coordination`：ORGANIC / SUSPECTED_COORDINATED / UNCERTAIN。
- `gold_direction`：BULLISH / BEARISH / NEUTRAL / UNCLEAR / NOT_APPLICABLE。
- `subject_relation`：PRIMARY / RELATED / EXTERNAL / UNKNOWN。
- `explicit_direction`：人工布尔或未知。
- `horizon`：INTRADAY / 1D / 1W / MEDIUM / LONG / UNSPECIFIED。
- `annotator`：实际标注人员标识；完成后填 `annotation_status=COMPLETED`。

事实或公告不自动看多；NEUTRAL必须是明确震荡或平衡判断；问题、冲突期限不并入中性。复制公告未必协同操纵。模型输出不能用作 Gold。

填完后运行 `python -m scripts.jev_benchmark --evaluate-only --output-dir local/jev_benchmark_20261006`，不访问 API，程序重新计算指标。重跑不会覆盖 Gold。不能把未标注项当作分类错误或零分。

## 度量与门槛

分别报告每类 support、precision、recall、F1、混淆矩阵、未知率与覆盖率。Macro-F1 按有人类样本支持的类别计算，缺类标明 PARTIAL_GOLD；完整验收需要所有类别覆盖。

Brier 为所有类别平方误差之和的样本均值（0至2）；ECE 为10个等宽概率箱的 winner-label 校准误差。概率质量和语义准确率分别评估。

目标：协同 precision≥0.90、recall≥0.70、organic precision≥0.90、ECE<0.10；方向 Bull/Bear precision≥0.90、recall≥0.80、NA precision≥0.95、Macro-F1≥0.85。无对应真实样本则为未验收，不能判为通过。

先用104条做人类标注及误差分析；开发调参和冻结验收样本应分开，近重复不能跨集合。温度或阈值校准只能拟合开发集，最终指标在独立冻结集计算。

## 三条 Pipeline

A=LLM only，B=Jev comment judge，C=原子抽取加Jev。B已产出；A/C需要同语料、同目标、相同样本与任务映射的预测，当前不把已有规则提取冒充LLM结果。Gold和可比预测齐备后才能做三方精度比较。

## 融合及审计

配置保存权重0.35/0.25/0.20/0.10/0.10。不可用特征为null，可用权重重归一；报告其分母。相似度只有近重复簇存在时贡献，普通金融词相似不自动判协同。时间指标为有限样本描述，没有平台完整采集覆盖，不当作已验证异常。same_direction_cluster_ratio在方向完成后计算，不反向污染当前判定。

Choice三类概率分别用于 organic/coordinated 两路加权。启发式融合score和独立Noul保持分离，未称为校准的P(coord)。低概率质量不推断账号真实性或操纵事实。有效概率权重不足时不发布分歧结论。

请求审计保留 provider、requested/resolved model、问题版本及 question/criteria SHA256。若供应商只返回模型别名，明确标记，不能编造具体模型版本。
