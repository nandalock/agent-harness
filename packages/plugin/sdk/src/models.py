"""Validated public data shared by independently installed plugin packages."""
from typing import Annotated, Literal, Self

from packaging.version import Version
from pydantic import BaseModel, ConfigDict, Field, JsonValue as JsonValue, StrictBool, StrictInt, StrictStr, field_validator, model_validator

SDK_API_VERSION = 1
PLUGIN_ENTRY_POINT_GROUP = "agent_platform.plugins"

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


class ServiceRef(SdkModel):
    """A service identity and its exact behavioral API major version."""

    name: Identifier
    api_version: PositiveInteger = 1

    def __str__(self) -> str:
        return f"{self.name}.v{self.api_version}"


class ServiceRequirement(SdkModel):
    """An optional dependency may be absent, but never silently incompatible."""

    service: ServiceRef
    optional: StrictBool = False


class PluginSpec(SdkModel):
    """Implementation metadata, separate from a YAML plugin instance's id.

    Package version, SDK API version and service API version are independent.
    There is one provider per ServiceRef in a runtime scope.
    """

    name: Identifier
    version: StrictStr
    sdk_api_version: PositiveInteger = SDK_API_VERSION
    requires: tuple[ServiceRequirement, ...] = ()
    provides: tuple[ServiceRef, ...] = ()

    @field_validator("version")
    @classmethod
    def valid_version(cls, value: str) -> str:
        return str(Version(value))

    @model_validator(mode="after")
    def unique_services(self) -> Self:
        required = [item.service for item in self.requires]
        if len(required) != len(set(required)):
            raise ValueError("requires contains duplicate service references")
        if len(self.provides) != len(set(self.provides)):
            raise ValueError("provides contains duplicate service references")
        return self


class PluginEntry(SdkModel):
    """A package entry-point instance, not a tool declaration.

    One instance may provide services and zero or many tools. Multiple entries
    may instantiate the same plugin package with independent config/lifetimes.
    Config is validated again by its plugin.
    """

    id: Identifier
    name: Identifier
    disabled: StrictBool = False
    config: JsonObject = Field(default_factory=dict)


class PluginConfiguration(SdkModel):
    """The public YAML/JSON document shape; parsing and loading belong to runtime."""

    version: Literal[1] = 1
    plugins: tuple[PluginEntry, ...] = ()

    @field_validator("version", mode="before")
    @classmethod
    def exact_document_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("configuration version must be integer 1")
        return value

    @model_validator(mode="after")
    def unique_instances(self) -> Self:
        ids = [entry.id for entry in self.plugins]
        if len(ids) != len(set(ids)):
            raise ValueError("plugin instance ids must be unique, including disabled entries")
        return self


class ExecutionScope(SdkModel):
    """Host-issued identity; a routing scope is not an authorization decision."""

    tenant_id: PositiveInteger
    agent_key: NonEmptyString
    session_id: NonEmptyString | None = None
