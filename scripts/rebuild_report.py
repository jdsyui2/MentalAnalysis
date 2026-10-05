"""Refresh aggregation and reporting from a v3 run without any model calls."""

import argparse
import json
from pathlib import Path
from core.aggregator import aggregate
from core.report import write_json, write_csv, make_report
from core.publishing import publish_redacted
from build_conclusions import build
from core.ingestion import digest


def rebuild(run, public=None):
    run = Path(run)
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["schema_version"] != "3.0":
        raise ValueError("Requires schema 3.0")
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
    write_csv(run / "ticker_consensus.csv", ranks)
    write_csv(run / "strategy_ranking.csv", methods["ranking"])
    manifest["report_code_hashes"] = {
        p.name: digest(p.read_text())
        for p in [
            Path("core/aggregator.py"),
            Path("core/report.py"),
            Path("build_conclusions.py"),
            Path("core/publishing.py"),
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
    a = p.parse_args()
    print(rebuild(a.run, a.public))
