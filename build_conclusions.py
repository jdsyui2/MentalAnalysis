"""Generate evidence-linked conclusions from a completed full JSON analysis."""

import argparse
import json
import html
from collections import Counter, defaultdict
from pathlib import Path

from core.report import write_json
from core.schema import METHOD_NAMES


def build(run):
    rows = json.loads((run / "analyzed_comments.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("pilot"):
        raise ValueError(
            "Conclusions require a full run; pilot data cannot represent the full batch"
        )
    quality = json.loads((run / "quality.json").read_text())
    ranks = json.loads((run / "ticker_consensus.json").read_text())
    strategies = json.loads((run / "strategy_ranking.json").read_text())
    topics = json.loads((run / "topics.json").read_text())
    valid = [r for r in rows if r["valid"]]
    parsed = [r for r in valid if r.get("analysis")]
    successful = [r for r in valid if r["status"] == "SUCCESS"]
    review = [r for r in valid if r["status"] == "NEEDS_REVIEW"]
    videos = defaultdict(list)
    intents = Counter()
    exploratory_methods = defaultdict(list)
    candidates = defaultdict(list)
    actions = Counter()
    resolved_views = []
    for r in rows:
        videos[r["aweme_id"]].append(r)
        if r.get("analysis"):
            intents.update(set(r["analysis"]["intents"]))
            for m in {m["method"] for m in r["analysis"]["methods"]}:
                exploratory_methods[m].append(r)
            for v in r["analysis"]["views"]:
                candidates[
                    (v["entity"], v["category"], v["resolved_entity"]["resolution"])
                ].append((r, v))
                if r["status"] == "SUCCESS":
                    actions[v["action"]] += 1
                    resolved_views.append((r, v))
    stock_etf_actions = [
        r
        for r in successful
        if any(
            v["category"] in ("STOCK", "ETF")
            and v["action"] in ("BUY", "HOLD", "WATCH")
            for v in r["analysis"]["views"]
        )
    ]
    specific_recommendations = [r for r in stock_etf_actions if "RECOMMENDATION" in r["analysis"]["intents"]]
    method_comments = sum(bool(r["analysis"]["methods"]) for r in successful)
    defensive_comments = sum(any(m["method"] in {"CASH_WAIT", "POSITION_RISK", "EXIT"} for m in r["analysis"]["methods"]) for r in successful)
    noninvestment = sum("NON_INVESTMENT" in r["analysis"]["intents"] for r in parsed)
    details = []
    for video, group in sorted(videos.items(), key=lambda x: (-len(x[1]), str(x[0]))):
        methods = Counter(
            m["method"]
            for r in group
            if r["status"] == "SUCCESS"
            for m in {m["method"]: m for m in r["analysis"]["methods"]}.values()
        )
        entities = Counter(
            v["resolved_entity"]["name"]
            for r in group
            if r["status"] == "SUCCESS"
            for v in r["analysis"]["views"]
        )
        details.append(
            {
                "video_id": video,
                "url": next((r["video_url"] for r in group if r["video_url"]), None),
                "records": len(group),
                "share": len(group) / len(rows),
                "valid": sum(r["valid"] for r in group),
                "status_counts": dict(Counter(r["status"] for r in group)),
                "methods": dict(methods.most_common()),
                "entities": dict(entities.most_common()),
            }
        )
    summary = {
        "run": str(run.resolve()),
        "model": manifest["model"],
        "valid_comments": len(valid),
        "structured_comments": len(parsed),
        "successful_comments": len(successful),
        "review_comments": len(review),
        "failed": sum(r["status"] == "FAILED" for r in valid),
        "unprocessed": sum(r["status"] == "SKIPPED" for r in valid),
        "noninvestment": noninvestment,
        "noninvestment_denominator": len(parsed),
        "intents": dict(intents),
        "specific_stock_etf_recommendation_comments": len(specific_recommendations),
        "stock_etf_action_comments": len(stock_etf_actions),
        "method_bearing_comments": method_comments,
        "defensive_method_comments": defensive_comments,
        "specific_recommendation_denominator": len(successful),
        "strict_assets": ranks,
        "strict_methods": strategies,
        "exploratory_methods": [
            {
                "method": k,
                "name": METHOD_NAMES[k],
                "count": len(v),
                "needs_review": sum(r["status"] == "NEEDS_REVIEW" for r in v),
                "examples": [r["comment_key"] for r in v[:5]],
            }
            for k, v in sorted(
                exploratory_methods.items(), key=lambda x: (-len(x[1]), x[0])
            )
        ],
        "unresolved_mentions": [
            {
                "entity": k[0],
                "category": k[1],
                "comments": len({r["comment_key"] for r, v in pairs}),
                "examples": [r["comment_key"] for r, v in pairs[:3]],
            }
            for k, pairs in sorted(candidates.items(), key=lambda x: -len(x[1]))
            if k[2] == "UNRESOLVED"
        ],
        "videos": details,
        "topics_status": topics["status"],
        "claims_verified": False,
        "acceptance": "PENDING_HUMAN_ANNOTATION",
    }
    write_json(run / "conclusions.json", summary)
    report = (run / "report.html").resolve()

    def evidence_link(row):
        return f"[原文](report.html#{row['comment_key']})"

    def md(text):
        return str(text).replace("|", "\\|").replace("\n", " ").replace("`", "\\`")

    lines = [
        "# 本批投资评论分析结论",
        "",
        f"使用 **{manifest['model']}** 对全部 **{len(valid):,} 条有效评论**提交分析；取得结构化结果 **{len(parsed):,} 条**，其中严格通过 **{len(successful):,} 条**、待复核 **{len(review):,} 条**，失败 **{summary['failed']} 条**、未处理 **{summary['unprocessed']} 条**。这些计数描述处理状态，不能解释为准确率。",
        "",
        "## 核心发现",
        "",
        f"**具体公司推荐稀疏**：严格结果中 {len(stock_etf_actions)} 条股票/ETF评论包含 BUY/HOLD/WATCH，其中同时被标为推荐意图的有 {len(specific_recommendations)} 条。动作不等于向他人推荐，例如‘今年开始投资QQQ了’属于本人投资经历。实体词典与待复核结果限制了覆盖，不能据此断言其他评论没有推荐。",
        "",
        f"**方法讨论更值得整理**：{method_comments} 条成功评论含投资方法；现金等待103条、仓位风控47条、退出交易44条，三类去重合计 {defensive_comments} 条。次数表示讨论频率，包含支持、反对和提及，不是策略支持率。",
        "",
        "**黄金分歧与纳指定投**：黄金59条严格提及中，看空25、看多9、未知22、中性3；纳斯达克100为21条，看多18、看空1、未知2。黄金讨论主要集中在第二个视频，纳指讨论主要来自第一个视频。短句‘相信国运，定投纳指’可能带反讽，不能仅凭模型标签认定真实共识。",
        "",
        f"**非投资与信息不足内容**：已取得结构化结果的评论中，{noninvestment} 条被模型归为非投资内容，占 {noninvestment / max(1, len(parsed)):.1%}；另有 {len(review)} 条需要复核。",
        "",
        "**视频来源明显不均衡**：下表列出每个视频贡献。跨视频差异应优先解释为样本和讨论场景差异，而不是时间趋势。",
        "",
        "| 视频 ID | 记录数 | 占全部记录 | 成功 | 待复核 |",
        "|---|---:|---:|---:|---:|",
    ]
    for d in details:
        lines.append(
            f"| {d['video_id']} | {d['records']} | {d['share']:.1%} | {d['status_counts'].get('SUCCESS', 0)} | {d['status_counts'].get('NEEDS_REVIEW', 0)} |"
        )
    lines += [
        "",
        "## 投资方法：严格统计",
        "",
        f"共 {method_comments} 条成功评论含方法标签；同时显示占全部成功评论与占方法评论比例。多标签合计可以超过100%，标签次数不是支持人数。",
        "",
        "| 方法 | 评论数 | 占成功评论 | 占方法评论 |",
        "|---|---:|---:|---:|",
    ]
    for s in strategies["ranking"]:
        lines.append(f"| {s['method_name']} | {s['count']} | {s['percentage']:.1f}% | {s['count'] / max(1, method_comments):.1%} |")
    lines += ["", "### 代表性方法原文", ""]
    for s in strategies["ranking"][:6]:
        matching = [
            r
            for r in successful
            if any(m["method"] == s["method"] for m in r["analysis"]["methods"])
        ]
        matching.sort(key=lambda r: (-len(r["raw_comment"]), r["comment_key"]))
        if matching:
            r = matching[0]
            lines.append(
                f"- **{s['method_name']}**：{md(next(m['evidence']['quote'] for m in r['analysis']['methods'] if m['method'] == s['method']))} {evidence_link(r)}"
            )
    lines += [
        "",
        "## 标的讨论：提及、动作与分歧",
        "",
        "标的不限于股票；无验证证券代码的名称保留为概念实体。方向样本不足10条不作稳定共识判断。动作次数包含本人操作，不能解释为向他人推荐次数。",
        "",
        "| 标的 | 类别 | 提及 | 买入/持有/关注动作 | 卖出/回避动作 | 看多 | 看空 | 中性 | 未知 | 分歧度 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for a in ranks:
        st = a["stances"]
        dis = f"{a['disagreement']:.2f}" if a["disagreement"] is not None else "—"
        lines.append(
            f"| {md(a['entity']['name'])} | {a['entity']['category']} | {a['mentions']} | {a['recommend_count']} | {a['oppose_count']} | {st.get('BULLISH', 0)} | {st.get('BEARISH', 0)} | {st.get('NEUTRAL', 0)} | {st.get('UNKNOWN', 0)} | {dis} |"
        )
    lines += ["", "### 标的理由及原文证据", ""]
    by_key = {r["comment_key"]: r for r in rows}
    for a in ranks[:10]:
        lines.append(
            f"- **{a['entity']['name']}**："
            + (
                "；".join(
                    f"{md(reason['summary'])}（{reason['mentions']}条）"
                    for reason in a["rationales"][:4]
                )
                or "原文没有可提取的明确理由。"
            )
        )
        for key in a["representative_comments"][:2]:
            r = by_key[key]
            lines.append(f"  - {md(r['raw_comment'][:300])} {evidence_link(r)}")
    lines += [
        "",
        "## 待复核视图与主题",
        "",
        "以下方法统计同时包含 NEEDS_REVIEW，仅用于发现线索，不与严格统计混用。",
        "",
        "| 方法 | 初步识别 | 其中待复核 |",
        "|---|---:|---:|",
    ]
    for s in summary["exploratory_methods"]:
        lines.append(f"| {s['name']} | {s['count']} | {s['needs_review']} |")
    lines += [
        "",
        f"中文主题发现状态：**{topics['status']}**。所有自动主题均为候选，尚未完成至少80%相关率的人工抽查。",
        "",
    ]
    for t in topics.get("topics", []):
        lines.append(
            f"- {t['name']}：{t['comment_count']} 条评论、{t['unique_texts']} 种文本；关键词 {', '.join(t['keywords'])}。"
        )
    lines += [
        "",
        "## 结论的适用范围",
        "",
        "- 这批数据来自三个视频，来源不均衡；不能据此推断全市场投资者偏好或全平台推荐榜。",
        f"- 输入采集元数据记录 {quality['collection_coverage']['expected_replies_from_main_sum']} 条预期楼中楼回复，实际未采集回复；当前结论仅覆盖已导入评论。",
        "- 无稳定用户 ID，无法判断独立投资者共识；相同文本不同评论身份仍保留。",
        "- 公司事实、投资理由和传闻均未进行外部核验；这些是评论者表达及模型归纳。",
        "- 缺少可比的完整时间窗口，因此仅有样本内日期分布，没有可靠的热度增长或衰退判断。",
        "- 人工准确率验收尚未完成；未知名称、反讽和信息不足内容仍需复核；待复核评论不会进入严格标的榜，词典覆盖缺口使榜单只是保守子集。",
        "",
        "[完整原文与结构化报告](" + "report.html" + ")",
    ]
    (run / "conclusions.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    intro = '<section id="conclusions"><h2>本批评论的主要结论</h2>'
    intro += f"<p>有效评论 {len(valid):,} 条，已取得结构化结果 {len(parsed):,} 条；成功 {len(successful):,} 条，待复核 {len(review):,} 条，失败 {summary['failed']} 条。人工准确性验收待完成。</p>"
    intro += f"<p>严格通过的评论中，{len(specific_recommendations)} 条同时包含股票/ETF动作和推荐意图，占 {len(specific_recommendations) / max(1, len(successful)):.1%}。不能把单纯提及当作买入推荐。</p>"
    intro += (
        "<p>最常见投资方法："
        + html.escape(
            "；".join(
                f"{s['method_name']} {s['count']}条" for s in strategies["ranking"][:5]
            )
        )
        + "。</p>"
    )
    intro += "<p>样本来自3个视频，来源不均衡；未采集楼中楼回复、无稳定用户ID、没有可比完整时间窗口。结论仅描述本批已采集评论，不代表全市场共识或预测收益。</p>"
    intro += '<p>黄金59条严格提及中看空25条、看多9条；纳斯达克100的21条提及中看多18条、看空1条。视频场景不同，反讽与未知表达需复核，不能解读为全市场共识。</p>'
    intro += '<p><a href="conclusions.md">详细结论与原文证据</a> · <a href="conclusions.json">结论数据</a></p></section>'
    body = (run / "report.html").read_text(encoding="utf-8")
    if '<section id="conclusions">' in body:
        start = body.index('<section id="conclusions">')
        end = body.index("</section>", start) + len("</section>")
        body = body[:start] + intro + body[end:]
    else:
        end = body.index("</h1>") + len("</h1>")
        body = body[:end] + intro + body[end:]
    (run / "report.html").write_text(body, encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    result = build(args.run)
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "valid_comments",
                    "structured_comments",
                    "successful_comments",
                    "review_comments",
                    "failed",
                    "unprocessed",
                    "noninvestment",
                    "specific_stock_etf_recommendation_comments",
                ]
            },
            ensure_ascii=False,
        )
    )
