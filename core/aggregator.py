import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .schema import METHOD_NAMES

TZ = ZoneInfo("Asia/Shanghai")


def aggregate(rows, config):
    groups = defaultdict(list)
    methods = defaultdict(list)
    risks = Counter()
    daily = Counter()
    unknown_time = 0
    eligible = [r for r in rows if r["status"] == "SUCCESS"]
    for r in eligible:
        a = r["analysis"]
        seen = set()
        for v in a["views"]:
            key = v["resolved_entity"]["entity_id"]
            if key not in seen:
                groups[key].append((r, v))
                seen.add(key)
        for method in {m["method"] for m in a["methods"]}:
            methods[method].append(r["comment_key"])
        for risk in {(x["rule"], x["attitude"]) for x in a["risks"]}:
            risks[risk] += 1
        try:
            date = (
                datetime.fromtimestamp(float(r["create_time"]), TZ).date().isoformat()
            )
            daily[date] += 1
        except (TypeError, ValueError, OverflowError, OSError):
            unknown_time += 1
    ranks = []
    timeline = []
    cutoff = (
        datetime.fromisoformat(config["analysis_cutoff"]).astimezone(TZ)
        if config.get("analysis_cutoff")
        else None
    )
    for key, pairs in groups.items():
        stances = Counter(v["stance"] for r, v in pairs)
        actions = Counter(v["action"] for r, v in pairs)
        b = stances["BULLISH"]
        s = stances["BEARISH"]
        n = b + s
        weight = {
            label: sum(
                1 + math.log1p(max(0, float(r.get("digg_count") or 0)))
                for r, v in pairs
                if v["stance"] == label
            )
            for label in ["BULLISH", "BEARISH"]
        }
        reason_groups = defaultdict(list)
        for r, v in pairs:
            for reason in v.get("rationales", []):
                reason_groups[(reason["category"], reason["summary"])].append(
                    {
                        "comment_key": r["comment_key"],
                        "stance": v["stance"],
                        "action": v["action"],
                        "evidence": reason,
                    }
                )
        users = {r["user_id"] for r, v in pairs if r["user_id"]}
        videos = {r["aweme_id"] for r, v in pairs if r["aweme_id"]}
        ranks.append(
            {
                "entity": pairs[0][1]["resolved_entity"],
                "mentions": len(pairs),
                "recommend_count": sum(actions[k] for k in ["BUY", "HOLD", "WATCH"]),
                "oppose_count": sum(actions[k] for k in ["AVOID", "SELL"]),
                "stances": dict(stances),
                "actions": dict(actions),
                "video_count": len(videos),
                "unique_users": len(users) if users else None,
                "user_id_coverage": sum(bool(r["user_id"]) for r, v in pairs)
                / len(pairs),
                "bullish_index": round(math.log((1 + b) / (1 + s)), 4),
                "directional_count": n,
                "bull_ratio": b / n if n else None,
                "disagreement": 2 * min(b, s) / n if n else None,
                "sample_status": "SUFFICIENT" if n >= 10 else "INSUFFICIENT",
                "weighted_directional_ratio": weight["BULLISH"] / sum(weight.values())
                if sum(weight.values())
                else None,
                "rationales": [
                    {
                        "category": k[0],
                        "summary": k[1],
                        "mentions": len({x["comment_key"] for x in ev}),
                        "evidence": ev,
                    }
                    for k, ev in sorted(
                        reason_groups.items(), key=lambda x: (-len(x[1]), x[0])
                    )
                ],
                "representative_comments": [
                    r["comment_key"]
                    for r, v in sorted(
                        pairs,
                        key=lambda rv: (
                            -len(rv[1].get("rationales", [])),
                            -float(rv[0].get("digg_count") or 0),
                            rv[0]["comment_key"],
                        ),
                    )[:5]
                ],
            }
        )
        days = Counter()
        times = []
        for r, v in pairs:
            try:
                t = datetime.fromtimestamp(float(r["create_time"]), TZ)
                days[t.date().isoformat()] += 1
                times.append(t)
            except (TypeError, ValueError, OverflowError, OSError):
                pass
        item = {
            "entity_id": key,
            "daily": dict(sorted(days.items())),
            "momentum": None,
            "trend_status": "SAMPLE_DISTRIBUTION_ONLY",
        }
        if (
            cutoff
            and config.get("comparable_complete_windows")
            and len(times) == len(pairs)
        ):
            current = sum(cutoff - timedelta(hours=24) <= t < cutoff for t in times)
            previous = sum(
                cutoff - timedelta(hours=48) <= t < cutoff - timedelta(hours=24)
                for t in times
            )
            mom = (current - previous) / (previous + 1)
            item.update(
                current_mentions=current,
                previous_mentions=previous,
                momentum=mom,
                trend_status="COMPARABLE_WINDOWS",
                trend_label="RISING"
                if mom >= 0.5
                else "FADING"
                if mom <= -0.5
                else "STABLE",
            )
        timeline.append(item)
    ranks.sort(key=lambda x: (-x["mentions"], x["entity"]["entity_id"]))
    return (
        ranks,
        {
            "denominator": len(eligible),
            "multi_label": True,
            "ranking": [
                {
                    "method": k,
                    "method_name": METHOD_NAMES[k],
                    "count": len(v),
                    "percentage": 100 * len(v) / len(eligible) if eligible else 0,
                    "comment_keys": v,
                }
                for k, v in sorted(methods.items(), key=lambda x: (-len(x[1]), x[0]))
            ],
            "risk_attitudes": [
                {"rule": k[0], "attitude": k[1], "count": v}
                for k, v in sorted(risks.items())
            ],
        },
        {
            "timezone": "Asia/Shanghai",
            "daily_analyzed_comments": dict(sorted(daily.items())),
            "missing_time": unknown_time,
            "entities": timeline,
        },
    )
