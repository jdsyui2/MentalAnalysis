import asyncio
import json
from pathlib import Path
import httpx
import pytest
from core.preprocessor import CommentCleaner
from core.ingestion import ingest
from core.schema import Analysis
from core.entities import EntityResolver
from core.extractor import SemanticExtractor
from core.aggregator import aggregate
from core.report import csv_value


def output(text, views=None):
    return {
        "intents": ["MENTION"],
        "views": views or [],
        "methods": [],
        "risks": [],
        "confidence_self_reported": 0.5,
    }


def view(text, name, action="NONE", stance="NEUTRAL", category="STOCK"):
    start = text.index(name)
    ev = {"quote": name, "start": start, "end": start + len(name)}
    return {
        "entity": name,
        "category": category,
        "evidence": ev,
        "action": action,
        "stance": stance,
        "action_evidence": {"quote": text, "start": 0, "end": len(text)}
        if action != "NONE"
        else None,
    }


@pytest.mark.parametrize("text", ["买纳指", "做T", "石油", "QQQ"])
def test_short(text):
    assert CommentCleaner().process({"comment": text})


@pytest.mark.parametrize("text", ["", "[赞][捂脸]", "😀🔥"])
def test_noise(text):
    assert CommentCleaner().process({"comment": text}) is None


def test_identity(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "comments": [
                    {"cid": "1", "comment": "买纳指", "aweme_id": "v"},
                    {"cid": "2", "comment": "买纳指", "aweme_id": "v"},
                    {"comment": "做T", "aweme_id": "v"},
                ]
            }
        )
    )
    q = tmp_path / "b.json"
    q.write_text(
        json.dumps(
            {
                "comments": [
                    {"cid": "1", "comment": "买纳指", "aweme_id": "v"},
                    {"comment": "做T", "aweme_id": "v"},
                ]
            }
        )
    )
    rows, files, quality, _ = ingest([p, q])
    assert len(rows) == 4
    assert quality["merged_observations"] == 1
    assert len(rows[0]["sources"]) == 2


def test_unique_idless(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "comments": [
                    {"cid": "1", "comment": "买纳指", "aweme_id": "v"},
                    {"comment": "买纳指", "aweme_id": "v"},
                ]
            }
        )
    )
    rows, _, quality, _ = ingest([p])
    assert len(rows) == 1
    assert quality["idless_matched"] == 1


def test_evidence():
    a = output("茅台", [view("茅台", "茅台")])
    Analysis.model_validate(a).validate_evidence("茅台")
    a["views"][0]["evidence"]["quote"] = "虚构"
    with pytest.raises(ValueError):
        Analysis.model_validate(a).validate_evidence("茅台")


def test_entity():
    resolver = EntityResolver("configs/entities.json")
    for text, category in [
        ("TQQQ", "ETF"),
        ("黄金", "ASSET"),
        ("纳指", "INDEX"),
        ("银行存款", "ASSET"),
    ]:
        r = resolver.resolve(view(text, text, category=category))
        assert r["ticker"] is None
    assert resolver.resolve(view("TQQQ", "TQQQ", category="ETF"))["name"] == "TQQQ"


def test_api_cache_and_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAL_API_KEY", "test")
    monkeypatch.setenv("MENTAL_MODEL", "test")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps(output("买纳指"))}}],
                "usage": {"total_tokens": 10},
            },
        )

    transport = httpx.MockTransport(respond)
    row = {"raw_comment": "买纳指", "aweme_id": "v"}

    async def check():
        ex = SemanticExtractor({"max_calls": 3}, tmp_path, transport)
        r = await ex.analyze(row)
        assert r["status"] == "SUCCESS"
        ex2 = SemanticExtractor({}, tmp_path, transport)
        assert (await ex2.analyze(row))["status"] == "SUCCESS"
        assert ex2.calls == 0
        ex3 = SemanticExtractor({"max_calls": 0}, tmp_path / "other", transport)
        assert (await ex3.analyze(row))["reason"] == "QUOTA_EXHAUSTED"

    asyncio.run(check())
    assert len(calls) == 1


