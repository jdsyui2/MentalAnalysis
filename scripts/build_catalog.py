"""Build a versioned catalog from archived official lists or normalized ASDC snapshot.
Usage: python scripts/build_catalog.py [--import-snapshot normalized.json]
Network collection is separate; no credentials required or written here.
"""

import argparse
import json
import re
import hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent


def build(snapshot=None):
    old = json.loads((ROOT / "configs/entities.json").read_text())
    entities = {
        e["id"]: dict(e, layer="GLOBAL" if e["name"] in ("QQQ", "TQQQ") else "CONCEPT")
        for e in old["entities"]
    }
    sources = []

    def security(code, name, exchange, category, source, valid_from=None):
        if not code or not name:
            return
        suffix = "SH" if exchange == "SSE" else "SZ"
        entities[f"{code}.{suffix}"] = {
            "id": f"{code}.{suffix}",
            "name": name,
            "category": category,
            "aliases": [code],
            "historical_aliases": [],
            "ticker": code,
            "ts_code": f"{code}.{suffix}",
            "market": "CN",
            "exchange": exchange,
            "layer": "SECURITY",
            "source": source,
            "source_date": "2026-09-30",
            "valid_from": valid_from,
            "valid_to": None,
        }

    if snapshot:
        imported = json.loads(Path(snapshot).read_text())
        for e in imported["entities"]:
            if not e.get("source") or not e.get("source_date"):
                raise ValueError("Snapshot requires provenance")
            entities[e["id"]] = e
        sources.append(
            {
                "source": "ASDC_NORMALIZED_SNAPSHOT",
                "sha256": hashlib.sha256(Path(snapshot).read_bytes()).hexdigest(),
            }
        )
    else:
        import pandas as pd

        for file, kind in [("szse_stock_all.xlsx", "STOCK"), ("szse_fund.xlsx", "ETF")]:
            path = ROOT / "local/catalog_sources" / file
            if not path.exists():
                continue
            df = pd.read_excel(path, dtype=str).fillna("")
            source = (
                "https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID="
                + ("1110" if kind == "STOCK" else "1105")
                + "&TABKEY=tab1"
            )
            sources.append(
                {
                    "url": source,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "rows": len(df),
                }
            )
            for row in df.to_dict("records"):
                if kind == "STOCK":
                    security(
                        row["A股代码"],
                        row["A股简称"],
                        "SZSE",
                        "STOCK",
                        source,
                        row["A股上市日期"],
                    )
                elif row.get("基金类别") == "ETF":
                    security(
                        row["基金代码"],
                        row["基金简称"],
                        "SZSE",
                        "ETF",
                        source,
                        row.get("上市日期"),
                    )
                elif (
                    "REIT" in row.get("基金类别", "").upper()
                    or "REIT" in row.get("基金简称", "").upper()
                ):
                    security(
                        row["基金代码"],
                        row["基金简称"],
                        "SZSE",
                        "REIT",
                        source,
                        row.get("上市日期"),
                    )
        for file in (
            "ssesuggestdata.js",
            "ssesuggestfunddata.js",
            "ssesuggestdataAll.js",
        ):
            path = ROOT / "local/catalog_sources" / file
            if not path.exists():
                continue
            source = "https://www.sse.com.cn/js/common/" + file
            data = path.read_text()
            pairs = re.findall(r'val:"(\d{6})",val2:"([^"]+)"', data)
            sources.append(
                {
                    "url": source,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "entries": len(pairs),
                }
            )
            for code, name in pairs:
                if code.startswith(("600", "601", "603", "605", "688", "689", "900")):
                    security(code, name, "SSE", "STOCK", source)
                elif "ETF" in name.upper():
                    security(code, name, "SSE", "ETF", source)
                elif "REIT" in name.upper():
                    security(code, name, "SSE", "REIT", source)
    # Explicitly verified index records; do not classify 000xxx government bonds as indices.
    index_source = (
        "https://www.sse.com.cn/market/sseindex/indexlist/index.shtml?classid=010202"
    )
    for code, name, aliases in [
        ("000001", "上证指数", ["上证综指", "上证综合指数"]),
        ("000016", "上证50", ["上证50指数"]),
        ("000688", "科创50", ["科创50指数"]),
        ("000010", "上证180", ["上证180指数"]),
    ]:
        entities["SSE_INDEX:" + code] = {
            "id": "SSE_INDEX:" + code,
            "name": name,
            "category": "INDEX",
            "aliases": aliases,
            "ticker": code,
            "exchange": "SSE",
            "layer": "SECURITY",
            "source": index_source,
            "source_date": "2026-10-05",
        }
    for e in entities.values():
        if e["name"] == "大盘":
            e["aliases"] = [a for a in e.get("aliases", []) if a != "上证指数"]
    # Merge former curated entries with verified security records, never duplicate an exact alias.
    for key, e in list(entities.items()):
        if e["layer"] != "SECURITY" and e["category"] == "STOCK":
            matches = [
                s
                for s in entities.values()
                if s["layer"] == "SECURITY"
                and s["category"] == "STOCK"
                and (s["name"] == e["name"] or s.get("ts_code") == e.get("ticker"))
            ]
            if len(matches) == 1:
                matches[0]["aliases"] += e.get("aliases", [])
                entities.pop(key)
    aliases = {
        "601288.SH": ["农行", "农业银行"],
        "601398.SH": ["工行", "工商银行"],
        "601939.SH": ["建行", "建设银行"],
        "601988.SH": ["中行", "中国银行"],
        "000560.SZ": ["我爱我家"],
        "688256.SH": ["寒武纪"],
        "000001.SZ": ["平安银行"],
    }
    for key, values in aliases.items():
        if key in entities:
            entities[key]["aliases"] = sorted(set(entities[key]["aliases"] + values))
    concepts = [
        ("A股市场", "ASSET", ["A股", "大A", "中国股市"]),
        ("港股市场", "ASSET", ["港股"]),
        ("美国国债", "ASSET", ["美债"]),
        ("美元", "ASSET", ["美金"]),
        ("美元指数", "INDEX", []),
        ("比特币", "ASSET", ["BTC"]),
        ("新能源", "SECTOR", []),
        ("科技板块", "SECTOR", ["科技", "科技股"]),
        ("白酒", "SECTOR", ["白酒股"]),
        ("红利低波", "SECTOR", []),
        ("纳指ETF", "ETF", []),
        ("中证红利ETF", "ETF", []),
        ("日经225ETF", "ETF", []),
        ("日经225", "INDEX", ["日经指数"]),
        ("铜", "ASSET", []),
        ("个股", "ASSET", ["股票", "强势股", "优质公司", "涨停股"]),
    ]
    for name, kind, aliases in concepts:
        existing = [e for e in entities.values() if e["name"] == name]
        if existing:
            continue
        entities["CONCEPT:" + name] = {
            "id": "CONCEPT:" + name,
            "name": name,
            "category": kind,
            "aliases": aliases,
            "ticker": None,
            "layer": "CONCEPT",
            "source": "curated-concept-ontology (no security code)",
            "source_date": "2026-10-05",
        }
    result = {
        "version": "3.0-20261005",
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "entities": list(entities.values()),
        "sources": sources,
        "coverage": dict(Counter(e["category"] for e in entities.values())),
        "gaps": [
            "BSE full security list unavailable",
            "Index coverage is curated, not a full all-index master",
            "Historical aliases and SSE listing dates incomplete",
            "Global stock coverage remains curated; not a full global security master",
        ],
    }
    (ROOT / "configs/entity_catalog.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(result["coverage"], result["gaps"])


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--import-snapshot", type=Path)
    a = p.parse_args()
    build(a.import_snapshot)
