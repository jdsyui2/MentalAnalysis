"""Versioned security, global asset and concept catalogs; no invented codes."""

import json
import re
from pathlib import Path
from datetime import datetime
from .ingestion import digest


class EntityResolver:
    def __init__(self, path):
        self.dictionary = json.loads(Path(path).read_text(encoding="utf-8"))
        self.sha256 = digest(self.dictionary)
        self.index = {}
        for e in self.dictionary["entities"]:
            for alias in (
                [e["name"]]
                + e.get("aliases", [])
                + e.get("historical_aliases", [])
                + [e.get("ticker"), e.get("ts_code")]
            ):
                if alias:
                    self.index.setdefault(alias.casefold(), []).append(e)
        alternatives = [
            r"(?<![A-Za-z0-9])" + re.escape(a) + r"(?![A-Za-z0-9])"
            if a.isascii()
            else re.escape(a)
            for a in sorted(self.index, key=lambda a: (-len(a), a))
        ]
        self.mention_pattern = re.compile("|".join(alternatives), re.IGNORECASE)

    @staticmethod
    def grounded(alias, text):
        pattern = re.escape(alias)
        if alias.isascii():
            pattern = r"(?<![A-Za-z0-9])" + pattern + r"(?![A-Za-z0-9])"
        return re.search(pattern, text, re.IGNORECASE) is not None

    def candidates(self, text):
        matches = {}
        for found in self.mention_pattern.finditer(text):
            alias = found.group().casefold()
            for e in self.index.get(alias, []):
                matches[e["id"]] = {
                    "entity_id": e["id"],
                    "name": e["name"],
                    "category": e["category"],
                    "matched_alias": alias,
                }
        return sorted(matches.values(), key=lambda e: e["entity_id"])

    def resolve(self, view, timestamp=None, text=""):
        name, surface = view["entity"], view["evidence"]["quote"]
        matches = []
        when = None
        try:
            when = datetime.fromtimestamp(float(timestamp)).date().isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            pass
        for e in self.index.get(name.casefold(), []):
            if e in matches:
                continue
            # Catalog category takes precedence over the model only for same-family concepts.
            if view["category"] != e["category"] and {
                view["category"],
                e["category"],
            } != {"INDEX", "ASSET"}:
                continue
            if when and (
                (e.get("valid_from") and when < e["valid_from"])
                or (e.get("valid_to") and when > e["valid_to"])
            ):
                continue
            if any(
                self.grounded(alias, surface)
                for alias in [e["name"]]
                + e.get("aliases", [])
                + e.get("historical_aliases", [])
            ):
                matches.append(e)
        if len(matches) == 1:
            e = matches[0]
            ambiguous = e["name"] in ("我爱我家", "老百姓", "机器人")
            if ambiguous and not re.search(
                r"股票|上市公司|股份|持仓|分红|估值|业绩|买入|卖出|(?:买|卖|持有|看好).{0,6}"
                + re.escape(name),
                text,
            ):
                return {
                    "entity_id": "unresolved:" + e["id"],
                    "name": name,
                    "category": view["category"],
                    "ticker": None,
                    "resolution": "UNRESOLVED",
                    "candidates": [e["id"]],
                    "reason": "ORDINARY_PHRASE_REQUIRES_DISAMBIGUATION",
                }
            return {
                "entity_id": e["id"],
                "name": e["name"],
                "category": e["category"],
                "ticker": e.get("ticker"),
                "ts_code": e.get("ts_code"),
                "market": e.get("market"),
                "exchange": e.get("exchange"),
                "layer": e.get("layer", "CONCEPT"),
                "resolution": "RESOLVED",
                "source": e["source"],
                "source_date": e["source_date"],
                "dictionary_version": self.dictionary["version"],
                "resolution_method": "GROUNDED_EXACT_ALIAS",
                "resolution_confidence": "LEXICAL_EXACT",
            }
        return {
            "entity_id": "unresolved:" + view["category"] + ":" + name.casefold(),
            "name": name,
            "category": view["category"],
            "ticker": None,
            "resolution": "UNRESOLVED",
            "candidates": [e["id"] for e in matches],
            "reason": "AMBIGUOUS_OR_MISSING_OR_UNGROUNDED",
        }
