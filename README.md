# MentalAnalysis v3.1

可追溯的中文投资评论批量分析：分别识别推荐、本人持仓、询问、预测、方法态度和理由，提供本地原文报告与公开脱敏结果。当前用途为 **RESEARCH_ASSIST（研究辅助可用）**，保留 **RESEARCH_ONLY / PENDING_HUMAN_ANNOTATION**，测试通过不代表模型准确率达标。

## 安装与运行

需要 Python 3.10+。推荐创建虚拟环境后安装：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[test,topics,catalog]'
cp .env.example .env
```

在 `.env` 填写 `MENTAL_BASE_URL`、`MENTAL_API_KEY`、`MENTAL_MODEL`；默认 DeepSeek、`deepseek-flash`、关闭 thinking。凭据不会写入报告或 Git。没有价格配置时只记录 token，不估算金额。

```bash
# 输入检查：不调用模型或写报告
.venv/bin/python run_pipeline.py --input-manifest configs/input_manifest.json --dry-run
# 分视频抽取100条真实评论，试运行不会发布公开结果
.venv/bin/python run_pipeline.py --input-manifest configs/input_manifest.json --resume
# 全量：本地完整结果位于 local/runs，公开脱敏版位于 output/public
.venv/bin/python run_pipeline.py --input-manifest configs/input_manifest.json --config configs/full_analysis.json --full --resume
# 仅重建3.0报告与统计，无API调用
.venv/bin/python -m scripts.rebuild_report local/runs/RUN --public output/public/RUN
```

保留 `--input`、`--output-dir`、`--config`、`--resume`、`--dry-run`、`--full`、`--analysis-cutoff`；新增 `--input-manifest`、`--context-file`、`--entity-catalog`。显式清单优先于 `--input`。默认仅扫描根目录 JSON，排除 `sample_* / fixture_* / test_*`。`is_sample` 描述采集范围，不控制是否导入。本批三个正式视频均带采样标记；样例和31条摘录通过清单明确排除。

默认并发2、60秒超时、最多3次尝试；全量配置并发8、12,000次调用／30,000,000 token上限。结构解析失败重试；字段证据失败隔离相应字段。达到配额保存缓存与进度，未处理任务不填为中性。恢复仍在新的独立运行目录生成报告。

## 数据口径与字段校验

- 同平台评论ID合并；无ID只有同视频、规范文本唯一对应并且至少两个附加元数据一致才合并，缺失值不算匹配、存在冲突不合并。短投资建议保留，空白与纯表情过滤。
- 原文、来源观察和时间保留在本地；昵称不充当独立用户ID，缺时间不从文件名推断。身份内容冲突阻止整条正式统计。
- 字段状态为 `PASS / REVIEW / FAIL / NOT_APPLICABLE`。评论为 `SUCCESS / PARTIAL / FAILED / SKIPPED`；`PARTIAL`中的合法实体、方法和风险独立参与统计。整条JSON非法仍失败。
- 引文带 `COMMENT / VIDEO / PARENT / ROOT` 来源、字符位置；仅唯一原文引文允许修复偏移并留记录。实体、明确动作、立场与理由的证据来自评论。
- `configs/video_context.json` 保存逐视频来源、标题、提问、原文与读取状态。只有来源、时间和原文问题齐全并经验证的投资征集才能支持上下文推荐。当前三个视频网页及浏览器访问失败，上下文留空，短回复不自动补BUY。之后补上下文会使缓存自动失效。
- `configs/entity_catalog.json` 合并交易所证券、全球资产及概念三层目录；模型不能自行生成代码。证券候选仅供消歧，“我爱我家”“老百姓”“机器人”等普通短语不能仅凭字面映射股票。泛指黄金、纳指ETF等概念不指定某个金融产品。
- 已归档深交所A股／基金名录、上交所官网证券名称数据；目录记录来源、摘要和覆盖。北交所、全球证券、历史简称及部分上市日期不完整，指数仅为已核实子集；不是完整全球证券库。
- `scripts/build_catalog.py --import-snapshot FILE` 支持带来源与日期的标准化ASDC快照，输入为 `{"entities": [...]}`，条目采用当前目录格式。不会修改ASDC。无导入参数时使用本地归档的交易所名录，所需文件和URL见目录 sources。
- 方法分类以 `configs/strategy_taxonomy.json` 为唯一来源，不用关键词直接分类。理由按 `reason_code` 与观点方向聚合；公司事实、传闻与预测均未经外部核验。

## 统计与主题

推荐按逐标的 `speech_act` 判断，区分明确／上下文推荐、自持、关注、回避、卖出；不再用BUY/HOLD/WATCH合计当推荐。一个评论可对同一实体有多种言语行为；提及只计一次，相互冲突的方向计UNKNOWN。

方法统计区分支持、反对、自用、询问、提及与未知。净支持率为 `(支持−反对)/(支持+反对)`；无方向样本时为空，少于10条标明不足。比例注明分母，多标签可超过100%。强度和模型自报置信度不作为投票权重。

同时输出评论次数、唯一文本次数、相似度0.9的确定性近重复组、逐视频提及率及其均值（没有提及的视频计零）。这些都不是独立用户数。点赞辅助采用视频内百分位并以 `1+percentile` 加权，缺失点赞不补零，不合成单一最终分数。

主题分方法、标的、理由、风险四个空间，分别用通过校验的字段选样本；每空间不足50种文本不聚类。BGE中文向量、固定种子42、中文1–3词组合及领域停用词，使用MMR代表词、中心原文和缓存的DeepSeek名称；命名失败退回关键词，保留离群项。所有主题人工确认前均为候选。

趋势只有在显式截止时间、输入声明完整且可比的窗口、配置开启三者同时满足时生成；否则仅输出上海时区的样本日期分布。没有时间覆盖证据不生成新出现／衰退主题。

## 人工标注与测试

```bash
.venv/bin/python -m evaluation.manage prepare --input comments_video_1791117359379.json comments_video_1791131714769.json comments_video_1791162762327.json --output evaluation/dataset_v3
.venv/bin/python -m evaluation.manage evaluate --annotations evaluation/dataset_v3/annotations.json --predictions local/runs/RUN/analyzed_comments.json --output local/evaluation_v3.json
.venv/bin/python -m pytest -q
```

400条真实评论：200条分层随机、200条挑战样本，100开发／300冻结验收；同一近重复组不跨集合。50条准备双人标注，`gold`与`second_annotation`必须由人工填写，完成后可计算多标签意图的一致性。`canonical_ids`用view序号字符串映射到目录ID，无法解析项人工填写明确的UNRESOLVED标记。原标注集保留；准备工具拒绝覆盖已有完整gold。

评测分别报告实体span、标准ID、意图、言语行为、立场、动作、方法类型／态度和理由precision／recall／F1；失败和被拒绝字段作为漏检，同时报告类别样本量、未知率和自动覆盖。实体P≥95%／R≥85%；意图、动作、言语行为、立场F1≥85%；方法与态度micro-F1≥85%；理由支持率≥95%。这些是目标，不是已达到成绩。人工标注不足不输出假精度，模型不会替代人工gold。

主题抽查每个最多10条、最多10个主题，相关率≥80%才确认。CI在Python3.10和3.12运行mock测试，不调用真实模型。当前未完成人工标注，不做置信度校准或研究就绪晋级。

## 结果、公开数据与兼容

本地 `local/runs/RUN` 保存完整评论、字段、证据、复核队列、失败、主题、统计、结论及质量；`local/runs/cache`存语义缓存，`resolution_cache`存目录解析缓存。缓存包含实际提示词／schema／上下文／目录候选／参数摘要，验证与解析实现也有摘要，旧2.0结果不会充当3.0缓存。

公开 `output/public/RUN` 仅保留受控实体聚合、理由代码计数、方法态度、候选主题数量、质量、结论和脱敏HTML；不包含评论原文、昵称、评论／用户ID、来源明细、自由文本理由或本机绝对路径。

**v3.1 已将当前分支的旧 `output/runs/` 原文输出移出，123 个文件经 SHA-256 核对后备份至本地忽略目录 `local/legacy_public_backup/daaba8b/`。Git 历史未重写，历史提交仍可访问旧评论原文和元数据。** README的原始输入忽略规则不意味着历史输出已脱敏。

3.0输出字段与2.0不兼容：`recommend_count`移除，使用明确／上下文推荐计数；`NEEDS_REVIEW`对应新版字段级`PARTIAL`，不是同口径数量。旧结果保留用于比较；回滚可使用2.0提交及其独立结果，不把3.0缓存交给2.0。始终保持RESEARCH_ONLY，直至人工验收完成。

## 已完成的3.0运行

- [公开结论](output/public/20261005T111901191947/conclusions.md)
- [公开质量与验证](output/public/20261005T111901191947/verification.json)
- [公开报告文件](output/public/20261005T111901191947/report.html)（下载后离线打开）

3,829条有效评论全部取得结构化结果：2,629条SUCCESS、1,200条PARTIAL；167条空白／纯表情SKIPPED，未处理有效评论和请求失败均为0。缓存复跑0次API调用、0新增token，标的、方法、时间统计一致。四类主题全部完成，仍待人工确认。两个Python版本的回归测试通过；人工gold为0／300，视频上下文未获取，不能把运行完成等同于研究准确率验收。


## v3.1 报告收尾

- [最新公开结论](output/public/20261005T111901191947-v3.1/conclusions.md)
- [最新公开报告](output/public/20261005T111901191947-v3.1/report.html)（下载后离线打开）
- [修订验证记录](output/public/20261005T111901191947-v3.1/verification.json)

首页按具体证券、资产／指数、行业／板块、投资方法展示。证券榜仅含 SECURITY 层的股票、ETF、REIT；指数单列资产／指数，全球基金区分具体产品与泛化基金概念。泛指“个股”等进入其他讨论对象附录，尚未绑定标准证券代码的公司名称单列。分类配置唯一来源为 `configs/report_taxonomy.json`，不改变实体解析结果。

软件版本 3.1.0；语义 schema 仍为 3.0，提示词、目录、校验与缓存保持冻结。本次仅重建报告，新增 API 调用和 token 为零，底层统计与原运行一致。独立本地报告位于 `local/report_revisions/20261005T111901191947-v3.1/`，源 v3.0 结果保留。

```bash
.venv/bin/python -m scripts.rebuild_report local/runs/RUN --revision-output local/report_revisions/NEW_REVISION --public output/public/NEW_REVISION
```

修订目录必须是新目录；记录源运行 ID、报告版本、修订时间及代码哈希。方法净支持率显示支持＋反对的实际分母，小于10条标明样本不足。公开版只发布聚合，原文证据在本地报告；HTML和Markdown使用同一四榜布局。

工程就绪、研究辅助可用，**模型准确率未验证、投资信号未就绪、ASDC因子未就绪**。成熟度描述用途，不表示精度已达标。400条标注集（100开发／300冻结验收）尚待人工填写；旧200条验收占位结果归档为 `evaluation/legacy_v2_metrics.json`。

当前仅分析已采集一级评论；视频提问仍缺失，单独标的名等短回复的推荐属性可能低估，具体证券推荐数量尚未定稿。补齐有出处的视频问题后需要重新抽取；完成真实人工验收后才考虑 RESEARCH_READY。不以评论结论预测收益。
