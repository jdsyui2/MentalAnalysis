import hashlib
import math
import json
import re
from collections import defaultdict
from pathlib import Path
from .preprocessor import CommentCleaner


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def nonnegative_number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def ingest(paths):
    cleaner = CommentCleaner()
    observations = []
    files = []
    for path in sorted(set(map(Path, paths))):
        info = {"path": str(path.resolve())}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            info["sha256"] = digest(payload)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("comments"), list
            ):
                files.append(
                    dict(info, status="EXCLUDED", reason="not a comments object")
                )
                continue
            info.update(
                status="INCLUDED",
                raw_rows=len(payload["comments"]),
                coverage=payload.get("coverage"),
                video_url=payload.get("video_url"),
                total_reported=payload.get("total_reported"),
                success=payload.get("success"),
                collection_metadata={
                    k: v for k, v in payload.items() if k != "comments"
                },
            )
            for index, c in enumerate(payload["comments"]):
                if not isinstance(c, dict) or not isinstance(c.get("comment"), str):
                    observations.append(
                        {
                            "invalid": True,
                            "source": {"file": str(path.resolve()), "row": index},
                            "raw": c,
                        }
                    )
                    continue
                url = c.get("video_url") or payload.get("video_url")
                video = c.get("aweme_id") or (
                    re.search(r"/(?:video|note)/(\d+)", url or "").group(1)
                    if re.search(r"/(?:video|note)/(\d+)", url or "")
                    else url
                )
                video = str(video) if video else None
                observations.append(
                    {
                        "raw": c,
                        "cid": str(c["cid"]) if c.get("cid") else None,
                        "video": video,
                        "video_url": url,
                        "text": c["comment"],
                        "normalized": cleaner.clean_text(c["comment"]),
                        "source": {
                            "file": str(path.resolve()),
                            "row": index,
                            "metadata": c,
                        },
                    }
                )
        except (ValueError, OSError) as e:
            info.update(status="ERROR", reason=str(e))
        files.append(info)
    by_identity = {}
    missing = []
    invalid = []
    for o in observations:
        if o.get("invalid"):
            invalid.append(o)
            continue
        if not o["cid"]:
            missing.append(o)
            continue
        key = "douyin:" + o["cid"]
        if key not in by_identity:
            by_identity[key] = o | {
                "comment_key": key,
                "identity_confidence": "HIGH",
                "sources": [],
                "conflicts": [],
            }
        target = by_identity[key]
        target["sources"].append(o["source"])
        if target["text"] != o["text"] or target["video"] != o["video"]:
            target["conflicts"].append(o["source"])
    candidates = defaultdict(list)
    for row in by_identity.values():
        candidates[(row["video"], row["normalized"])].append(row)
    merged = 0
    for o in missing:
        matches = (
            candidates.get((o["video"], o["normalized"]), []) if o["video"] else []
        )
        if len(matches) == 1:
            matches[0]["sources"].append(o["source"])
            merged += 1
        else:
            key = "unidentified:" + digest(o["source"])
            by_identity[key] = o | {
                "comment_key": key,
                "identity_confidence": "LOW",
                "sources": [o["source"]],
                "conflicts": [],
            }
    records = []
    for r in by_identity.values():
        c = r["raw"]
        user = c.get("user") if isinstance(c.get("user"), dict) else {}
        user_id = (
            c.get("uid")
            or c.get("user_id")
            or c.get("sec_uid")
            or user.get("uid")
            or user.get("sec_uid")
        )
        records.append(
            dict(
                comment_key=r["comment_key"],
                cid=r["cid"],
                platform="douyin",
                aweme_id=r["video"],
                video_url=r["video_url"],
                raw_comment=r["text"],
                cleaned_comment=r["normalized"],
                create_time=c.get("create_time"),
                level=c.get("level"),
                parent_comment_id=c.get("parent_comment_id") or c.get("reply_id"),
                digg_count=nonnegative_number(c.get("digg_count")),
                reply_count=nonnegative_number(c.get("reply_comment_total")),
                root_comment_id=c.get("root_comment_id"),
                user_id=str(user_id) if user_id else None,
                nickname=c.get("nickname"),
                identity_confidence=r["identity_confidence"],
                sources=r["sources"],
                conflicts=r["conflicts"],
                valid=cleaner.process({"comment": r["text"]}) is not None,
            )
        )
    quality = {
        "raw_rows": len(observations),
        "invalid_rows": len(invalid),
        "identity_records": len(records),
        "merged_observations": len(observations) - len(invalid) - len(records),
        "idless_matched": merged,
        "low_identity_records": sum(r["identity_confidence"] == "LOW" for r in records),
        "valid_records": sum(r["valid"] for r in records),
        "noise_records": sum(not r["valid"] for r in records),
        "text_collapsed_records": len({r["cleaned_comment"] for r in records}),
        "missing_time": sum(r["create_time"] is None for r in records),
        "missing_user_id": sum(r["user_id"] is None for r in records),
        "reply_rows": sum(r["level"] == "reply" for r in records),
    }
    assert (
        quality["raw_rows"]
        == quality["invalid_rows"]
        + quality["identity_records"]
        + quality["merged_observations"]
    )
    return records, files, quality, invalid
