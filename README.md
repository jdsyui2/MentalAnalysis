# MentalAnalysis 2.0

可追溯的中文投资评论分析。所有输出保持实验状态，直到人工验收通过。现有 `output/*.json` 是旧规则结果，运行不覆盖它们。

## 安装与运行

Python 3.10+（本次使用 3.12）。

```bash
uv venv --python python3.12 .venv
uv pip install --python .venv/bin/python 'pydantic>=2.7,<3' 'httpx>=0.27,<1' 'pytest>=8,<10'
.venv/bin/python run_pipeline.py --dry-run
export MENTAL_BASE_URL=https://api.deepseek.com
export MENTAL_API_KEY=your-key
export MENTAL_MODEL=deepseek-flash
.venv/bin/python run_pipeline.py --resume
```

根目录 `.env` 自动加载 MENTAL_BASE_URL / MENTAL_API_KEY / MENTAL_MODEL；进程环境变量优先。`.env.example` 提供模板。不要将凭据写入配置、报告或版本控制。支持 OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL 别名。

默认先分析按固定散列顺序选择的 100 条有效评论，记录调用与 token。确认配置配额足够后，用 `--full --resume` 运行所有评论。默认最多 300 次请求和 2,000,000 token，包含重试；全量须在 `configs/pipeline.json` 中配置足够额度。缺凭据时生成 PARTIAL 报告，所有待分析记录明确失败，无伪造的中性结果。

`--input` 接受多个文件或目录；目录只扫描顶层 JSON。默认包括根目录样例，经身份匹配后合并，所有来源保留。`--output-dir` 指定运行根目录，每次运行生成独立子目录。`--resume` 使用该根目录的共享持久缓存，不重复请求已通过证据校验的结果；不使用该选项时缓存仅属于本次运行。失败不缓存。校验 schema、提示词、模型或上下文变化会使缓存失效。

## 中文主题发现

```bash
uv pip install --python .venv/bin/python 'bertopic>=0.16,<1' 'sentence-transformers>=3,<6' 'jieba>=0.42' 'umap-learn>=0.5' 'hdbscan>=0.8'
```

首次运行需要下载 `BAAI/bge-small-zh-v1.5` 权重。模型卡许可证 MIT，版本与许可见 https://huggingface.co/BAAI/bge-small-zh-v1.5 。主题仅针对成功识别投资方法的文本；不足 50 条为 INSUFFICIENT_DATA，依赖或模型不可用为 FAILED。离群主题保留。主题名称为候选，人工评审通过才可确认。

## 数据口径与报告

每次运行输出 normalized_comments、analyzed_comments、ticker_consensus、strategy_ranking、topics、timeline、quality、manifest、review_queue、failures，另附 CSV 和离线 report.html。HTML 的原文链接定位到身份记录，包含源文件、行号和原元数据。CSV 对公式触发文本转义。

源文件 `row` 为 comments 数组的零起始位置。cid 全局按 douyin 平台去重；无 ID 数据只在同视频规范文本唯一匹配时合并，不确定身份保留。缺用户 ID 不用昵称替代。相同文本不同 cid 分别计数。相同 cid 的原文/视频冲突进入复核。点赞、回复等观察值全部保留在 sources；展示取第一个有 ID 的观察，缺失值不推测。

代码解析仅来自 `configs/entities.json`。原词典证券代码标注为 legacy 来源，需人工核查；新增词条无已验证代码时 ticker=null。泛指黄金、指数等不自动映射具体产品。未解析实体进入复核队列；其原始意见仍保留在明细，正式方向聚合只包含 SUCCESS。

指数与方向分布均显示样本数。推荐数包括 BUY/HOLD/WATCH，反对数包括 AVOID/SELL，不表示投资收益。分歧度与情绪强度分别计算；少于 10 个方向样本标为不足。多标签方法比例分母为成功分析评论数，允许合计超过 100%。点赞加权仅为辅助视图。

趋势必须配置带时区的 `analysis_cutoff` 和 `comparable_complete_windows=true`，且每个纳入输入的 coverage 同时声明 `window_complete=true`、`comparable=true`。当前原始数据无此证据，因此仅展示样本内时间分布。缺失评论时间不从文件名推算。原输入一级评论与平台报告总量、未采集回复差额在 manifest 保留；这些数据无法证明完整评论区覆盖。

## 人工标注与验收

```bash
.venv/bin/python -m evaluation.manage prepare --input comments_video_*.json sample_comments.json
.venv/bin/python -m evaluation.manage evaluate --annotations evaluation/dataset/annotations.json --predictions output/runs/RUN/analyzed_comments.json --output evaluation/metrics.json
.venv/bin/python -m pytest -q
```

生成 200 条跨视频分层样本与 100 条复杂样本，近重复组内取一条代表，固定 seed=42，100 dev + 200 test。人工按 annotation_manifest 中 schema 填写 gold、annotator 和 COMPLETE。冻结测试集只用于验收，不能把标签放进提示词。模型不会代替人工填写 gold；未完成人工标注时评测返回 PENDING_HUMAN_ANNOTATION。

指标采用实体表面名与类别的匹配；标注者使用同一规范名称。未成功处理的测试评论视为空预测，纳入漏检；报告每类支持数、未知观点数与自动覆盖率。理由支持率按人工标注的所属实体、原文引文与理由类别匹配。无理由预测时该指标为空，不能通过门槛。目标为实体 P≥95%/R≥85%，意图与实体动作 macro-F1≥85%，方法 micro-F1≥85%，理由支持率≥95%。阈值不是已实现的模型成绩。

主题抽查表在报告生成时提供；每主题最多 10 条，最多 10 个主题，需人工填相关/不相关，相关率≥80%才确认。未评审主题保持候选。

## 恢复与限制

原输入和旧输出保留。结果 JSON 原子写入，progress.json 展示选中任务进度；中断后 `--resume` 重建运行报告并复用已完成缓存。配额的 token 预留按 UTF-8 输入上界加最大输出保守估算；服务未返回 usage 或请求失败时按预留值计费统计，不表示精确消耗或费用。缺价格配置只报告 token。

目前交付为批处理分析、静态报告和验收工具；无自动交易、采集器或 ASDC 接口。真实 API 语义效果与中文聚类需要有效模型配置、依赖和人工标签验证。

DeepSeek 默认使用 deepseek-flash，thinking.type=disabled，减少推理耗尽输出额度后出现空正文的情况。缓存仍按模型、提示词、schema 与上下文复用；已通过校验的结果保留。

引文位置校正仅在引文在原文中唯一出现时启用；修正前后位置记于 evidence_offset_repairs。重复或原文中不存在的引文不自动校正。

## 全量分析与结论

本次全量任务使用 configs/full_analysis.json（并发8，上限12,000次请求/30,000,000 token），默认试跑配置保持不变。

```bash
.venv/bin/python run_pipeline.py --config configs/full_analysis.json --full --resume
.venv/bin/python build_conclusions.py output/runs/RUN
```

结论分为严格通过结果与包含待复核的探索性视图；按视频拆分，所有结论附原文链接。生成 conclusions.md / conclusions.json 并在 report.html 顶部加入摘要。不能用100条试跑结果生成全量结论。

## 公开仓库与本地数据

原始评论 JSON、人工标注数据、API 缓存和 `.env` 不纳入版本管理；分析结果已纳入 `output/`，包含历史试运行和全量结果。最新全量结论见 [conclusions.md](output/runs/20261005T102506056983/conclusions.md)，离线报告见同目录的 `report.html`。克隆后在根目录放入自己的评论 JSON，并根据 `.env.example` 配置模型凭据。
