# 设计参考与许可

本实现重新编写 Python 管道，没有复制以下项目源码、数据集或模型权重。引用用来记录设计依据，不表示集成了对应模型。直接复用时须单独保留许可证并核查数据/权重条款。

|项目|研究提交|借鉴|
|---|---|---|
|actionow-ai/x2t|f90487430f8d93fa245f81ac7b37a2014301e3b5|逐标的观点、schema、状态重试|
|StephanAkkerman/reddit-stock-analyzer|0ac6498756122a3a92fa129d4fb8db0b511acd03|分标的上下文、双窗口、时间分布|
|AI4Finance-Foundation/FinGPT|fdb04c9a273d1ccc3764b09b8e3ed1e708e57566|金融NER/情绪/关系的任务划分|
|aniketcomps/BERT-Topic-Modeling|317a4732618588aa7bc9b09f31302b0d8bfae23e|BERTopic主题词与聚类|
|K0EKJE/Market-Sentiment-Analysis|fa55add689ce5da20d564a6fc8ffd7d7d2bcd5de|中文金融语料与看多指数|
|JDKrasnick/MarketSent|0dfd2b50797763c285496e6db49e772fb1623253|静态快照、来源状态|
|thunlp/Chinese_NRE|2cd47e6dc1b95e8ca3e93b5b8567666c37c5d654|关系标注与评测定义|

BERTopic、BGE 的模型/库版本安装后记录于运行环境清单；聚类效果须经本项目人工抽查。未下载或使用上游训练数据。

## 3.0 实体目录来源

- 深交所A股名单：`https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1`。
- 深交所基金名单：同一官网报表接口，`CATALOGID=1105`；仅纳入类别明确为ETF或REIT的记录。
- 上交所股票及基金名称：官网页面使用的 `https://www.sse.com.cn/js/common/ssesuggestdata.js`、`ssesuggestfunddata.js`、`ssesuggestdataAll.js`；按证券代码范围及明确产品名称选取，不把000开头的国债识别成指数。
- 已核实上证指数子集：`https://www.sse.com.cn/market/sseindex/indexlist/index.shtml?classid=010202`；上证指数、上证50、上证180、科创50。未声称完整指数名录。

实际源文件摘要、记录数、生成时间与覆盖缺口见 `configs/entity_catalog.json`。本地归档位于忽略的 `local/catalog_sources`，未复制训练数据。证券目录是研究用快照；历史简称、部分上市日期和北交所名单不完整。未配置ASDC快照时不读取其数据库或凭据。

## 本批上下文获取

尝试读取三个抖音公开页面及按视频ID检索，网页不可访问、Chrome工具超时、搜索未返回结果。因此 `configs/video_context.json` 保留来源URL、失败状态和空正文；未从评论推断视频问题。上下文推荐保持关闭。

BGE本地推理权重来自 [BAAI/bge-small-zh-v1.5 模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)，模型卡标注MIT；权重未纳入Git仓库，未下载其训练数据。完整运行报告记录安装包版本，模型缓存提交标识另记录在验证清单中。
