"""Validate individual claims without discarding unrelated, sound fields."""

import re
from .schema import Analysis, Evidence
from pydantic import BaseModel


def evidence_check(value, texts, repairs):
    if value is None:
        return True
    if isinstance(value, Evidence):
        text = texts.get(value.source, "")
        if (
            value.start < value.end <= len(text)
            and text[value.start : value.end] == value.quote
        ):
            return True
        pos = text.find(value.quote)
        if pos >= 0 and text.find(value.quote, pos + 1) < 0:
            repairs.append(
                {
                    "source": value.source,
                    "quote": value.quote,
                    "supplied_start": value.start,
                    "start": pos,
                    "end": pos + len(value.quote),
                }
            )
            value.start, value.end = pos, pos + len(value.quote)
            return True
        return False
    if isinstance(value, BaseModel):
        return all(
            evidence_check(getattr(value, k), texts, repairs)
            for k in type(value).model_fields
        )
    if isinstance(value, list):
        return all(evidence_check(x, texts, repairs) for x in value)
    return True


def validate_fields(analysis: Analysis, row):
    ctx = row.get("context", {})
    texts = {
        "COMMENT": row["raw_comment"],
        "VIDEO": ctx.get("video_text", ""),
        "PARENT": ctx.get("parent_comment", ""),
        "ROOT": ctx.get("root_comment", ""),
    }
    repairs, items = [], []
    a = analysis.model_dump()
    a["field_status"] = {"intent": "REVIEW" if analysis.needs_review else "PASS"}
    if "NON_INVESTMENT" in analysis.intents and (
        analysis.views or analysis.methods or analysis.risks
    ):
        a["field_status"]["intent"] = "FAIL"
        items.append(
            {"field": "intent", "reason": "NON_INVESTMENT_WITH_INVESTMENT_FIELDS"}
        )

    def rationale_record(r):
        ok = r.source == "COMMENT" and evidence_check(r, texts, repairs)
        return r.model_dump() | {"field_status": "PASS" if ok else "FAIL"}

    for i, (model, v) in enumerate(zip(analysis.views, a["views"])):
        gate = {
            k: "PASS" for k in ("entity", "speech_act", "stance", "action", "context")
        }
        if model.evidence.source != "COMMENT" or not evidence_check(
            model.evidence, texts, repairs
        ):
            gate["entity"] = "FAIL"
        basis = model.intent_basis
        if basis in ("VIDEO_PROMPT_CONTEXT", "PARENT_CONTEXT"):
            expected = "VIDEO" if basis == "VIDEO_PROMPT_CONTEXT" else "PARENT"
            verified = (
                ctx.get("solicitation_verified", False)
                if expected == "VIDEO"
                else bool(ctx.get("parent_comment"))
            )
            ev = model.context_evidence
            if (
                not verified
                or not ev
                or ev.source != expected
                or not evidence_check(ev, texts, repairs)
            ):
                gate["context"] = gate["speech_act"] = "REVIEW"
            if model.explicit_action:
                gate["action"] = "FAIL"
        elif basis == "UNKNOWN":
            gate["context"] = gate["speech_act"] = "REVIEW"
        if model.speech_act == "UNKNOWN":
            gate["speech_act"] = "REVIEW"
        if model.stance == "UNKNOWN":
            gate["stance"] = "REVIEW"
        elif (
            not model.stance_evidence
            or model.stance_evidence.source != "COMMENT"
            or not evidence_check(model.stance_evidence, texts, repairs)
        ):
            gate["stance"] = "REVIEW"
        if model.action not in ("NONE", "UNKNOWN"):
            ev = model.action_evidence
            if (
                not model.explicit_action
                or not ev
                or ev.source != "COMMENT"
                or not evidence_check(ev, texts, repairs)
            ):
                gate["action"] = "REVIEW"
            if (
                ev
                and model.action == "BUY"
                and re.search(r"不买|别买|不要买|不能买", ev.quote)
            ):
                gate["action"] = "FAIL"
        elif model.action == "UNKNOWN":
            gate["action"] = "REVIEW"
        if model.action_evidence and not evidence_check(
            model.action_evidence, texts, repairs
        ):
            gate["action"] = "FAIL"
        v["rationales"] = [rationale_record(r) for r in model.rationales]
        gate["rationale"] = (
            "NOT_APPLICABLE"
            if not v["rationales"]
            else "PASS"
            if all(r["field_status"] == "PASS" for r in v["rationales"])
            else "FAIL"
        )
        for field in ("condition", "horizon"):
            ev = getattr(model, field)
            gate[field] = (
                "NOT_APPLICABLE"
                if ev is None
                else "PASS"
                if ev.source == "COMMENT" and evidence_check(ev, texts, repairs)
                else "FAIL"
            )
        v.update(model.model_dump(exclude={"rationales"}))
        v["field_status"] = gate
        items += [
            {"view": i, "field": k, "reason": k.upper() + "_" + st}
            for k, st in gate.items()
            if st in ("FAIL", "REVIEW")
        ]
    for collection in ("methods", "risks"):
        for i, (model, record) in enumerate(
            zip(getattr(analysis, collection), a[collection])
        ):
            ok = model.evidence.source == "COMMENT" and evidence_check(
                model.evidence, texts, repairs
            )
            status = "PASS" if ok else "FAIL"
            if model.attitude == "UNKNOWN":
                status = "REVIEW" if ok else "FAIL"
            if (
                collection == "methods"
                and model.attitude in ("SUPPORT", "SELF_PRACTICE")
                and re.search(r"别做[Tt]|不要做[Tt]|不做[Tt]", model.evidence.quote)
                and model.method == "SWING_T"
            ):
                status = "FAIL"
            if (
                collection == "risks"
                and model.rule == "NO_LEVERAGE"
                and model.attitude == "SUPPORT"
                and re.search(r"我要加杠杆|杠杆加满", model.evidence.quote)
            ):
                status = "FAIL"
            record.update(model.model_dump())
            record["field_status"] = {
                "type": "PASS" if ok else "FAIL",
                "attitude": status,
            }
            if collection == "methods":
                record["rationales"] = [rationale_record(r) for r in model.rationales]
            if status != "PASS":
                items.append(
                    {
                        "collection": collection,
                        "index": i,
                        "field": "attitude",
                        "reason": status,
                    }
                )
    a["review_items"] = items
    return a, repairs


def finalize_row(row):
    a = row.get("analysis")
    if not a:
        return row
    if row.get("conflicts"):
        a["identity_status"] = "FAIL"
        a["review_items"].append(
            {"field": "identity", "reason": "SOURCE_CONTENT_CONFLICT"}
        )
    else:
        a["identity_status"] = "PASS"
    row["status"] = (
        "PARTIAL" if a["review_items"] or a.get("needs_review") else "SUCCESS"
    )
    row["reason"] = "FIELD_REVIEW_REQUIRED" if row["status"] == "PARTIAL" else ""
    return row


def passed(item, field):
    return item.get("field_status", {}).get(field) == "PASS"


def usable(row):
    return (
        bool(row.get("analysis"))
        and row["analysis"].get("identity_status", "PASS") == "PASS"
        and row.get("status") in ("SUCCESS", "PARTIAL")
    )
