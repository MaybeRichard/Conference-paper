"""Common internal schema types; upstream metadata uses separate validation."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Identifier = Annotated[str, StringConstraints(strict=True, pattern=r"^[A-Za-z0-9_-]+$")]
NonEmptyText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Version = Annotated[int, Field(strict=True, ge=1)]


class Contract(BaseModel):
    """Frozen top-level fields only; nested dicts still require rehash on commit."""
    model_config = ConfigDict(
        extra="forbid", frozen=True, validate_default=True,
        allow_inf_nan=False, hide_input_in_errors=True,
    )


class ArtifactRef(Contract):
    artifact_id: Identifier
    version: Version
    sha256: Sha256
