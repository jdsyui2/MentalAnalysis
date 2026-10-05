import json
import re
from pathlib import Path


class EntityResolver:
    def __init__(self, path):
        self.dictionary = json.loads(Path(path).read_text(encoding="utf-8"))

    def resolve(self, view):
        name = view["entity"]
        surface = view["evidence"]["quote"]
        matches = []
        for e in self.dictionary["entities"]:
            if (
                name.casefold() in [x.casefold() for x in [e["name"]] + e["aliases"]]
                and view["category"] == e["category"]
            ):
                matches.append(e)
        if len(matches) == 1:
            e = matches[0]
            aliases = [e["name"]] + e["aliases"]

            def grounded(alias):
                pattern = re.escape(alias)
                if alias.isascii():
                    pattern = r"(?<![A-Za-z0-9])" + pattern + r"(?![A-Za-z0-9])"
                return re.search(pattern, surface, re.IGNORECASE) is not None

            if not any(grounded(alias) for alias in aliases):
                return {
                    "entity_id": "unresolved:"
                    + view["category"]
                    + ":"
                    + name.casefold(),
                    "name": name,
                    "category": view["category"],
                    "ticker": None,
                    "resolution": "UNRESOLVED",
                    "candidates": [e["id"]],
                    "reason": "NAME_NOT_GROUNDED_IN_ENTITY_EVIDENCE",
                }
            return {
                "entity_id": e["id"],
                "name": e["name"],
                "category": e["category"],
                "ticker": e.get("ticker"),
                "resolution": "RESOLVED",
                "source": e["source"],
                "source_date": e["source_date"],
                "dictionary_version": self.dictionary["version"],
            }
        return {
            "entity_id": "unresolved:" + view["category"] + ":" + name.casefold(),
            "name": name,
            "category": view["category"],
            "ticker": None,
            "resolution": "UNRESOLVED",
            "candidates": [e["id"] for e in matches],
        }
