"""Refresh aggregation and reporting from a v3 run without any model calls."""

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from core.aggregator import aggregate
from core.report import write_json, write_csv, make_report
from core.publishing import publish_redacted
from build_conclusions import build
from core.ingestion import digest
from core.presentation import REPORT_VERSION, MATURITY, group_ranks


def rebuild(run, public=None, revision_output=None):
    run = Path(run)
    source_id = run.name
    if revision_output:
        destination = Path(revision_output)
        if destination.exists():
            raise ValueError(
                "Revision output already exists; source runs must be preserved"
            )
        shutil.copytree(run, destination)
        run = destination
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["schema_version"] != "3.0":
        raise ValueError("Requires schema 3.0")
    if revision_output:
        manifest.update(
            source_run_id=source_id,
            report_revision_id=run.name,
            report_generated_at=datetime.now(timezone.utc).isoformat(),
            report_version=REPORT_VERSION,
            report_revision_api_calls=0,
            report_revision_tokens=0,
            **MATURITY,
        )
    rows = json.loads((run / "analyzed_comments.json").read_text())
    quality = json.loads((run / "quality.json").read_text())
    topics = json.loads((run / "topics.json").read_text())
    ranks, methods, timeline = aggregate(rows, manifest["config"])
    for name, data in [
        ("ticker_consensus", ranks),
        ("strategy_ranking", methods),
        ("timeline", timeline),
    ]:
        write_json(run / (name + ".json"), data)
    boards = group_ranks(ranks)
    boards["methods"] = methods
    write_json(run / "boards.json", boards)
    write_csv(run / "ticker_consensus.csv", ranks)
    write_csv(run / "strategy_ranking.csv", methods["ranking"])
    manifest["report_code_hashes"] = {
        p.name: digest(p.read_text())
        for p in [
            Path("core/aggregator.py"),
            Path("core/report.py"),
            Path("build_conclusions.py"),
            Path("core/publishing.py"),
            Path("core/presentation.py"),
            Path("configs/report_taxonomy.json"),
            Path("scripts/rebuild_report.py"),
        ]
    }
    write_json(run / "manifest.json", manifest)
    make_report(run, rows, ranks, methods, topics, quality, manifest)
    if not manifest["pilot"]:
        build(run)
        if public:
            publish_redacted(run, public)
    return run


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run", type=Path)
    p.add_argument("--public", type=Path)
    p.add_argument("--revision-output", type=Path)
    a = p.parse_args()
    print(rebuild(a.run, a.public, a.revision_output))
