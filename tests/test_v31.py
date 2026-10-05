import copy
import json
from pathlib import Path
import pytest
from core.presentation import (
    group_name,
    group_ranks,
    product_label,
    render_boards,
    MATURITY,
)
from build_conclusions import insights


@pytest.mark.parametrize(
    "entity,expected",
    [
        ({"layer": "SECURITY", "category": "STOCK"}, "securities"),
        ({"layer": "SECURITY", "category": "ETF"}, "securities"),
        ({"layer": "SECURITY", "category": "REIT"}, "securities"),
        ({"layer": "SECURITY", "category": "INDEX"}, "assets"),
        ({"layer": "GLOBAL", "category": "ETF"}, "assets"),
        ({"layer": "CONCEPT", "category": "SECTOR"}, "sectors"),
        ({"entity_id": "CONCEPT:个股", "category": "ASSET"}, "other"),
        ({"category": "STOCK", "layer": "CONCEPT"}, "unbound_companies"),
        ({"category": "UNSEEN"}, "other"),
    ],
)
def test_routes(entity, expected):
    assert group_name(entity) == expected


def test_fund_product_label():
    assert product_label({"category": "ETF", "ticker": "QQQ"}) == "具体基金"
    assert "概念" in product_label({"category": "ETF"})


def test_empty_boards_and_maturity():
    body = render_boards([], {"ranking": [], "denominator": 0}, local=False)
    assert body.count("暂无通过校验的数据") == 6
    assert (
        MATURITY["maturity_level"] == "RESEARCH_ASSIST"
        and not MATURITY["model_accuracy_validated"]
    )
    assert MATURITY["promotion_state"] == "RESEARCH_ONLY"


@pytest.mark.parametrize("n", [0, 1, 9, 10])
def test_method_denominator_and_all_attitudes(n):
    m = {
        "method_name": "<script>",
        "count": 11,
        "attitudes": {"SUPPORT": n, "SELF_PRACTICE": 11 - n},
        "net_support_rate": 1 if n else None,
    }
    body = render_boards([], {"ranking": [m], "denominator": 20})
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert "55.0%" in body and "支持＋反对分母" in body
    assert str(n) + ("（样本不足）" if n < 10 else "") in body
    assert ("100.0%" if n else "—") in body


def test_group_conservation_and_generic_not_recommended():
    source = json.loads(
        Path("output/public/20261005T111901191947/ticker_consensus.json").read_text()
    )
    original = copy.deepcopy(source)
    groups = group_ranks(source)
    assert sum(map(len, groups.values())) == len(source)
    ids = [a["entity"]["entity_id"] for xs in groups.values() for a in xs]
    assert len(ids) == len(set(ids)) and source == original
    facts = insights(source, {"ranking": []})
    assert not any(f.get("entity_id") == "CONCEPT:个股" for f in facts)
    assert {f["board"] for f in facts if f["kind"] == "RECOMMENDED"} == {
        "securities",
        "assets",
        "sectors",
    }


@pytest.mark.parametrize("videos", [1, 3])
def test_video_coverage_denominator(videos):
    source = json.loads(
        Path("output/public/20261005T111901191947/ticker_consensus.json").read_text()
    )[0]
    source["video_count"] = 1
    source["video_total"] = videos
    body = render_boards([source], {"ranking": [], "denominator": 10})
    assert f"1/{videos}" in body


def test_revision_preserves_source_and_refuses_overwrite(tmp_path):
    from scripts.rebuild_report import rebuild

    source = tmp_path / "source"
    source.mkdir()
    files = {
        "manifest": {
            "schema_version": "3.0",
            "config": {},
            "pilot": False,
            "model": "mock",
            "prompt_version": "3.0",
            "generated_at": "now",
            "run_status": "COMPLETE",
            "catalog_coverage": {},
            "catalog_gaps": [],
            "files": [],
        },
        "analyzed_comments": [],
        "quality": {"reply_rows": 0},
        "topics": {"status": "INSUFFICIENT_DATA", "topics": [], "spaces": {}},
    }
    for name, data in files.items():
        (source / (name + ".json")).write_text(json.dumps(data))
    original = {p.name: p.read_bytes() for p in source.iterdir()}
    revision = tmp_path / "revision"
    public = tmp_path / "public"
    rebuild(source, public, revision)
    assert original == {p.name: p.read_bytes() for p in source.iterdir()}
    m = json.loads((revision / "manifest.json").read_text())
    assert m["source_run_id"] == "source" and m["report_revision_api_calls"] == 0
    assert m["schema_version"] == "3.0" and m["report_version"] == "3.1.0"
    assert "report_taxonomy.json" in m["report_code_hashes"]
    with pytest.raises(ValueError, match="already exists"):
        rebuild(source, public, revision)
    assert "RESEARCH_ASSIST" in (public / "report.html").read_text()
