"""Allowlist public aggregates; full artifacts are never copied to public output."""

import json
import html
from pathlib import Path
from .report import write_json, write_csv


def publish_redacted(run, output):
    run, output = Path(run), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    ranks = json.loads((run / "ticker_consensus.json").read_text())
    methods = json.loads((run / "strategy_ranking.json").read_text())
    summary = json.loads((run / "conclusions.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    quality = json.loads((run / "quality.json").read_text())
    # Free-form LLM summaries, evidence and user-provided arbitrary keys are not public.
    numeric_rank = [
        "mentions",
        "explicit_recommendation_count",
        "context_recommendation_count",
        "recommendation_count",
        "self_position_count",
        "self_position_buy_count",
        "hold_count",
        "watch_count",
        "avoid_count",
        "sell_count",
        "unique_text_mentions",
        "near_duplicate_cluster_mentions",
        "video_count",
        "video_total",
        "bullish_index",
        "directional_count",
        "bull_ratio",
        "disagreement",
        "engagement_adjusted_bull_ratio",
        "engagement_observed_comments",
        "video_balanced_score",
    ]
    public_ranks = []
    for a in ranks:
        e = a["entity"]
        public_ranks.append(
            {
                "entity": {
                    k: e.get(k)
                    for k in [
                        "entity_id",
                        "name",
                        "category",
                        "ticker",
                        "ts_code",
                        "layer",
                    ]
                },
                **{k: a.get(k) for k in numeric_rank},
                "stances": a["stances"],
                "actions": a["actions"],
                "speech_acts": a["speech_acts"],
                "reason_counts": [
                    {
                        "reason_code": r["reason_code"],
                        "stance": r["stance"],
                        "mentions": r["mentions"],
                    }
                    for r in a["rationales"]
                ],
            }
        )
    public_methods = {
        k: methods[k] for k in ["denominator", "method_bearing_comments", "multi_label"]
    }
    public_methods["ranking"] = [
        {
            k: m[k]
            for k in [
                "method",
                "method_name",
                "count",
                "percentage",
                "attitudes",
                "net_support_rate",
                "directional_count",
                "sample_status",
            ]
        }
        for m in methods["ranking"]
    ]
    public_manifest = {
        "schema_version": manifest["schema_version"],
        "prompt_version": manifest["prompt_version"],
        "generated_at": manifest["generated_at"],
        "model": manifest["model"],
        "pilot": manifest["pilot"],
        "run_status": manifest["run_status"],
        "promotion_state": "RESEARCH_ONLY",
        "catalog_coverage": manifest["catalog_coverage"],
        "catalog_gaps": manifest["catalog_gaps"],
        "input_hashes": [
            {
                "logical_source_id": f"source_{i + 1}",
                "sha256": f.get("sha256"),
                "status": f["status"],
            }
            for i, f in enumerate(manifest["files"])
        ],
    }
    public_quality = {
        k: quality[k]
        for k in [
            "raw_rows",
            "identity_records",
            "valid_records",
            "noise_records",
            "merged_observations",
            "missing_time",
            "missing_user_id",
            "reply_rows",
            "status_counts",
            "calls",
            "tokens",
            "cache_hits",
            "acceptance",
            "field_status_counts",
            "semantic_processed",
            "field_usable_comments",
        ]
        if k in quality
    }
    comparison = quality.get("v2_comparison", {})
    public_quality["v2_comparison"] = {
        k: comparison[k]
        for k in ("old_valid", "new_valid", "old_status_counts", "new_status_counts")
        if k in comparison
    }
    # Insights only reference entities already resolved to a controlled catalog.
    public_summary = {
        k: summary[k]
        for k in [
            "schema_version",
            "valid_comments",
            "structured_comments",
            "status_counts",
            "video_count",
            "acceptance",
            "promotion_state",
            "narrative",
            "claims_verified",
        ]
    }
    public_summary["insights"] = [
        {k: v for k, v in f.items() if k != "evidence_keys"}
        for f in summary["insights"]
    ]
    topics = json.loads((run / "topics.json").read_text())
    public_topics = {
        "status": topics["status"],
        "spaces": {
            k: {"status": v["status"], "unique_documents": v["unique_documents"]}
            for k, v in topics["spaces"].items()
        },
        "topics": [
            {
                "topic_id": f"topic_{i + 1}",
                "space": t["space"],
                "comment_count": t["comment_count"],
                "unique_texts": t["unique_texts"],
                "acceptance": t["acceptance"],
            }
            for i, t in enumerate(topics["topics"])
        ],
    }
    for name, data in [
        ("ticker_consensus", public_ranks),
        ("strategy_ranking", public_methods),
        ("quality", public_quality),
        ("manifest", public_manifest),
        ("conclusions", public_summary),
        ("topics", public_topics),
    ]:
        write_json(output / (name + ".json"), data)
    write_csv(output / "ticker_consensus.csv", public_ranks)
    write_csv(output / "strategy_ranking.csv", public_methods["ranking"])
    lines = (
        [
            "# 投资评论分析（公开脱敏版）",
            "",
            "RESEARCH_ONLY · PENDING_HUMAN_ANNOTATION",
            "",
            f"有效评论 {summary['valid_comments']} 条，来自 {summary['video_count']} 个视频。",
            "",
        ]
        + ["- " + t for t in summary["narrative"]]
        + [
            "",
            "仅含聚合与质量指标；不包含原文、昵称、评论或用户ID、来源明细及本机路径。历史公开提交仍含旧评论明细。",
        ]
    )
    (output / "conclusions.md").write_text("\n".join(lines) + "\n")
    sections = "<h1>投资评论分析（公开脱敏版）</h1>" + "".join(
        "<p>" + html.escape(t) + "</p>" for t in lines[2:]
    )
    for title, data in [
        ("投资选择", public_ranks),
        ("投资方法", public_methods),
        ("质量", public_quality),
    ]:
        sections += (
            "<h2>"
            + title
            + "</h2><pre>"
            + html.escape(json.dumps(data, ensure_ascii=False, indent=2))
            + "</pre>"
        )
    (output / "report.html").write_text(
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>投资评论分析</title><style>body{max-width:1100px;margin:30px auto;font:16px/1.6 sans-serif}pre{white-space:pre-wrap}</style>'
        + sections
        + "</html>"
    )
    return output
