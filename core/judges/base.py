"""Versioned closed-set judgement contracts."""
from typing import Literal, Protocol
from pydantic import BaseModel, Field

DirectionLabel = Literal['BULLISH', 'BEARISH', 'NEUTRAL', 'UNCLEAR', 'NOT_APPLICABLE']
CoordinationLabel = Literal['ORGANIC', 'SUSPECTED_COORDINATED', 'UNCERTAIN', 'NO_COORDINATION_EVIDENCE', 'INSUFFICIENT_EVIDENCE']


class JudgeContext(BaseModel):
    stock_code: str
    stock_name: str
    platform: str


class CoordinationJudgement(BaseModel):
    label: CoordinationLabel
    probabilities: dict[str, float]
    jev_probability: float = Field(ge=0, le=1)
    coordination_score: float = Field(ge=0, le=1)
    score_status: str = 'EXPERIMENTAL_HEURISTIC_NOT_CALIBRATED_PROBABILITY'
    available_weight: float
    components: dict[str, float | None]
    reason_flags: list[str]
    audit: dict


class DirectionJudgement(BaseModel):
    label: DirectionLabel
    probabilities: dict[str, float]
    explicit_probability: float = Field(ge=0, le=1)
    horizon: Literal['INTRADAY', '1D', '1W', 'MEDIUM', 'LONG', 'UNSPECIFIED']
    horizon_probabilities: dict[str, float]
    relevant_probability: float = Field(ge=0, le=1)
    directional_score: float = Field(ge=-1, le=1)
    audit: dict


class SemanticJudge(Protocol):
    async def judge_direction(self, unit: dict, context: JudgeContext) -> DirectionJudgement: ...
    async def judge_coordination(self, comment: dict, features: dict) -> CoordinationJudgement: ...
