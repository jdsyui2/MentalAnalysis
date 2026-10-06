# v3.2.1 Coordination Evidence & PIT Calibration

104条路维光电新版分析全部成功；第一层104条均为INSUFFICIENT_EVIDENCE。本次原始243次请求（包括35个原子单元判断）耗时约59秒；缓存重放新增请求0。两层问题保持独立，默认并发4。

适配EquityCrawler content / point_in_time / observation和legacy字段；簇级证据保留缺失。新标签不代表真人认证。104条缺少available_at，PIT检查全部拒绝，未补造采集时间。

200条协同Gold候选准备完成：100条按证据排序、100条随机；50条开发、150条冻结，近重复簇不跨集合。人工完成0条，F1/Brier/ECE/bootstrap95%区间均未测量。校准未拟合，ASDC信号未就绪。

Pipeline C通过引文位置、目标代码、主体关系门禁后，对35个本地规则提取单元进行闭集判断。全原文保留否定上下文。外部标的禁止生成目标方向，产业链关系需复核。这不是已验收LLM管线，三方精度横评仍待Gold及可比预测。

本目录仅包含脱敏聚合；完整原文、作者/评论标识、来源细节、Gold候选及密钥不公开。详见docs/JEV_321.md。
