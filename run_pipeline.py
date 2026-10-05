"""Traceable investment-comment pipeline; old output is never overwritten."""

import argparse
import asyncio
import json
import importlib.metadata
import sys
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from core.ingestion import ingest, digest
from core.extractor import SemanticExtractor
from core.entities import EntityResolver
from core.aggregator import aggregate
from core.topics import discover_topics
from core.report import write_json, write_csv, make_report
from core.schema import SCHEMA_VERSION, PROMPT_VERSION

ROOT = Path(__file__).resolve().parent


def load_local_environment(path=ROOT / ".env"):
    """Local ignored credentials; explicit process environment takes precedence."""
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() in ("MENTAL_BASE_URL", "MENTAL_API_KEY", "MENTAL_MODEL"):
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def arguments():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        nargs="+",
        type=Path,
        help="JSON files or directories; default root JSON",
    )
    p.add_argument("--output-dir", type=Path, default=ROOT / "output" / "runs")
    p.add_argument("--config", type=Path, default=ROOT / "configs" / "pipeline.json")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Reuse persistent validated semantic cache",
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Inspect inputs only; no API or files"
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="Process full batch instead of 100-comment pilot",
    )
    p.add_argument(
        "--analysis-cutoff",
        help="ISO timestamp with timezone; required for comparable trends",
    )
    return p.parse_args()


