# JEV 评论 Pilot

使用 TypeSafe 官方 `https://api.typesafe.ai/v1/systemone`，协议核对来源：
https://github.com/typesafe-ai/typesafe-sdk-python

```sh
export TYPESAFE_API_KEY="your-key"
python scripts/jev_pilot.py --input local/jev_input.json --output-dir local/jev_pilot_20261006
```

也可读取本地忽略文件 `local/.jev.env`。密钥与完整结果均不发布。
缓存键含模型、实际问题、输入上下文、版本与接口。同目录重跑复用成功缓存；身份记录独立计数。遇认证或配额错误停止，保留进度；失败不算中性。

此 Pilot 在评论级输出主要方向/动作/陈述类型及完整概率，不替代 v3.2 原子单元。二元概率采用 0.5 阈值，未校准；有冲突的输出列入 review_flags。保留模型原始判断，不用规则覆盖模型概率。对照为当前本地规则抽取结果，不能当作 Gold。人工标注缺失时不计算准确率、Macro-F1、Brier 或 Calibration，不推断投资收益。

CSV 做公式防护，HTML 转义原文；报告 JSON、Markdown、HTML 及缓存仅写入 local。成功响应 token 为供应商报告值；失败重试是否计费未可知，不估计金额。


## JevJudge v2：两层协同线索与方向

```sh
python scripts/jev_judge_v2.py --input local/jev_input.json --config configs/jev_v2.json --output-dir local/jev_v2_20261006
```

第一层：同平台的 NFKC 去空白文本、SequenceMatcher 相似度0.9单链接聚类、数字替换模板、15分钟样本时间集中度、同作者发言、组内已知作者多样性、跨作者文本相似度、点赞对数的 robust zscore。无作者ID不使用昵称代替；缺失/退化字段为 null。burst_score 为本样本窗口次数相对跨度平均期望的比值，不能当作平台全量异常。单链接簇可能通过中间成员连接，不要求所有成员两两0.9。

第一层 Noul 概率与 Choice 完整概率分别保留。第二层独立读取目标语义，保留 NEUTRAL / UNCLEAR / NOT_APPLICABLE 区别。高疑似协同文本也保留方向。

阈值配置可修改：p_bot≥0.8 默认排除；0.5–0.8 降权复核；低于0.5进入 ACCEPT。ACCEPT 是实验统计 gate，不是“已确认真实用户”。主指数只纳入相关、两层均成功且未排除记录，权重1−p_bot；另列所有相关文本软加权值。对比组不足10条时不输出分歧指数；0.5–0.9阈值敏感性视图仅作描述。

两个请求各自缓存，缓存键含实际问题、上下文、配置与模型。旧Pilot标签不直接复用为新五分类。部分失败不进入汇总，第一层成功可以缓存恢复。features.json / review_queue.json / human_annotation.json 为本地交付；Gold字段保持空白且重跑不覆盖人工填写。

当前104条均无稳定作者ID，无法验证账号真实性；不得把本轮结果作为水军检测准确率或投资操纵事实。无人工Gold不生成精度数字。未接入ASDC、不删除原文、不修改既有v3.2抽取。
