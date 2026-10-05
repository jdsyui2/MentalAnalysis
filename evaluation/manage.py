"""Prepare human annotation sets and evaluate manually completed gold labels."""

import argparse
import json
import random
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from core.ingestion import ingest, digest
from core.report import write_json
from core.schema import Analysis


def near_key(text):
    return re.sub(r"\W", "", text.casefold())


def prepare(inputs, out):
    existing = out / "annotations.json"
    if existing.exists() and any(
        x.get("annotation_status") == "COMPLETE"
        for x in json.loads(existing.read_text())
    ):
        raise ValueError(
            "Refusing to overwrite completed human annotations; choose a new output directory"
        )
    records, _, _, _ = ingest(inputs)
    rng = random.Random(42)
    groups = []
    # Conservative near-duplicate grouping; whole group belongs to one split.
    for r in sorted((r for r in records if r["valid"]), key=lambda r: r["comment_key"]):
        norm = near_key(r["cleaned_comment"])
        for g in groups:
            if norm == g["norm"] or (
                abs(len(norm) - len(g["norm"])) <= max(2, 0.15 * len(norm))
                and SequenceMatcher(None, norm, g["norm"], autojunk=False).ratio()
                >= 0.9
            ):
                g["rows"].append(r)
                break
        else:
            groups.append({"norm": norm, "rows": [r]})
    by_video = defaultdict(list)
    for g in groups:
        by_video[g["rows"][0]["aweme_id"]].append(g)
    for bucket in by_video.values():
        rng.shuffle(bucket)
    random_groups = []
    while len(random_groups) < 200 and any(by_video.values()):
        for video in sorted(by_video, key=str):
            if by_video[video] and len(random_groups) < 200:
                random_groups.append(by_video[video].pop())
    used = {id(g) for g in random_groups}
    remaining = [g for g in groups if id(g) not in used]
    triggers = ("不", "？", "?", "如果", "但是", "杠杆", "去年", "买", "卖", "定投")
    remaining.sort(
        key=lambda g: (
            -sum(t in g["rows"][0]["raw_comment"] for t in triggers),
            -len(g["rows"][0]["raw_comment"]),
            g["norm"],
        )
    )
    selected = [(g, "STRATIFIED_RANDOM") for g in random_groups] + [
        (g, "COMPLEX") for g in remaining[:100]
    ]
    rng.shuffle(selected)
    labels = []
    for i, (g, stratum) in enumerate(selected):
        r = g["rows"][0]
        labels.append(
            {
                "id": r["comment_key"],
                "split": "dev" if i < 100 else "test",
                "stratum": stratum,
                "duplicate_group": digest(g["norm"]),
                "group_comment_keys": [x["comment_key"] for x in g["rows"]],
                "raw_comment": r["raw_comment"],
                "sources": r["sources"],
                "annotation_status": "PENDING",
                "annotator": None,
                "gold": None,
            }
        )
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "annotations.json", labels)
    write_json(
        out / "annotation_manifest.json",
        {
            "selected": len(labels),
            "dev": min(100, len(labels)),
            "test": max(0, len(labels) - 100),
            "status": "PENDING_HUMAN_ANNOTATION",
            "seed": 42,
            "near_duplicate_similarity": 0.9,
            "schema": Analysis.model_json_schema(),
        },
    )
    return {"selected": len(labels), "status": "PENDING_HUMAN_ANNOTATION"}


def score_sets(pairs):
    labels = sorted(set().union(*(g | p for g, p in pairs))) if pairs else []
    stats = {}
    for label in labels:
        tp = sum(label in g and label in p for g, p in pairs)
        fp = sum(label not in g and label in p for g, p in pairs)
        fn = sum(label in g and label not in p for g, p in pairs)
        stats[label] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "support": tp + fn,
            "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0,
        }
    tp = sum(s["tp"] for s in stats.values())
    fp = sum(s["fp"] for s in stats.values())
    fn = sum(s["fn"] for s in stats.values())
    return {
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "macro_f1": sum(s["f1"] for s in stats.values()) / len(stats)
        if stats
        else None,
        "micro_f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        "labels": stats,
    }


