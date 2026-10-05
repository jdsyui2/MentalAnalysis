"""Only source-backed context can justify an implicit recommendation."""

import json
from pathlib import Path
from .ingestion import digest


def load_context(path):
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    contexts = data.get("videos", {})
    for ctx in contexts.values():
        if ctx.get("solicitation_verified") and not (
            ctx.get("source_url")
            and ctx.get("retrieved_at")
            and ctx.get("video_question")
            and ctx["video_question"] in ctx.get("video_text", "")
        ):
            raise ValueError(
                "Verified solicitation requires timestamp, source and verbatim question in video_text"
            )
    return contexts


def attach_context(rows, contexts):
    by_id = {r["cid"]: r for r in rows if r.get("cid")}
    for r in rows:
        c = dict(contexts.get(r.get("aweme_id"), {}))
        for field, key in (
            ("parent_comment", "parent_comment_id"),
            ("root_comment", "root_comment_id"),
        ):
            parent = by_id.get(r.get(key))
            c[field] = (
                parent["raw_comment"]
                if parent and parent["aweme_id"] == r["aweme_id"]
                else ""
            )
        c.setdefault("solicitation_verified", False)
        c.setdefault("video_text", "")
        r["context"] = c
        r["context_sha256"] = digest(c)
