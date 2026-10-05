"""Data-driven, evidence-constrained conclusions. No batch-specific numbers."""

import argparse
import html
import json
from pathlib import Path
from collections import Counter
from core.report import write_json
from core.presentation import (
    group_name,
    group_ranks,
    MATURITY,
    REPORT_VERSION,
    LIMITATIONS,
    TAXONOMY,
    markdown_boards,
    methods_with_evidence,
)


def insights(ranks, methods):
    facts = []

    def entity_fact(kind, a, fields):
        evidence = a.get("representative_comments", [])
        if kind == "RECOMMENDED":
            evidence = a.get("recommendation_comments", [])[:5]
        if kind == "AVOIDED":
            evidence = a.get("avoid_comments", [])[:5]
        if kind in ("DIRECTION", "DISAGREEMENT"):
            evidence = (
                a.get("direction_comments", {}).get("BULLISH", [])[:2]
                + a.get("direction_comments", {}).get("BEARISH", [])[:2]
            )
        return {
            "kind": kind,
            "board": group_name(a["entity"]),
            "entity_id": a["entity"]["entity_id"],
            "name": a["entity"]["name"],
            "metrics": {k: a[k] for k in fields},
            "evidence_keys": evidence,
            "verification": "UGC_UNVERIFIED",
        }

    for board in ("securities", "assets", "sectors"):
        recommended = sorted(
            (a for a in group_ranks(ranks)[board] if a["recommendation_count"]),
            key=lambda a: (-a["recommendation_count"], a["entity"]["entity_id"]),
        )
        for a in recommended[:3]:
            facts.append(
                entity_fact(
                    "RECOMMENDED",
                    a,
                    [
                        "recommendation_count",
                        "explicit_recommendation_count",
                        "context_recommendation_count",
                        "mentions",
                        "video_count",
                        "unique_text_mentions",
                        "near_duplicate_cluster_mentions",
                    ],
                )
            )
    headline_ranks = [
        a
        for a in ranks
        if group_name(a["entity"]) in ("securities", "assets", "sectors")
    ]
    for a in sorted(
        (a for a in headline_ranks if a["avoid_count"] + a["sell_count"]),
        key=lambda a: -(a["avoid_count"] + a["sell_count"]),
    )[:3]:
        facts.append(
            entity_fact("AVOIDED", a, ["avoid_count", "sell_count", "mentions"])
        )
    sufficient = [a for a in headline_ranks if a["directional_count"] >= 10]
    for a in sorted(
        sufficient, key=lambda a: (-(a["disagreement"] or 0), a["entity"]["entity_id"])
    )[:3]:
        facts.append(
            entity_fact(
                "DISAGREEMENT",
                a,
                ["directional_count", "disagreement", "bull_ratio", "stances"],
            )
        )
    for a in sorted(
        sufficient,
        key=lambda a: (
            -max(a["bull_ratio"], 1 - a["bull_ratio"]),
            a["entity"]["entity_id"],
        ),
    )[:3]:
        facts.append(
            entity_fact("DIRECTION", a, ["directional_count", "bull_ratio", "stances"])
        )
    for m in sorted(
        (m for m in methods["ranking"] if m["attitudes"].get("SUPPORT")),
        key=lambda m: (-m["attitudes"].get("SUPPORT", 0), m["method"]),
    )[:5]:
        facts.append(
            {
                "kind": "METHOD_SUPPORT",
                "name": m["method_name"],
                "metrics": {
                    "attitudes": m["attitudes"],
                    "net_support_rate": m["net_support_rate"],
                    "count": m["count"],
                    "directional_count": m["directional_count"],
                },
                "evidence_keys": m.get("support_comment_keys", [])[:5],
            }
        )
    return facts


def narrative(facts):
    lines = []
    for f in facts:
        m = f["metrics"]
        name = f["name"]
        if f["kind"] == "RECOMMENDED":
            text = f"[{TAXONOMY['titles'][f['board']]}] {name}：推荐表达{m['recommendation_count']}条（明确{m['explicit_recommendation_count']}、上下文{m['context_recommendation_count']}），涉及{m['video_count']}个视频；全部提及按唯一文本折叠后{m['unique_text_mentions']}条，近重复分组后{m['near_duplicate_cluster_mentions']}组。"
        elif f["kind"] == "AVOIDED":
            text = f"{name}：回避动作{m['avoid_count']}条、卖出动作{m['sell_count']}条；动作不一定是向他人建议。"
        elif f["kind"] == "DISAGREEMENT":
            text = f"{name}：有效方向样本{m['directional_count']}条，分歧度{m['disagreement']:.2f}；方向分布{m['stances']}。"
        elif f["kind"] == "DIRECTION":
            text = f"{name}：有效方向样本{m['directional_count']}条，看多占方向样本{m['bull_ratio']:.1%}。这描述评论观点，不预测收益。"
        else:
            attitudes = m["attitudes"]
            rate = (
                f"{m['net_support_rate']:.1%}"
                if m["net_support_rate"] is not None
                else "无方向样本"
            )
            text = (
                f"{name}：支持{attitudes.get('SUPPORT', 0)}、反对{attitudes.get('OPPOSE', 0)}、自用{attitudes.get('SELF_PRACTICE', 0)}条，净支持率{rate}（分母：支持＋反对 {m['directional_count']} 条）；"
                + (
                    "方向样本不足10条。"
                    if m["directional_count"] < 10
                    else "多标签统计。"
                )
            )
        lines.append(text)
    return lines or ["当前通过校验的数据不足以生成推荐、方法支持或稳定方向结论。"]