def test_retry_invalid_json(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAL_API_KEY", "test")
    monkeypatch.setenv("MENTAL_MODEL", "test")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "invalid"}}]}
        )

    async def check():
        ex = SemanticExtractor(
            {"max_attempts": 2}, tmp_path, httpx.MockTransport(respond)
        )
        r = await ex.analyze({"raw_comment": "abc"})
        assert r["status"] == "FAILED"
        assert ex.calls == 2

    asyncio.run(check())


def test_no_configuration(tmp_path, monkeypatch):
    for key in ["MENTAL_API_KEY", "OPENAI_API_KEY", "MENTAL_MODEL", "OPENAI_MODEL"]:
        monkeypatch.delenv(key, raising=False)
    r = asyncio.run(SemanticExtractor({}, tmp_path).analyze({"raw_comment": "买纳指"}))
    assert r["analysis"] is None
    assert r["status"] == "FAILED"


def test_csv_escape():
    assert csv_value(" =SUM(1)") == "' =SUM(1)"
    assert csv_value("@evil").startswith("'")


def test_aggregate_distinct_and_unknown():
    a = output("茅台", [view("茅台", "茅台")])
    a["views"][0]["resolved_entity"] = {"entity_id": "STOCK:茅台", "name": "茅台"}
    rows = [
        {
            "comment_key": str(i),
            "status": "SUCCESS",
            "analysis": a,
            "user_id": None,
            "create_time": None,
            "digg_count": 0,
            "aweme_id": "v",
        }
        for i in range(2)
    ]
    ranks, methods, timeline = aggregate(rows, {})
    assert ranks[0]["mentions"] == 2
    assert ranks[0]["disagreement"] is None
    assert ranks[0]["unique_users"] is None


@pytest.mark.parametrize(
    "text,assets",
    [
        (
            "买茅台，避开宁德时代",
            [
                ("茅台", "BUY", "BULLISH", "STOCK"),
                ("宁德时代", "AVOID", "BEARISH", "STOCK"),
            ],
        ),
        ("不买黄金", [("黄金", "AVOID", "UNKNOWN", "ASSET")]),
        ("谁可以教我美股", [("美股", "NONE", "NEUTRAL", "ASSET")]),
        ("全仓做多原油", [("原油", "BUY", "BULLISH", "ASSET")]),
    ],
)
def test_semantic_contract_examples(text, assets):
    # Contract fixture: live model correctness requires the independent human set.
    a = output(text, [view(text, *args) for args in assets])
    parsed = Analysis.model_validate(a).validate_evidence(text)
    assert [(v.entity, v.action) for v in parsed.views] == [
        (args[0], args[1]) for args in assets
    ]


def test_timeout_is_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAL_API_KEY", "test")
    monkeypatch.setenv("MENTAL_MODEL", "test")

    def fail(request):
        raise httpx.ReadTimeout("timeout", request=request)

    ex = SemanticExtractor({"max_attempts": 1}, tmp_path, httpx.MockTransport(fail))
    r = asyncio.run(ex.analyze({"raw_comment": "买纳指"}))
    assert r["status"] == "FAILED"
    assert r["analysis"] is None


def test_fabricated_evidence_is_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("MENTAL_API_KEY", "test")
    monkeypatch.setenv("MENTAL_MODEL", "test")
    a = output("黄金", [view("黄金", "黄金")])
    a["views"][0]["evidence"]["quote"] = "假证据"

    def respond(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(a)}}]}
        )

    ex = SemanticExtractor({"max_attempts": 1}, tmp_path, httpx.MockTransport(respond))
    r = asyncio.run(ex.analyze({"raw_comment": "黄金"}))
    assert r["status"] == "FAILED"
    assert not list(tmp_path.glob("*.json"))


def test_no_leverage_attitude():
    a = output("我要加杠杆")
    a["risks"] = [
        {
            "rule": "NO_LEVERAGE",
            "attitude": "OPPOSE",
            "evidence": {"quote": "我要加杠杆", "start": 0, "end": 5},
        }
    ]
    assert (
        Analysis.model_validate(a).validate_evidence("我要加杠杆").risks[0].attitude
        == "OPPOSE"
    )


def test_html_escape_and_links(tmp_path):
    from core.report import make_report

    row = {
        "comment_key": "douyin:1",
        "status": "FAILED",
        "raw_comment": "<script>alert(1)</script>",
        "sources": [],
        "video_url": "javascript:alert(1)",
    }
    make_report(tmp_path, [row], [], {}, {}, {}, {})
    s = (tmp_path / "report.html").read_text()
    assert "<script>" not in s
    assert 'href="javascript:' not in s
    assert "&lt;script&gt;" in s


