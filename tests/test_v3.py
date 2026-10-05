import copy
import json
import pytest
from core.schema import Analysis
from core.validation import validate_fields, finalize_row
from core.aggregator import aggregate
from core.entities import EntityResolver
from core.extractor import SemanticExtractor
from core.ingestion import ingest
from core.context import load_context
from core.duplicates import assign_duplicate_groups
from core.report import write_json, make_report
from core.publishing import publish_redacted
from build_conclusions import build


def ev(text, quote=None, source="COMMENT"):
    quote = quote or text
    p = text.index(quote)
    return {"quote": quote, "start": p, "end": p + len(quote), "source": source}


def sample(
    text, entity="黄金", speech="RECOMMENDATION", stance="BULLISH", action="BUY"
):
    return {
        "intents": ["RECOMMENDATION"],
        "views": [
            {
                "entity": entity,
                "category": "ASSET",
                "speech_act": speech,
                "intent_basis": "EXPLICIT_COMMENT",
                "explicit_action": action not in ("NONE", "UNKNOWN"),
                "evidence": ev(text, entity),
                "stance": stance,
                "stance_evidence": ev(text),
                "action": action,
                "action_evidence": ev(text)
                if action not in ("NONE", "UNKNOWN")
                else None,
            }
        ],
        "methods": [],
        "risks": [],
        "confidence_self_reported": 0.7,
    }


def row(text, data=None, key="1", video="v"):
    r = {
        "comment_key": key,
        "valid": True,
        "raw_comment": text,
        "cleaned_comment": text,
        "aweme_id": video,
        "create_time": None,
        "user_id": None,
        "cid": key,
        "digg_count": None,
        "conflicts": [],
        "sources": [],
        "video_url": None,
    }
    if data is not None:
        r["analysis"], _ = validate_fields(Analysis.model_validate(data), r)
        for v in r["analysis"]["views"]:
            v["resolved_entity"] = EntityResolver("configs/entities.json").resolve(v)
            if v["resolved_entity"]["resolution"] == "UNRESOLVED":
                v["field_status"]["entity"] = "REVIEW"
                r["analysis"]["review_items"].append({"field": "entity"})
        finalize_row(r)
    return r


def test_mixed_view_survives():
    text = "买黄金，也看未知公司"
    d = sample(text)
    d["views"].append(
        dict(
            d["views"][0],
            entity="未知公司",
            category="STOCK",
            evidence=ev(text, "未知公司"),
        )
    )
    d["methods"] = [
        {"method": "CASH_WAIT", "attitude": "MENTION", "evidence": ev(text)}
    ]
    r = row(text, d)
    assert r["status"] == "PARTIAL"
    ranks, methods, _ = aggregate([r], {})
    assert len(ranks) == 1 and ranks[0]["entity"]["name"] == "黄金"
    assert methods["ranking"][0]["count"] == 1


def test_invalid_action_retains_entity():
    d = sample("不买黄金")
    r = row("不买黄金", d)
    ranks, _, _ = aggregate([r], {})
    assert ranks[0]["mentions"] == 1 and ranks[0]["actions"] == {"UNKNOWN": 1}


def test_self_position_not_recommendation():
    r = row("我买黄金", sample("我买黄金", speech="SELF_POSITION"))
    ranks, _, _ = aggregate([r], {})
    assert (
        ranks[0]["recommendation_count"] == 0
        and ranks[0]["self_position_buy_count"] == 1
    )


def test_verified_context_without_buy():
    text = "黄金"
    d = sample(text, action="NONE", stance="UNKNOWN")
    d["views"][0].update(
        intent_basis="VIDEO_PROMPT_CONTEXT",
        context_evidence=ev("值得投资什么？", source="VIDEO"),
    )
    r = row(text)
    r["context"] = {"video_text": "值得投资什么？", "solicitation_verified": True}
    a, _ = validate_fields(Analysis.model_validate(d), r)
    assert (
        a["views"][0]["field_status"]["speech_act"] == "PASS"
        and a["views"][0]["action"] == "NONE"
    )
    r["context"]["solicitation_verified"] = False
    a, _ = validate_fields(Analysis.model_validate(d), r)
    assert a["views"][0]["field_status"]["speech_act"] == "REVIEW"


