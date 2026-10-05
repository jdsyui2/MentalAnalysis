"""Prepare human annotation sets and evaluate manually completed gold labels."""

import argparse
import json
import random
import re
from collections import Counter, defaultdict
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
    from core.context import attach_context, load_context
    from core.duplicates import assign_duplicate_groups
    from core.entities import EntityResolver

    root = Path(__file__).resolve().parent.parent
    attach_context(records, load_context(root / "configs/video_context.json"))
    resolver = EntityResolver(root / "configs/entity_catalog.json")
    for r in records:
        r["entity_candidates"] = resolver.candidates(r["raw_comment"])
    assign_duplicate_groups(records)
    rng = random.Random(42)
    grouped = defaultdict(list)
    for r in records:
        if r["valid"]:
            grouped[r["duplicate_group"]].append(r)
    groups = [
        {
            "norm": g[0]["duplicate_group"],
            "rows": sorted(g, key=lambda r: r["comment_key"]),
        }
        for g in grouped.values()
    ]
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
    challenge = []
    chosen = set()
    predicates = [
        lambda r: bool(re.search(r"推荐|值得|可以买|定投|买入", r["raw_comment"])),
        lambda r: len(r["raw_comment"]) <= 12 and bool(r["entity_candidates"]),
        lambda r: bool(re.search(r"不|别|国运|呵呵|难道|[？?]", r["raw_comment"])),
        lambda r: (
            len(r["entity_candidates"]) >= 2
            or bool(re.search(r"买.*卖|买.*避|持.*不", r["raw_comment"]))
        ),
    ]
    for predicate in predicates:
        bucket = [
            g for g in remaining if id(g) not in chosen and predicate(g["rows"][0])
        ]
        rng.shuffle(bucket)
        for g in bucket[:50]:
            challenge.append(g)
            chosen.add(id(g))
    for g in remaining:
        if len(challenge) >= 200:
            break
        if id(g) not in chosen:
            challenge.append(g)
            chosen.add(id(g))
    selected = [(g, "STRATIFIED_RANDOM") for g in random_groups] + [
        (g, "CHALLENGE") for g in challenge
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
                "context": r["context"],
                "entity_candidates": r["entity_candidates"],
                "challenge_tags": [
                    tag
                    for tag, pattern in {
                        "SHORT_ENTITY": r"^.{1,8}$",
                        "NEGATION_SARCASM": r"不|别|国运|呵呵",
                        "MULTI_ACTION": r"买.*卖|买.*避|持.*不",
                        "RECOMMENDATION": r"推荐|值得|可以买|定投",
                    }.items()
                    if re.search(pattern, r["raw_comment"])
                ],
                "canonical_ids": {},
                "second_annotation": {
                    "annotator": None,
                    "gold": None,
                    "canonical_ids": {},
                }
                if i < 50
                else None,
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
            "double_annotation_samples": min(50, len(labels)),
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
    from core.validation import usable, passed

    metric_names = [
        "entities",
        "entity_spans",
        "canonical_ids",
        "intents",
        "speech_acts",
        "stances",
        "actions",
        "methods",
        "method_attitudes",
        "rationales",
    ]
    metrics = {k: [] for k in metric_names}
    unknown = predicted_views = processed = 0
    matched_spans = correct_canonical = 0

    def labels(a, kind, canonical, prediction=False, raw=""):
        def grounded(v):
            e = v.get("evidence", {})
            start, end = e.get("start"), e.get("end")
            return (
                e.get("source", "COMMENT") == "COMMENT"
                and isinstance(start, int)
                and isinstance(end, int)
                and 0 <= start < end <= len(raw)
                and raw[start:end] == e.get("quote")
            )

        views = a.get("views", [])

        def allowed(v, field):
            return not prediction or passed(v, field)

        if kind == "entities":
            return {
                (v["category"], v["entity"].casefold())
                for v in views
                if allowed(v, "entity")
            }
        if kind == "entity_spans":
            return {
                (
                    v["category"],
                    v["evidence"].get("source", "COMMENT"),
                    v["evidence"]["start"],
                    v["evidence"]["end"],
                )
                for v in views
                if grounded(v)
            }
        if kind == "canonical_ids":
            return {
                (
                    v["evidence"]["start"],
                    v["evidence"]["end"],
                    v.get("resolved_entity", {}).get("entity_id")
                    if prediction
                    else canonical.get(str(i)),
                )
                for i, v in enumerate(views)
                if allowed(v, "entity")
            }
        if kind == "intents":
            return (
                set(a.get("intents", []))
                if not prediction or a.get("field_status", {}).get("intent") == "PASS"
                else set()
            )
        if kind in ("speech_acts", "stances", "actions"):
            field = {
                "speech_acts": "speech_act",
                "stances": "stance",
                "actions": "action",
            }[kind]
            return {
                (v["evidence"]["start"], v["evidence"]["end"], v[field])
                for v in views
                if allowed(v, field)
            }
        if kind == "methods":
            return {m["method"] for m in a.get("methods", []) if allowed(m, "type")}
        if kind == "method_attitudes":
            return {
                (m["method"], m["attitude"])
                for m in a.get("methods", [])
                if allowed(m, "type") and allowed(m, "attitude")
            }
        return {
            (v["evidence"]["start"], rr["quote"], rr.get("reason_code", "OTHER"))
            for v in views
            for rr in v.get("rationales", [])
            if not prediction or rr.get("field_status") == "PASS"
        }

    for x in complete:
        gold_model = Analysis.model_validate(x["gold"])
        from core.validation import validate_fields

        g, repairs = validate_fields(
            gold_model,
            {"raw_comment": x["raw_comment"], "context": x.get("context", {})},
        )
        if repairs or any(
            i.get("reason", "").endswith("FAIL") for i in g["review_items"]
        ):
            raise ValueError(
                "Human gold contains invalid evidence or a deterministic contradiction"
            )
        if any(
            str(i) not in x.get("canonical_ids", {}) for i, v in enumerate(g["views"])
        ):
            return {
                "status": "PENDING_CANONICAL_ANNOTATION",
                "test_samples": len(test),
                "completed": len(complete),
            }
        row = predictions.get(x["id"], {})
        p = row.get("analysis") if usable(row) else {}
        p = p or {}
        processed += bool(p)
        predicted_views += len(p.get("views", []))
        unknown += sum(
            v["stance"] == "UNKNOWN" or v["action"] == "UNKNOWN"
            for v in p.get("views", [])
        )
        gold_ids = {
            (v["evidence"]["start"], v["evidence"]["end"]): x["canonical_ids"][str(i)]
            for i, v in enumerate(g["views"])
        }
        for v in p.get("views", []):
            span = (v["evidence"]["start"], v["evidence"]["end"])
            if span in gold_ids and labels(
                {"views": [v]}, "entity_spans", {}, True, x["raw_comment"]
            ):
                matched_spans += 1
                correct_canonical += bool(
                    passed(v, "entity")
                    and v.get("resolved_entity", {}).get("entity_id") == gold_ids[span]
                )
        for kind in metric_names:
            metrics[kind].append(
                (
                    labels(g, kind, x.get("canonical_ids", {}), raw=x["raw_comment"]),
                    labels(p, kind, {}, True, x["raw_comment"]),
                )
            )
    result = {k: score_sets(v) for k, v in metrics.items()}
    for k in metrics:
        result[k]["labels"] = {
            str(label): value for label, value in result[k]["labels"].items()
        }
    result.update(
        status="EVALUATED",
        canonical_id_accuracy=correct_canonical / matched_spans
        if matched_spans
        else None,
        canonical_id_matched_spans=matched_spans,
        test_samples=len(test),
        automatic_coverage=processed / len(test),
        unknown_views=unknown,
        unknown_rate=unknown / max(1, predicted_views),
        rationale_support_rate=result["rationales"]["precision"],
        rationale_recall=result["rationales"]["recall"],
        rationale_f1=result["rationales"]["micro_f1"],
    )
    checks = {
        "entity_precision": (result["entity_spans"]["precision"] or 0) >= 0.95,
        "entity_recall": (result["entity_spans"]["recall"] or 0) >= 0.85,
        "canonical_id_accuracy": (result["canonical_id_accuracy"] or 0) >= 0.95,
        "intent_macro_f1": (result["intents"]["macro_f1"] or 0) >= 0.85,
        "action_macro_f1": (result["actions"]["macro_f1"] or 0) >= 0.85,
        "speech_act_macro_f1": (result["speech_acts"]["macro_f1"] or 0) >= 0.85,
        "stance_macro_f1": (result["stances"]["macro_f1"] or 0) >= 0.85,
        "method_micro_f1": (result["methods"]["micro_f1"] or 0) >= 0.85,
        "method_attitude_micro_f1": (result["method_attitudes"]["micro_f1"] or 0)
        >= 0.85,
        "rationale_support": (result["rationale_support_rate"] or 0) >= 0.95,
    }
    result["gates"] = checks
    result["acceptance"] = "PASS" if all(checks.values()) else "EXPERIMENTAL"
    result["double_annotation"] = annotation_agreement(annotations)
    return result


def annotation_agreement(annotations):
    pairs = []
    for x in annotations:
        second = x.get("second_annotation") or {}
        if (
            x.get("gold")
            and x.get("annotator")
            and second.get("gold")
            and second.get("annotator")
        ):
            pairs.append(
                (
                    tuple(sorted(x["gold"]["intents"])),
                    tuple(sorted(second["gold"]["intents"])),
                )
            )
    if not pairs:
        return {
            "status": "PENDING_SECOND_ANNOTATION",
            "samples": 0,
            "cohens_kappa": None,
        }
    left = Counter(a for a, b in pairs)
    right = Counter(b for a, b in pairs)
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    expected = sum(left[k] * right[k] for k in set(left) | set(right)) / n**2
    return {
        "status": "EVALUATED",
        "task": "exact multi-label intent agreement",
        "samples": n,
        "cohens_kappa": (observed - expected) / (1 - expected)
        if expected < 1
        else None,
    }


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