async def run(args):
    load_local_environment()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    api = config.get("api", {})
    for key, default in [
        ("concurrency", 2),
        ("timeout_seconds", 60),
        ("max_attempts", 3),
        ("max_output_tokens", 4096),
    ]:
        if (
            not isinstance(api.get(key, default), (int, float))
            or api.get(key, default) <= 0
        ):
            raise ValueError(key + " must be positive")
    for key, default in [("max_calls", 300), ("max_tokens", 2000000)]:
        if not isinstance(api.get(key, default), int) or api.get(key, default) < 0:
            raise ValueError(key + " must be a nonnegative integer")
    if not isinstance(api.get("max_attempts", 3), int) or not isinstance(
        api.get("concurrency", 2), int
    ):
        raise ValueError("max_attempts and concurrency must be integers")
    if args.analysis_cutoff:
        config["analysis_cutoff"] = args.analysis_cutoff
    if (
        config.get("analysis_cutoff")
        and datetime.fromisoformat(config["analysis_cutoff"]).tzinfo is None
    ):
        raise ValueError("analysis_cutoff must include timezone")
    paths = []
    for p in args.input or [ROOT]:
        paths.extend(p.glob("*.json") if p.is_dir() else [p])
    records, files, quality, invalid = ingest(paths)
    if args.dry_run:
        print(
            json.dumps(
                {"files": files, "quality": quality}, ensure_ascii=False, indent=2
            )
        )
        return None
    stamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%dT%H%M%S%f")
    output = args.output_dir / stamp
    output.mkdir(parents=True)
    write_json(output / "normalized_comments.json", records)
    write_json(output / "invalid_records.json", invalid)
    cache = args.output_dir / "cache" if args.resume else output / "cache"
    extractor = SemanticExtractor(config.get("api", {}), cache)
    resolver = EntityResolver(ROOT / "configs" / "entities.json")
    valid = [r for r in records if r["valid"]]
    # Pilot samples across sorted identities rather than taking only one video's first page.
    valid = sorted(valid, key=lambda r: digest(r["comment_key"]))
    selected = valid if args.full else valid[: config.get("pilot_size", 100)]
    selected_keys = {r["comment_key"] for r in selected}
    results = {}

    async def work(r):
        result = await extractor.analyze(r)
        if result.get("analysis"):
            for view in result["analysis"]["views"]:
                view["resolved_entity"] = resolver.resolve(view)
                view["verification"] = "UGC_UNVERIFIED"
            if r["conflicts"] or any(
                v["resolved_entity"]["resolution"] == "UNRESOLVED"
                for v in result["analysis"]["views"]
            ):
                result.update(
                    status="NEEDS_REVIEW",
                    reason="IDENTITY_CONFLICT_OR_UNRESOLVED_ENTITY",
                )
        results[r["comment_key"]] = result
        write_json(
            output / "progress.json",
            {
                "completed": len(results),
                "selected": len(selected),
                "calls": extractor.calls,
                "tokens": extractor.tokens,
            },
        )

    await asyncio.gather(*(work(r) for r in selected))
    analyzed = []
    for r in records:
        result = results.get(
            r["comment_key"],
            {
                "status": "SKIPPED",
                "reason": "NOISE" if not r["valid"] else "PILOT_LIMIT",
                "analysis": None,
            },
        )
        analyzed.append(r | result)
    # Coverage assertions must be supported by input metadata, not inferred from date extrema.
    coverage_ok = all(
        (f.get("coverage") or {}).get("window_complete")
        and (f.get("coverage") or {}).get("comparable")
        for f in files
        if f["status"] == "INCLUDED"
    )
    config["comparable_complete_windows"] = bool(
        config.get("comparable_complete_windows") and coverage_ok
    )
    ranks, strategies, timeline = aggregate(analyzed, config)
    topics = discover_topics(analyzed, config.get("topics", {}))
    quality["collection_coverage"] = {
        "reported_total_sum": sum(
            (f.get("total_reported") or 0) for f in files if f["status"] == "INCLUDED"
        ),
        "expected_replies_from_main_sum": sum(
            (f.get("coverage") or {}).get("expected_replies_from_main", 0)
            for f in files
            if f["status"] == "INCLUDED"
        ),
        "observed_reply_rows": quality["reply_rows"],
        "complete_comment_section": False,
        "reason": "Reported totals and absent replies cannot establish complete coverage",
    }
    quality.update(
        status_counts=dict(Counter(r["status"] for r in analyzed)),
        calls=extractor.calls,
        tokens=extractor.tokens,
        cache_hits=extractor.cache_hits,
        price_estimate=None,
        acceptance="PENDING_HUMAN_ANNOTATION",
        automatic_coverage=sum(r["status"] == "SUCCESS" for r in analyzed)
        / max(1, len(valid)),
        trend_coverage_verified=coverage_ok,
    )
    old = ROOT / "output" / "batch_analyzed_comments.json"
    if old.exists():
        baseline = json.loads(old.read_text())
        quality["baseline_comparison"] = {
            "old_analyzed": len(baseline),
            "new_valid_short_records": sum(
                len(r["cleaned_comment"]) < 4 for r in valid
            ),
            "new_valid_text_collapsed": len({r["cleaned_comment"] for r in valid}),
            "new_valid_repeated_text_identities": len(valid)
            - len({r["cleaned_comment"] for r in valid}),
            "new_identity_records": len(records),
            "new_valid_records": len(valid),
            "delta_valid": len(valid) - len(baseline),
            "explanation": "Identity dedup retains distinct cids; idless samples matched to detailed records; short text retained; semantic success measured separately.",
        }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "files": files,
        "config": config,
        "model": extractor.model,
        "dictionary_sha256": digest(resolver.dictionary),
        "run_status": "COMPLETE"
        if all(r["status"] == "SUCCESS" for r in analyzed if r["valid"])
        and all(f["status"] != "ERROR" for f in files)
        and quality["invalid_rows"] == 0
        and bool(analyzed)
        and topics["status"] in ("SUCCESS", "INSUFFICIENT_DATA", "DISABLED")
        else "PARTIAL",
        "pilot": not args.full,
        "selected": len(selected),
        "comments_sha256": digest(records),
        "environment": {
            "python": sys.version,
            "packages": {
                d.metadata["Name"]: d.version
                for d in importlib.metadata.distributions()
            },
        },
    }
    for filename, data in [
        ("manifest", manifest),
        ("analyzed_comments", analyzed),
        ("ticker_consensus", ranks),
        ("strategy_ranking", strategies),
        ("topics", topics),
        ("timeline", timeline),
        ("quality", quality),
        ("review_queue", [r for r in analyzed if r["status"] == "NEEDS_REVIEW"]),
        ("failures", [r for r in analyzed if r["status"] in ("FAILED", "SKIPPED")]),
    ]:
        write_json(output / (filename + ".json"), data)
    write_csv(output / "ticker_consensus.csv", ranks)
    write_csv(output / "strategy_ranking.csv", strategies["ranking"])
    write_csv(output / "analyzed_comments.csv", analyzed)
    topic_audit = [
        {
            "topic_id": t["topic_id"],
            "comment_key": k,
            "relevant": None,
            "annotator": None,
        }
        for t in topics["topics"][:10]
        for k in sorted(t["comment_keys"], key=digest)[:10]
    ]
    write_json(output / "topic_annotations.json", topic_audit)
    make_report(output, analyzed, ranks, strategies, topics, quality, manifest)
    print(
        json.dumps(
            {
                "output": str(output),
                "run_status": manifest["run_status"],
                "quality": quality,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return output


if __name__ == "__main__":
    asyncio.run(run(arguments()))