def test_false_action_context_is_blocked():
    d = sample("黄金")
    d["views"][0]["intent_basis"] = "VIDEO_PROMPT_CONTEXT"
    a, _ = validate_fields(Analysis.model_validate(d), {"raw_comment": "黄金"})
    assert a["views"][0]["field_status"]["action"] == "FAIL"


@pytest.mark.parametrize(
    "text,attitude",
    [("别做T", "OPPOSE"), ("我一直在做T", "SELF_PRACTICE"), ("建议做T", "SUPPORT")],
)
def test_method_attitudes(text, attitude):
    d = {
        "intents": ["MENTION"],
        "views": [],
        "methods": [{"method": "SWING_T", "attitude": attitude, "evidence": ev(text)}],
        "risks": [],
        "confidence_self_reported": 0.8,
    }
    r = row(text, d)
    _, m, _ = aggregate([r], {})
    assert m["ranking"][0]["attitudes"] == {attitude: 1}


def test_method_contradiction_not_support():
    d = {
        "intents": ["MENTION"],
        "views": [],
        "methods": [
            {"method": "SWING_T", "attitude": "SUPPORT", "evidence": ev("别做T")}
        ],
        "risks": [],
        "confidence_self_reported": 0.8,
    }
    _, m, _ = aggregate([row("别做T", d)], {})
    assert m["ranking"][0]["attitudes"] == {"UNKNOWN": 1}


def test_identity_corroboration(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "comments": [
                    {
                        "cid": "1",
                        "comment": "纳指",
                        "aweme_id": "v",
                        "nickname": "A",
                        "create_time": 5,
                    },
                    {
                        "comment": "纳指",
                        "aweme_id": "v",
                        "nickname": "A",
                        "create_time": 5,
                    },
                    {
                        "comment": "纳指",
                        "aweme_id": "v",
                        "nickname": "B",
                        "create_time": 5,
                    },
                ]
            }
        )
    )
    rows, _, q, _ = ingest([p])
    assert len(rows) == 2 and q["idless_matched"] == 1


