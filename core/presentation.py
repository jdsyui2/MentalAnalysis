"""Report-only classification and shared safe tables; no extraction changes."""

import html
import json
from pathlib import Path

REPORT_VERSION = "3.1.0"
TAXONOMY = json.loads(
    (Path(__file__).resolve().parents[1] / "configs/report_taxonomy.json").read_text()
)
MATURITY = {
    "maturity_level": "RESEARCH_ASSIST",
    "promotion_state": "RESEARCH_ONLY",
    "acceptance": "PENDING_HUMAN_ANNOTATION",
    "engineering_ready": True,
    "research_assist_ready": True,
    "model_accuracy_validated": False,
    "investment_signal_ready": False,
    "asdc_factor_ready": False,
}
LIMITATIONS = "一级评论样本；人工准确率尚未验收。视频提问缺失，短回复的推荐属性可能低估，具体证券推荐数量尚未定稿。"


def group_name(entity):
    if entity.get("entity_id") in TAXONOMY["generic_entity_ids"]:
        return "other"
    if (
        entity.get("layer") == TAXONOMY["security_layer"]
        and entity.get("category") in TAXONOMY["security_categories"]
    ):
        return "securities"
    return TAXONOMY["category_routes"].get(entity.get("category"), "other")


def group_ranks(ranks):
    groups = {k: [] for k in TAXONOMY["titles"]}
    for rank in ranks:
        groups[group_name(rank["entity"])].append(rank)
    return groups


def product_label(entity):
    if entity.get("category") in ("ETF", "REIT"):
        return (
            "具体基金"
            if entity.get("ticker") or entity.get("ts_code")
            else "基金概念（未指定产品）"
        )
    return entity.get("category", "UNKNOWN")


def evidence_links(keys, local):
    if not local:
        return "仅公开聚合；原文证据保留本地"
    return (
        " ".join(
            '<a href="#' + html.escape(k, quote=True) + '">原文</a>' for k in keys[:5]
        )
        or "无证据"
    )


def table(headers, rows):
    return (
        "<table><tr>"
        + "".join("<th>" + html.escape(str(h)) + "</th>" for h in headers)
        + "</tr>"
        + (
            "".join(
                "<tr>"
                + "".join("<td>" + html.escape(str(c)) + "</td>" for c in cells)
                + "<td>"
                + links
                + "</td></tr>"
                for cells, links in rows
            )
            if rows
            else '<tr><td colspan="'
            + str(len(headers))
            + '">暂无通过校验的数据</td></tr>'
        )
        + "</table>"
    )


def render_boards(ranks, methods, local=True):
    groups = group_ranks(ranks)
    parts = []
    for key in (
        "securities",
        "assets",
        "sectors",
        "methods",
        "unbound_companies",
        "other",
    ):
        title = "投资方法" if key == "methods" else TAXONOMY["titles"][key]
        parts.append('<section id="board-' + key + '"><h2>' + title + "</h2>")
        if key == "methods":
            parts.append(
                "<p>多标签；讨论占比的分母为有效评论 "
                + str(methods.get("denominator", 0))
                + " 条。净支持率＝（支持−反对）／（支持＋反对），自用不计入支持。</p>"
            )
            data = []
            for m in methods.get("ranking", []):
                n = m["attitudes"].get("SUPPORT", 0) + m["attitudes"].get("OPPOSE", 0)
                rate = "—" if not n else f"{m['net_support_rate']:.1%}"
                cells = (
                    [
                        m["method_name"],
                        m["count"],
                        f"{m['count'] / methods['denominator']:.1%}"
                        if methods.get("denominator")
                        else "—",
                    ]
                    + [
                        m["attitudes"].get(k, 0)
                        for k in (
                            "SUPPORT",
                            "OPPOSE",
                            "SELF_PRACTICE",
                            "QUESTION",
                            "MENTION",
                            "UNKNOWN",
                        )
                    ]
                    + [rate, str(n) + ("（样本不足）" if n < 10 else "")]
                )
                data.append(
                    (
                        cells,
                        evidence_links(
                            m.get(
                                "representative_comments",
                                m.get("support_comment_keys", []),
                            ),
                            local,
                        ),
                    )
                )
            parts.append(
                table(
                    [
                        "方法",
                        "讨论",
                        "占有效评论",
                        "支持",
                        "反对",
                        "自用",
                        "询问",
                        "提及",
                        "未知",
                        "净支持率",
                        "支持＋反对分母",
                        "证据",
                    ],
                    data,
                )
            )
        else:
            parts.append(
                "<p>推荐、本人持仓与动作分别计数；视频覆盖分母为本批有效评论涉及的视频数。看多占比分母为明确看多＋看空的方向样本。</p>"
            )
            data = []
            for a in groups[key]:
                e = a["entity"]
                n = a["directional_count"]
                cells = (
                    [
                        e["name"],
                        e.get("ts_code") or e.get("ticker") or "—",
                        product_label(e),
                    ]
                    + [
                        a[k]
                        for k in (
                            "mentions",
                            "explicit_recommendation_count",
                            "context_recommendation_count",
                            "self_position_count",
                            "avoid_count",
                            "sell_count",
                        )
                    ]
                    + [
                        str(n) + ("（样本不足）" if n < 10 else ""),
                        f"{a['bull_ratio']:.1%}"
                        if n and a.get("bull_ratio") is not None
                        else "—",
                        f"{a['video_count']}/{a['video_total']}",
                    ]
                )
                data.append(
                    (cells, evidence_links(a.get("representative_comments", []), local))
                )
            parts.append(
                table(
                    [
                        "对象",
                        "代码",
                        "类别",
                        "提及",
                        "明确推荐",
                        "上下文推荐",
                        "本人持仓",
                        "回避",
                        "卖出",
                        "方向分母",
                        "看多占比",
                        "视频覆盖",
                        "证据",
                    ],
                    data,
                )
            )
        parts.append("</section>")
    return "\n".join(parts)


def markdown_boards(ranks, methods, local=True):
    """Reuse escaped HTML tables in Markdown; public evidence is explicitly withheld."""
    return render_boards(ranks, methods, local)


def methods_with_evidence(methods, rows):
    import copy
    from .validation import usable, passed

    result = copy.deepcopy(methods)
    refs = {}
    for r in rows:
        if usable(r):
            for m in (r.get("analysis") or {}).get("methods", []):
                if passed(m, "type"):
                    refs.setdefault(m["method"], []).append(r["comment_key"])
    for m in result.get("ranking", []):
        m["representative_comments"] = sorted(set(refs.get(m["method"], [])))[:5]
    return result