def build(run):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest.get("pilot"):
        raise ValueError(
            "Conclusions require a full run; pilot data cannot represent the full batch"
        )
    quality = json.loads((run / "quality.json").read_text())
    ranks = json.loads((run / "ticker_consensus.json").read_text())
    methods = json.loads((run / "strategy_ranking.json").read_text())
    rows = json.loads((run / "analyzed_comments.json").read_text())
    valid = [r for r in rows if r["valid"]]
    facts = insights(ranks, methods)
    summary = {
        "schema_version": "3.0",
        "report_version": REPORT_VERSION,
        **MATURITY,
        "valid_comments": len(valid),
        "structured_comments": sum(bool(r.get("analysis")) for r in valid),
        "status_counts": dict(Counter(r["status"] for r in valid)),
        "video_count": len({r["aweme_id"] for r in valid if r.get("aweme_id")}),
        "acceptance": "PENDING_HUMAN_ANNOTATION",
        "promotion_state": "RESEARCH_ONLY",
        "insights": facts,
        "narrative": narrative(facts),
        "claims_verified": False,
    }
    write_json(run / "conclusions.json", summary)
    lines = [
        "# 投资评论分析结论",
        "",
        f"有效评论 {len(valid):,} 条；处理状态 {summary['status_counts']}；来自 {summary['video_count']} 个视频。",
        "",
        "状态计数不是准确率。以下结论基于通过字段校验的表达，待复核字段不参与相应统计。",
        "",
        "RESEARCH_ASSIST · RESEARCH_ONLY · PENDING_HUMAN_ANNOTATION",
        "",
        LIMITATIONS,
        "",
        "## 数据支持的发现",
        "",
    ]
    by_key = {r["comment_key"]: r for r in rows}
    for fact, text in zip(facts, summary["narrative"]):
        lines.append("- " + text)
        for key in fact["evidence_keys"][:2]:
            if key in by_key:
                lines.append("  - [查看原文](report.html#" + key + ")")
    if not facts:
        lines += summary["narrative"]
    lines += [
        "",
        "## 适用范围",
        "",
        "- 推荐、本人持仓、关注和卖出分别统计；不把动作次数当推荐次数。",
        "- 未验证视频提问时，不启用视频上下文推荐；短回复和反讽仍可能漏检。",
        "- 重复文本及视频平衡视图仅调整样本口径，不能替代独立用户统计。",
        f"- 实际回复记录 {quality.get('reply_rows', 0)} 条；不声称完整评论区覆盖或全市场共识。",
        "- 缺少可比完整时间窗口时，只展示样本时间分布。",
        "- 公司事实、传闻、理由未经外部核验。人工准确率和主题相关率待验收。",
        "",
        "[完整报告](report.html) · [质量指标](quality.json)",
    ]
    lines += ["", markdown_boards(ranks, methods_with_evidence(methods, rows))]
    (run / "conclusions.md").write_text("\n".join(lines) + "\n")
    intro = (
        '<section id="conclusions"><h2>主要结论</h2><p>RESEARCH_ASSIST · RESEARCH_ONLY · 人工准确性待验收</p><ul>'
        + "".join("<li>" + html.escape(t) + "</li>" for t in summary["narrative"])
        + "</ul></section>"
    )
    report = run / "report.html"
    if report.exists():
        body = report.read_text()
        if '<section id="conclusions">' in body:
            start = body.index('<section id="conclusions">')
            end = body.index("</section>", start) + len("</section>")
            body = body[:start] + intro + body[end:]
        else:
            end = body.index("</h1>") + len("</h1>")
            body = body[:end] + intro + body[end:]
        report.write_text(body)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    a = parser.parse_args()
    print(json.dumps(build(a.run), ensure_ascii=False))