def evaluate(annotation_path, prediction_path):
    annotations = json.loads(annotation_path.read_text())
    predictions = {r["comment_key"]: r for r in json.loads(prediction_path.read_text())}
    test = [x for x in annotations if x["split"] == "test"]
    complete = [
        x
        for x in test
        if x["annotation_status"] == "COMPLETE"
        and x["annotator"]
        and x["gold"] is not None
    ]
    if len(complete) != len(test) or not test:
        return {
            "status": "PENDING_HUMAN_ANNOTATION",
            "test_samples": len(test),
            "completed": len(complete),
        }
    metrics = {k: [] for k in ["entities", "intents", "actions", "methods"]}
    supported = 0
    reasons = 0
    success = 0
    unknown = 0
    predicted_view_count = 0
    for x in complete:
        g = (
            Analysis.model_validate(x["gold"])
            .validate_evidence(x["raw_comment"])
            .model_dump()
        )
        row = predictions.get(x["id"], {})
        p = row.get("analysis") if row.get("status") == "SUCCESS" else None
        success += p is not None
        p = p or {"views": [], "intents": [], "methods": []}
        for k in ["entities", "intents", "actions", "methods"]:

            def labels(a):
                if k == "entities":
                    return {(v["category"], v["entity"].casefold()) for v in a["views"]}
                if k == "actions":
                    return {
                        (v["category"], v["entity"].casefold(), v["action"])
                        for v in a["views"]
                    }
                if k == "intents":
                    return set(a["intents"])
                return {m["method"] for m in a["methods"]}

            metrics[k].append((labels(g), labels(p)))
        predicted_view_count += len(p["views"])
        unknown += sum(
            v["stance"] == "UNKNOWN" or v["action"] == "UNKNOWN" for v in p["views"]
        )
        gold_reasons = {
            (v["entity"].casefold(), rr["quote"], rr["category"])
            for v in g["views"]
            for rr in v["rationales"]
        }
        for v in p["views"]:
            for rr in v["rationales"]:
                reasons += 1
                supported += (
                    v["entity"].casefold(),
                    rr["quote"],
                    rr["category"],
                ) in gold_reasons
    result = {k: score_sets(v) for k, v in metrics.items()}
    result.update(
        status="EVALUATED",
        test_samples=len(test),
        automatic_coverage=success / len(test),
        unknown_views=unknown,
        unknown_rate=unknown / max(1, predicted_view_count),
        rationale_support_rate=supported / reasons if reasons else None,
    )
    # tuple keys in label metrics must serialize deterministically.
    for k in metrics:
        result[k]["labels"] = {
            str(label): value for label, value in result[k]["labels"].items()
        }
    checks = {
        "entity_precision": (result["entities"]["precision"] or 0) >= 0.95,
        "entity_recall": (result["entities"]["recall"] or 0) >= 0.85,
        "intent_macro_f1": (result["intents"]["macro_f1"] or 0) >= 0.85,
        "action_macro_f1": (result["actions"]["macro_f1"] or 0) >= 0.85,
        "method_micro_f1": (result["methods"]["micro_f1"] or 0) >= 0.85,
        "rationale_support": (result["rationale_support_rate"] or 0) >= 0.95,
    }
    result["gates"] = checks
    result["acceptance"] = "PASS" if all(checks.values()) else "EXPERIMENTAL"
    return result


def evaluate_topics(path):
    rows = json.loads(path.read_text())
    groups = defaultdict(list)
    for row in rows:
        groups[row["topic_id"]].append(row)
    result = []
    for topic, items in groups.items():
        complete = all(
            isinstance(r.get("relevant"), bool) and r.get("annotator") for r in items
        )
        rate = sum(r["relevant"] for r in items) / len(items) if complete else None
        result.append(
            {
                "topic_id": topic,
                "samples": len(items),
                "relevance_rate": rate,
                "acceptance": "CONFIRMED"
                if rate is not None and rate >= 0.8
                else "CANDIDATE",
            }
        )
    return {
        "status": "EVALUATED"
        if result and all(x["relevance_rate"] is not None for x in result)
        else "PENDING_HUMAN_ANNOTATION",
        "topics": result,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--input", nargs="+", type=Path, required=True)
    s.add_argument("--output", type=Path, default=Path("evaluation/dataset"))
    s = sub.add_parser("evaluate")
    s.add_argument("--annotations", type=Path, required=True)
    s.add_argument("--predictions", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s = sub.add_parser("evaluate-topics")
    s.add_argument("--annotations", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.command == "prepare":
        print(prepare(a.input, a.output))
    elif a.command == "evaluate-topics":
        write_json(a.output, evaluate_topics(a.annotations))
        print(a.output)
    else:
        write_json(a.output, evaluate(a.annotations, a.predictions))
        print(a.output)
