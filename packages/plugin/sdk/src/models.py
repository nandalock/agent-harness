"""Validated public data shared by independently installed plugin packages."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue as JsonValue, StrictInt, StrictStr

Identifier = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=128)]
NonEmptyString = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]
PositiveInteger = Annotated[StrictInt, Field(gt=0)]
JsonObject = dict[str, JsonValue]


class SdkModel(BaseModel):
    """Reject unknown fields and non-finite JSON; freezing is shallow.

    Runtimes must snapshot mutable JSON fields before crossing an async boundary.
    These are process API models, not the durable Session event format.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True)


class ExecutionScope(SdkModel):
    """Host-issued identity; a routing scope is not an authorization decision."""

    tenant_id: PositiveInteger
    agent_key: NonEmptyString
    session_id: NonEmptyString | None = None
