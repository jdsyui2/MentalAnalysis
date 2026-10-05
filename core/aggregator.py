"""Aggregate only validated fields; separate recommendation, holdings and methods."""

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .schema import METHOD_NAMES
from .validation import usable, passed

TZ = ZoneInfo("Asia/Shanghai")


def aggregate(rows, config):
    valid = [r for r in rows if r.get("valid", True)]
    eligible = [r for r in valid if usable(r)]
    video_denoms = Counter(r.get("aweme_id") for r in valid if r.get("aweme_id"))
    engagement = {}
    for video in video_denoms:
        observed = [
            r
            for r in valid
            if r.get("aweme_id") == video and r.get("digg_count") is not None
        ]
        counts = Counter(float(r["digg_count"]) for r in observed)
        cumulative = 0
        pct = {}
        for number in sorted(counts):
            pct[number] = (cumulative + (counts[number] - 1) / 2) / max(
                1, len(observed) - 1
            )
            cumulative += counts[number]
        engagement.update(
            {r["comment_key"]: pct[float(r["digg_count"])] for r in observed}
        )
    groups, methods = defaultdict(list), defaultdict(list)
    risks, daily = Counter(), Counter()
    missing = 0
    for r in eligible:
        a = r["analysis"]
        for v in a["views"]:
            if (
                not passed(v, "entity")
                or v.get("resolved_entity", {}).get("resolution") != "RESOLVED"
            ):
                continue
            key = v["resolved_entity"]["entity_id"]
            groups[key].append((r, v))
        for m in {m["method"]: m for m in a["methods"] if passed(m, "type")}.values():
            methods[m["method"]].append((r, m))
        for risk in {
            (x["rule"], x["attitude"])
            for x in a["risks"]
            if passed(x, "type") and passed(x, "attitude")
        }:
            risks[risk] += 1
        try:
            daily[
                datetime.fromtimestamp(float(r["create_time"]), TZ).date().isoformat()
            ] += 1
        except (TypeError, ValueError, OverflowError, OSError, KeyError):
            missing += 1
    ranks, timeline = [], []
    cutoff = (
        datetime.fromisoformat(config["analysis_cutoff"]).astimezone(TZ)
        if config.get("analysis_cutoff")
        else None
    )
    for key, pairs in groups.items():
        all_pairs = pairs
        by_comment = defaultdict(list)
        for r, v in all_pairs:
            by_comment[r["comment_key"]].append((r, v))
        pairs = []
        for same in by_comment.values():
            r, first = same[0]
            merged = dict(first, field_status=dict(first["field_status"]))
            for field in ("stance", "action"):
                values = {
                    v[field]
                    for _, v in same
                    if passed(v, field) and v[field] != "UNKNOWN"
                }
                merged[field] = next(iter(values)) if len(values) == 1 else "UNKNOWN"
                merged["field_status"][field] = "PASS" if len(values) == 1 else "REVIEW"
            pairs.append((r, merged))
        stances = Counter(
            v["stance"] if passed(v, "stance") else "UNKNOWN" for r, v in pairs
        )
        actions = Counter(
            label
            for cid, label in {
                (r["comment_key"], v["action"])
                for r, v in all_pairs
                if passed(v, "action")
            }
        )
        action_unknown = len(by_comment) - len(
            {r["comment_key"] for r, v in all_pairs if passed(v, "action")}
        )
        if action_unknown:
            actions["UNKNOWN"] = action_unknown
        speech = Counter(
            label
            for cid, label in {
                (r["comment_key"], v["speech_act"])
                for r, v in all_pairs
                if passed(v, "speech_act")
            }
        )

        def count_if(predicate):
            return len({r["comment_key"] for r, v in all_pairs if predicate(v)})

        explicit = count_if(
            lambda v: (
                passed(v, "speech_act")
                and v["speech_act"] == "RECOMMENDATION"
                and v["action"] not in ("AVOID", "SELL", "WAIT")
                and v["intent_basis"] == "EXPLICIT_COMMENT"
            )
        )
        contextual = count_if(
            lambda v: (
                passed(v, "speech_act")
                and passed(v, "context")
                and v["speech_act"] == "RECOMMENDATION"
                and v["action"] not in ("AVOID", "SELL", "WAIT")
                and v["intent_basis"] in ("VIDEO_PROMPT_CONTEXT", "PARENT_CONTEXT")
            )
        )
        holds = count_if(
            lambda v: passed(v, "speech_act") and v["speech_act"] == "SELF_POSITION"
        )
        recommendation_comments = count_if(
            lambda v: (
                passed(v, "speech_act")
                and v["speech_act"] == "RECOMMENDATION"
                and v["action"] not in ("AVOID", "SELL", "WAIT")
                and (v["intent_basis"] == "EXPLICIT_COMMENT" or passed(v, "context"))
            )
        )
        b, s = stances["BULLISH"], stances["BEARISH"]
        n = b + s
        weight = {
            label: sum(
                1 + engagement[r["comment_key"]]
                for r, v in pairs
                if r["comment_key"] in engagement
                and passed(v, "stance")
                and v["stance"] == label
            )
            for label in ("BULLISH", "BEARISH")
        }
        reasons = defaultdict(list)
        for r, v in all_pairs:
            for reason in v.get("rationales", []):
                if reason.get("field_status") == "PASS":
                    reasons[
                        (
                            reason["reason_code"],
                            v["stance"] if passed(v, "stance") else "UNKNOWN",
                        )
                    ].append({"comment_key": r["comment_key"], "evidence": reason})
        videos = Counter(r.get("aweme_id") for r, v in pairs if r.get("aweme_id"))
        users = {r.get("user_id") for r, v in pairs if r.get("user_id")}
        ranks.append(
            {
                "entity": pairs[0][1]["resolved_entity"],
                "mentions": len(pairs),
                "explicit_recommendation_count": explicit,
                "context_recommendation_count": contextual,
                "recommendation_count": recommendation_comments,
                "self_position_count": holds,
                "self_position_buy_count": count_if(
                    lambda v: (
                        passed(v, "speech_act")
                        and v["speech_act"] == "SELF_POSITION"
                        and passed(v, "action")
                        and v["action"] == "BUY"
                    )
                ),
                "hold_count": actions["HOLD"],
                "watch_count": actions["WATCH"],
                "avoid_count": actions["AVOID"],
                "sell_count": actions["SELL"],
                "stances": dict(stances),
                "actions": dict(actions),
                "speech_acts": dict(speech),
                "unique_text_mentions": len(
                    {r.get("cleaned_comment", r["comment_key"]) for r, v in pairs}
                ),
                "near_duplicate_cluster_mentions": len(
                    {r.get("duplicate_group") or r["comment_key"] for r, v in pairs}
                ),
                "video_count": len(videos),
                "video_total": len(video_denoms),
                "video_rates": {
                    str(v): videos[v] / denom for v, denom in video_denoms.items()
                },
                "video_balanced_score": sum(
                    videos[v] / denom for v, denom in video_denoms.items()
                )
                / max(1, len(video_denoms)),
                "unique_users": len(users) if users else None,
                "user_id_coverage": sum(bool(r.get("user_id")) for r, v in pairs)
                / len(pairs),
                "bullish_index": round(math.log((1 + b) / (1 + s)), 4),
                "directional_count": n,
                "bull_ratio": b / n if n else None,
                "disagreement": 2 * min(b, s) / n if n else None,
                "sample_status": "SUFFICIENT" if n >= 10 else "INSUFFICIENT",
                "engagement_adjusted_bull_ratio": weight["BULLISH"]
                / sum(weight.values())
                if sum(weight.values())
                else None,
                "engagement_observed_comments": sum(
                    r["comment_key"] in engagement for r, v in pairs
                ),
                "rationales": [
                    {
                        "reason_code": k[0],
                        "stance": k[1],
                        "summary": ev[0]["evidence"]["summary"],
                        "mentions": len({x["comment_key"] for x in ev}),
                        "evidence": ev,
                    }
                    for k, ev in sorted(
                        reasons.items(), key=lambda x: (-len(x[1]), x[0])
                    )
                ],
                "recommendation_comments": sorted(
                    {
                        r["comment_key"]
                        for r, v in all_pairs
                        if passed(v, "speech_act")
                        and v["speech_act"] == "RECOMMENDATION"
                        and v["action"] not in ("AVOID", "SELL", "WAIT")
                        and (
                            v["intent_basis"] == "EXPLICIT_COMMENT"
                            or passed(v, "context")
                        )
                    }
                ),
                "avoid_comments": sorted(
                    {
                        r["comment_key"]
                        for r, v in all_pairs
                        if passed(v, "action") and v["action"] in ("AVOID", "SELL")
                    }
                ),
                "direction_comments": {
                    label: sorted(
                        {
                            r["comment_key"]
                            for r, v in pairs
                            if passed(v, "stance") and v["stance"] == label
                        }
                    )
                    for label in ("BULLISH", "BEARISH")
                },
                "representative_comments": [
                    r["comment_key"]
                    for r, v in sorted(
                        pairs,
                        key=lambda x: (-len(x[1]["rationales"]), x[0]["comment_key"]),
                    )[:5]
                ],
                "verification": "UGC_UNVERIFIED",
            }
        )
        days, times = Counter(), []
        for r, v in pairs:
            try:
                t = datetime.fromtimestamp(float(r["create_time"]), TZ)
                times.append(t)
                days[t.date().isoformat()] += 1
            except (TypeError, ValueError, OverflowError, OSError, KeyError):
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
            prev = sum(
                cutoff - timedelta(hours=48) <= t < cutoff - timedelta(hours=24)
                for t in times
            )
            mom = (current - prev) / (prev + 1)
            item.update(
                current_mentions=current,
                previous_mentions=prev,
                momentum=mom,
                trend_status="COMPARABLE_WINDOWS",
                trend_label="RISING"
                if mom >= 0.5
                else "FADING"
                if mom <= -0.5
                else "STABLE",
            )
        timeline.append(item)
    ranks.sort(
        key=lambda x: (
            -x["recommendation_count"],
            -x["mentions"],
            x["entity"]["entity_id"],
        )
    )
    ranking = []
    for key, pairs in sorted(methods.items(), key=lambda x: (-len(x[1]), x[0])):
        attitudes = Counter(
            m["attitude"] if passed(m, "attitude") else "UNKNOWN" for r, m in pairs
        )
        directional = attitudes["SUPPORT"] + attitudes["OPPOSE"]
        ranking.append(
            {
                "method": key,
                "method_name": METHOD_NAMES[key],
                "count": len(pairs),
                "percentage": 100 * len(pairs) / len(eligible) if eligible else 0,
                "attitudes": dict(attitudes),
                "net_support_rate": (attitudes["SUPPORT"] - attitudes["OPPOSE"])
                / directional
                if directional
                else None,
                "directional_count": directional,
                "sample_status": "SUFFICIENT" if directional >= 10 else "INSUFFICIENT",
                "comment_keys": [r["comment_key"] for r, m in pairs],
                "support_comment_keys": sorted(
                    {
                        r["comment_key"]
                        for r, m in pairs
                        if passed(m, "attitude") and m["attitude"] == "SUPPORT"
                    }
                ),
            }
        )
    return (
        ranks,
        {
            "denominator": len(eligible),
            "method_bearing_comments": len(
                {r["comment_key"] for pairs in methods.values() for r, m in pairs}
            ),
            "multi_label": True,
            "ranking": ranking,
            "risk_attitudes": [
                {"rule": k[0], "attitude": k[1], "count": v}
                for k, v in sorted(risks.items())
            ],
        },
        {
            "timezone": "Asia/Shanghai",
            "daily_analyzed_comments": dict(sorted(daily.items())),
            "missing_time": missing,
            "entities": timeline,
        },
    )
