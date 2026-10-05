"""Deterministic text clusters; these do not identify independent users."""

import re
from difflib import SequenceMatcher
from collections import defaultdict
from .ingestion import digest


def assign_duplicate_groups(rows):
    buckets = defaultdict(list)
    mapping = {}
    for text in sorted({r["cleaned_comment"] for r in rows if r["valid"]}):
        norm = re.sub(r"\W", "", text.casefold())
        candidates = []
        for length in range(
            max(0, int(len(norm) * 0.85) - 2), int(len(norm) / 0.85) + 3
        ):
            candidates.extend(buckets[length])
        match = next(
            (
                g
                for g in sorted(candidates, key=lambda x: x["norm"])
                if norm == g["norm"]
                or (
                    abs(len(norm) - len(g["norm"])) <= max(2, 0.15 * len(norm))
                    and SequenceMatcher(None, norm, g["norm"], autojunk=False).ratio()
                    >= 0.9
                )
            ),
            None,
        )
        if match is None:
            match = {"norm": norm, "id": digest(norm)}
            buckets[len(norm)].append(match)
        mapping[text] = match["id"]
    for r in rows:
        r["duplicate_group"] = mapping.get(r["cleaned_comment"])
    groups = defaultdict(list)
    for r in rows:
        if r["valid"]:
            groups[r["duplicate_group"]].append(r["comment_key"])
    return [
        {"group_id": k, "comment_keys": sorted(v)} for k, v in sorted(groups.items())
    ]