def test_cache_hashes(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAL_MODEL", "test")
    r = {"raw_comment": "黄金", "context": {"video_text": "a"}}
    ex = SemanticExtractor({}, tmp_path)
    old = ex.cache_key(r)
    assert ex.cache_key(dict(r, context={"video_text": "b"})) != old
    assert (
        SemanticExtractor({"thinking": {"type": "enabled"}}, tmp_path).cache_key(r)
        != old
    )
    import core.extractor as module

    monkeypatch.setattr(module, "SYSTEM", module.SYSTEM + "change")
    assert ex.cache_key(r) != old


def test_identity_conflict_blocks_all():
    r = row("买黄金", sample("买黄金"))
    r["conflicts"] = [{}]
    finalize_row(r)
    ranks, methods, _ = aggregate([r], {})
    assert ranks == [] and methods["ranking"] == []


def test_balanced_video_zero_and_likes():
    r = row("买黄金", sample("买黄金"))
    r["digg_count"] = 10
    blank = row(
        "你好",
        {
            "intents": ["NON_INVESTMENT"],
            "views": [],
            "methods": [],
            "risks": [],
            "confidence_self_reported": 0.8,
        },
        key="2",
        video="v2",
    )
    assign_duplicate_groups([r, blank])
    ranks, _, _ = aggregate([r, blank], {})
    assert ranks[0]["video_balanced_score"] == 0.5 and ranks[0]["video_total"] == 2
    assert ranks[0]["engagement_observed_comments"] == 1


def test_near_duplicate_determinism():
    rows = [row("相信国运，定投纳指", key="1"), row("相信国运定投纳指", key="2")]
    g = assign_duplicate_groups(rows)
    assert len(g) == 1
    reverse = copy.deepcopy(rows[::-1])
    assert assign_duplicate_groups(reverse) == g


def create_run(path, rows):
    path.mkdir(exist_ok=True)
    ranks, methods, timeline = aggregate(rows, {})
    manifest = {
        "pilot": False,
        "model": "mock",
        "schema_version": "3.0",
        "prompt_version": "3.0",
        "generated_at": "2026-10-05",
        "run_status": "COMPLETE",
        "catalog_coverage": {},
        "catalog_gaps": [],
        "files": [],
    }
    q = {"reply_rows": 0, "status_counts": {}, "valid_records": len(rows)}
    topics = {"status": "INSUFFICIENT_DATA", "spaces": {}, "topics": []}
    for name, data in [
        ("manifest", manifest),
        ("quality", q),
        ("ticker_consensus", ranks),
        ("strategy_ranking", methods),
        ("topics", topics),
        ("analyzed_comments", rows),
    ]:
        write_json(path / (name + ".json"), data)
    make_report(path, rows, ranks, methods, topics, q, manifest)
    build(path)
    return path


def test_empty_conclusions_public(tmp_path):
    run = create_run(tmp_path / "run", [])
    s = json.loads((run / "conclusions.json").read_text())
    assert s["video_count"] == 0 and s["valid_comments"] == 0
    assert (
        "黄金" not in (run / "conclusions.md").read_text()
        and "纳指" not in (run / "conclusions.md").read_text()
    )
    publish_redacted(run, tmp_path / "public")


def test_public_allowlist(tmp_path):
    r = row("我买黄金", sample("我买黄金", speech="SELF_POSITION"))
    r.update(
        nickname="PRIVATE_NICK",
        sources=[{"file": "/Users/secret/file", "data": "PRIVATE_META"}],
    )
    run = create_run(tmp_path / "run", [r])
    publish_redacted(run, tmp_path / "public")
    output = "".join(
        p.read_text(encoding="utf-8-sig") for p in (tmp_path / "public").iterdir()
    )
    for secret in [
        "我买黄金",
        "PRIVATE_NICK",
        "PRIVATE_META",
        "/Users/secret",
        "comment_key",
        "representative_comments",
        'sources"',
        'cid"',
    ]:
        assert secret not in output


def test_topic_space_failure_isolated(monkeypatch):
    from core.topics import discover_topics

    monkeypatch.setattr("core.topics.documents", lambda r, space: {"text": ["1"]})
    # Tiny inputs never force model import/download.
    t = discover_topics([], {})
    assert t["status"] == "INSUFFICIENT_DATA" and len(t["spaces"]) == 4


def test_context_requires_source(tmp_path):
    p = tmp_path / "ctx.json"
    p.write_text(json.dumps({"videos": {"v": {"solicitation_verified": True}}}))
    with pytest.raises(ValueError):
        load_context(p)


def test_question_no_recommendation():
    r = row(
        "黄金还会跌吗",
        sample("黄金还会跌吗", speech="QUESTION", action="NONE", stance="UNKNOWN"),
    )
    ranks, _, _ = aggregate([r], {})
    assert ranks[0]["recommendation_count"] == 0 and ranks[0]["directional_count"] == 0


def test_catalog_company_ordinary_phrase_not_added():
    resolver = EntityResolver("configs/entity_catalog.json")
    assert any(c["name"] == "我爱我家" for c in resolver.candidates("我爱我家"))
    # Candidates alone never produce an extracted view.
    d = {
        "intents": ["NON_INVESTMENT"],
        "views": [],
        "methods": [],
        "risks": [],
        "confidence_self_reported": 0.7,
    }
    ranks, _, _ = aggregate([row("我爱我家", d)], {})
    assert not ranks


def test_same_entity_question_and_position_are_not_lost():
    text = "黄金还会跌吗，我已买黄金"
    d = sample(text, speech="QUESTION", action="NONE", stance="UNKNOWN")
    holding = copy.deepcopy(d["views"][0])
    holding.update(
        speech_act="SELF_POSITION",
        explicit_action=True,
        action="BUY",
        action_evidence=ev(text, "我已买黄金"),
    )
    d["views"].append(holding)
    ranks, _, _ = aggregate([row(text, d)], {})
    assert (
        ranks[0]["mentions"] == 1
        and ranks[0]["self_position_count"] == 1
        and ranks[0]["recommendation_count"] == 0
    )


def test_avoid_speech_is_not_positive_recommendation():
    d = sample("不买黄金", stance="UNKNOWN", action="AVOID")
    ranks, _, _ = aggregate([row("不买黄金", d)], {})
    assert ranks[0]["recommendation_count"] == 0 and ranks[0]["avoid_count"] == 1


def test_gold_metrics_report_resolution_and_attitude(tmp_path):
    from evaluation.manage import evaluate

    text = "买黄金"
    d = sample(text)
    r = row(text, d)
    d["methods"] = [{"method": "CASH_WAIT", "attitude": "OPPOSE", "evidence": ev(text)}]
    r = row(text, d)
    annotations = [
        {
            "id": "1",
            "split": "test",
            "annotation_status": "COMPLETE",
            "annotator": "human",
            "raw_comment": text,
            "gold": d,
            "canonical_ids": {
                "0": r["analysis"]["views"][0]["resolved_entity"]["entity_id"]
            },
        }
    ]
    a = tmp_path / "a.json"
    p = tmp_path / "p.json"
    a.write_text(json.dumps(annotations))
    p.write_text(json.dumps([r]))
    result = evaluate(a, p)
    assert (
        result["entity_spans"]["precision"] == 1
        and result["canonical_ids"]["precision"] == 1
    )
    assert (
        result["method_attitudes"]["micro_f1"] == 1
        and result["stances"]["micro_f1"] == 1
    )

    r["status"] = "PARTIAL"
    r["analysis"]["views"][0]["field_status"]["entity"] = "REVIEW"
    p.write_text(json.dumps([r]))
    result = evaluate(a, p)
    assert result["entity_spans"]["recall"] == 1
    assert result["canonical_id_accuracy"] == 0
    assert result["canonical_id_matched_spans"] == 1


def test_retry_and_resume_v3_partial_no_repeat_api(tmp_path, monkeypatch):
    import asyncio
    import httpx

    monkeypatch.setenv("MENTAL_API_KEY", "mock")
    monkeypatch.setenv("MENTAL_MODEL", "mock")
    count = []

    def respond(request):
        count.append(request)
        content = "invalid" if len(count) == 1 else json.dumps(sample("买黄金"))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"total_tokens": 10},
            },
        )

    async def check():
        r = {"raw_comment": "买黄金"}
        ex = SemanticExtractor(
            {"max_attempts": 2}, tmp_path, httpx.MockTransport(respond)
        )
        assert (await ex.analyze(r))["status"] == "SUCCESS"
        other = SemanticExtractor(
            {"max_attempts": 2}, tmp_path, httpx.MockTransport(respond)
        )
        assert (await other.analyze(r))["status"] == "SUCCESS" and other.calls == 0

    asyncio.run(check())
    assert len(count) == 2


def test_sarcasm_unknown_not_promoted_to_recommendation():
    text = "相信国运，定投纳指"
    d = sample(text, entity="纳指", speech="UNKNOWN", stance="UNKNOWN", action="NONE")
    d["needs_review"] = True
    d["review_reason"] = "反讽无法确定"
    ranks, _, _ = aggregate([row(text, d)], {})
    assert ranks[0]["recommendation_count"] == 0 and ranks[0]["directional_count"] == 0


def test_csv_preserves_numeric_values_but_blocks_string_formula():
    from core.report import csv_value

    assert csv_value(-1.2) == "-1.2" and csv_value("-1+CMD").startswith("'")


def test_insight_references_only_matching_speech_act():
    from build_conclusions import insights

    holdings = row("我买黄金", sample("我买黄金", speech="SELF_POSITION"), key="a")
    recommendation = row("建议买黄金", sample("建议买黄金"), key="b")
    ranks, methods, _ = aggregate([holdings, recommendation], {})
    facts = insights(ranks, methods)
    assert facts[0]["kind"] == "RECOMMENDED" and facts[0]["evidence_keys"] == ["b"]