def test_no_substring_entity_mapping():
    resolver = EntityResolver("configs/entities.json")
    fake = view("TQQQ", "TQQQ", category="ETF")
    fake["entity"] = "QQQ"
    assert resolver.resolve(fake)["resolution"] == "UNRESOLVED"


def test_pending_human_evaluation(tmp_path):
    from evaluation.manage import evaluate

    a = tmp_path / "a.json"
    p = tmp_path / "p.json"
    a.write_text(
        json.dumps([{"split": "test", "annotation_status": "PENDING", "gold": None}])
    )
    p.write_text("[]")
    assert evaluate(a, p)["status"] == "PENDING_HUMAN_ANNOTATION"


def test_url_idless_identity(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(
        json.dumps(
            {
                "video_url": "https://www.douyin.com/note/123",
                "comments": [
                    {"comment": "买纳指"},
                    {"cid": "1", "aweme_id": "123", "comment": "买纳指"},
                ],
            }
        )
    )
    rows, _, q, _ = ingest([p])
    assert len(rows) == 1
    assert q["idless_matched"] == 1


def test_topics_insufficient():
    from core.topics import discover_topics

    assert discover_topics([], {})["status"] == "INSUFFICIENT_DATA"


def test_reject_explicit_action_contradiction():
    a = output("不买黄金", [view("不买黄金", "黄金", "BUY", "BULLISH", "ASSET")])
    with pytest.raises(ValueError):
        Analysis.model_validate(a).validate_evidence("不买黄金")


def test_reject_leverage_contradiction():
    a = output("我要加杠杆")
    a["risks"] = [
        {
            "rule": "NO_LEVERAGE",
            "attitude": "SUPPORT",
            "evidence": {"quote": "我要加杠杆", "start": 0, "end": 5},
        }
    ]
    with pytest.raises(ValueError):
        Analysis.model_validate(a).validate_evidence("我要加杠杆")


def test_local_environment_precedence(tmp_path, monkeypatch):
    from run_pipeline import load_local_environment

    monkeypatch.setenv("MENTAL_MODEL", "explicit-model")
    monkeypatch.delenv("MENTAL_BASE_URL", raising=False)
    p = tmp_path / ".env"
    p.write_text(
        "MENTAL_MODEL=file-model\nMENTAL_BASE_URL=https://api.deepseek.com\nIGNORED=test\n"
    )
    load_local_environment(p)
    assert __import__("os").environ["MENTAL_MODEL"] == "explicit-model"
    assert __import__("os").environ["MENTAL_BASE_URL"] == "https://api.deepseek.com"


def test_unique_original_quote_can_repair_offsets():
    a = output("买黄金", [view("买黄金", "黄金")])
    a["views"][0]["evidence"]["start"] = 0
    a["views"][0]["evidence"]["end"] = 2
    parsed = Analysis.model_validate(a).validate_evidence(
        "买黄金", repair_unique_offsets=True
    )
    assert parsed.views[0].evidence.start == 1
    assert len(parsed._offset_repairs) == 1


def test_repeated_quote_cannot_repair_offsets():
    a = output("黄金黄金", [view("黄金黄金", "黄金")])
    a["views"][0]["evidence"]["start"] = 1
    a["views"][0]["evidence"]["end"] = 3
    with pytest.raises(ValueError):
        Analysis.model_validate(a).validate_evidence(
            "黄金黄金", repair_unique_offsets=True
        )


def test_conclusions_reject_pilot_as_full(tmp_path):
    from build_conclusions import build

    (tmp_path / "analyzed_comments.json").write_text("[]")
    (tmp_path / "manifest.json").write_text('{"pilot":true}')
    with pytest.raises(ValueError, match="full run"):
        build(tmp_path)


def test_topic_keywords_filter_punctuation_and_function_words():
    pytest.importorskip("jieba")
    from core.topics import chinese_topic_tokens

    tokens = chinese_topic_tokens("我 的 空仓，等待。 ,  123")
    assert "空仓" in tokens and "等待" in tokens
    assert "我" not in tokens and "的" not in tokens and "123" not in tokens
    assert all(any(c.isalnum() for c in t) for t in tokens)
