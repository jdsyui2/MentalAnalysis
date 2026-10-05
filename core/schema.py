"""Versioned, evidence-grounded semantic output contract."""

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

SCHEMA_VERSION = "2.0"
METHOD_NAMES = dict(
    zip(
        [
            "INDEX_DCA",
            "HIGH_DIVIDEND",
            "VALUE",
            "TECH_GROWTH",
            "TREND",
            "SWING_T",
            "GRID",
            "SECTOR_ROTATION",
            "CYCLE_DIP",
            "CASH_WAIT",
            "ASSET_ALLOCATION",
            "POSITION_RISK",
            "EXIT",
            "OTHER",
        ],
        [
            "指数定投",
            "高股息",
            "价值投资",
            "科技成长",
            "趋势交易",
            "波段/做T",
            "网格交易",
            "行业轮动",
            "周期低吸",
            "现金等待",
            "资产配置",
            "仓位风控",
            "退出交易",
            "其他",
        ],
    )
)
PROMPT_VERSION = "investment-2.0"
METHODS = [
    "INDEX_DCA",
    "HIGH_DIVIDEND",
    "VALUE",
    "TECH_GROWTH",
    "TREND",
    "SWING_T",
    "GRID",
    "SECTOR_ROTATION",
    "CYCLE_DIP",
    "CASH_WAIT",
    "ASSET_ALLOCATION",
    "POSITION_RISK",
    "EXIT",
    "OTHER",
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    quote: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Rationale(Evidence):
    category: Literal[
        "VALUATION",
        "FUNDAMENTALS",
        "INDUSTRY",
        "TECHNICAL",
        "DIVIDEND",
        "POLICY",
        "CATALYST",
        "FLOW",
        "RISK",
        "OTHER",
    ]
    summary: str = Field(min_length=1)


class View(StrictModel):
    entity: str = Field(min_length=1)
    category: Literal["STOCK", "ETF", "INDEX", "SECTOR", "ASSET"]
    evidence: Evidence
    stance: Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
    action: Literal["BUY", "HOLD", "WATCH", "WAIT", "AVOID", "SELL", "NONE", "UNKNOWN"]
    action_evidence: Evidence | None = None
    rationales: list[Rationale] = Field(default_factory=list)
    condition: Evidence | None = None
    horizon: Evidence | None = None
    claim_type: Literal["OPINION", "FACT_CLAIM", "RUMOR", "FORECAST"] = "OPINION"


class Method(StrictModel):
    method: Literal[
        "INDEX_DCA",
        "HIGH_DIVIDEND",
        "VALUE",
        "TECH_GROWTH",
        "TREND",
        "SWING_T",
        "GRID",
        "SECTOR_ROTATION",
        "CYCLE_DIP",
        "CASH_WAIT",
        "ASSET_ALLOCATION",
        "POSITION_RISK",
        "EXIT",
        "OTHER",
    ]
    evidence: Evidence


class Risk(StrictModel):
    rule: Literal[
        "NO_LEVERAGE", "STAGED_REBALANCE", "DRAWDOWN_CONTROL", "DISCIPLINE_EXECUTION"
    ]
    attitude: Literal["SUPPORT", "OPPOSE", "MENTION", "UNKNOWN"]
    evidence: Evidence


class Analysis(StrictModel):
    _offset_repairs: list = PrivateAttr(default_factory=list)
    intents: list[
        Literal[
            "RECOMMENDATION",
            "QUESTION",
            "POSITION",
            "HISTORY",
            "RISK_DISCUSSION",
            "MENTION",
            "NON_INVESTMENT",
        ]
    ] = Field(min_length=1)
    views: list[View] = Field(default_factory=list)
    methods: list[Method] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    confidence_self_reported: float = Field(ge=0, le=1)
    needs_review: bool = False
    review_reason: str = ""

    def validate_evidence(self, text: str, repair_unique_offsets=False):
        def visit(value):
            if isinstance(value, Evidence):
                if (
                    value.end <= value.start
                    or value.end > len(text)
                    or text[value.start : value.end] != value.quote
                ):
                    position = text.find(value.quote)
                    if (
                        repair_unique_offsets
                        and position >= 0
                        and text.find(value.quote, position + 1) == -1
                    ):
                        self._offset_repairs.append(
                            {
                                "quote": value.quote,
                                "supplied_start": value.start,
                                "supplied_end": value.end,
                                "start": position,
                                "end": position + len(value.quote),
                            }
                        )
                        value.start = position
                        value.end = position + len(value.quote)
                    else:
                        raise ValueError(
                            "Evidence offsets/quote do not match original text"
                        )
            if isinstance(value, BaseModel):
                for name in type(value).model_fields:
                    visit(getattr(value, name))
            elif isinstance(value, list):
                for x in value:
                    visit(x)

        visit(self)
        for v in self.views:
            if v.action not in ("NONE", "UNKNOWN") and v.action_evidence is None:
                raise ValueError("Directional action requires original action evidence")
        if "NON_INVESTMENT" in self.intents and (
            self.views or self.methods or self.risks
        ):
            raise ValueError(
                "NON_INVESTMENT means the ENTIRE comment has no investment content. For mixed comments with any investment content, remove NON_INVESTMENT and keep investment intents and extractions."
            )
        for v in self.views:
            quote = v.action_evidence.quote if v.action_evidence else ""
            if v.action == "BUY" and re.search(r"(不买|别买|不要买|不能买)", quote):
                raise ValueError(
                    "BUY contradicts explicit negative purchase evidence; use scoped evidence"
                )
        for risk in self.risks:
            if (
                risk.rule == "NO_LEVERAGE"
                and risk.attitude == "SUPPORT"
                and re.search(
                    r"(我要加杠杆|杠杆加满|梭哈[，,、 ]*上杠杆)", risk.evidence.quote
                )
            ):
                raise ValueError(
                    "NO_LEVERAGE SUPPORT contradicts explicit leverage endorsement"
                )
        return self
