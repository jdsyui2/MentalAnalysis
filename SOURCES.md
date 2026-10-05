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
