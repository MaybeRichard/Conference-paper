"""M1 structural contracts; citation existence is not scientific support."""
from datetime import date
import re
from typing import Literal, Self

from pydantic import JsonValue, field_validator, model_validator

from research_agent.core.serialization import canonical_bytes
from research_agent.schemas.base import Contract, Identifier, NonEmptyText

EpistemicStatus = Literal["FACT", "SYNTHESIS", "HYPOTHESIS", "TRANSFER", "RISK"]


class Claim(Contract):
    """Minimal citation-bearing claim, extended by later evidence-reading stages."""
    statement: NonEmptyText
    epistemic_status: EpistemicStatus
    evidence_ids: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_sources(self) -> Self:
        if self.epistemic_status == "FACT" and not self.evidence_ids:
            raise ValueError("FACT requires at least one evidence reference")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Evidence references must be unique")
        return self


class ResearchBrief(Contract):
    topic: NonEmptyText
    domain: Identifier
    target_venue: NonEmptyText
    scope: dict[str, JsonValue]
    start_date: date
    end_date: date
    snapshot_id: Identifier
    creation_basis: NonEmptyText

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def validate_absolute_date(cls, value: object) -> date:
        if type(value) is date:
            return value
        if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError("Dates must be date objects or YYYY-MM-DD strings")
        return date.fromisoformat(value)

    @field_validator("scope")
    @classmethod
    def validate_scope_json(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        canonical_bytes(value)
        return value

    @model_validator(mode="after")
    def validate_date_order(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self
