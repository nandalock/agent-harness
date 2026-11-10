"""Profile document models owned by the minidsh loader."""
from typing import Annotated, Literal, Self

from pydantic import Field, StrictBool, StrictStr, field_validator, model_validator

from agent_platform_plugin_sdk import JsonObject, SdkModel
from agent_platform_plugin_sdk.models import Identifier, NonEmptyString


class PluginEntry(SdkModel):
    """One configured instance of a Cordis plugin.

    One instance may provide services and zero or many tools. Multiple entries
    may instantiate the same plugin package with independent config/lifetimes.
    Config is validated again by its plugin.
    """

    id: Identifier
    name: Identifier
    use: Annotated[StrictStr, Field(pattern=r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")] | None = None
    group: Identifier | None = None
    disabled: StrictBool = False
    config: JsonObject = Field(default_factory=dict)


class PluginGroup(SdkModel):
    disabled: StrictBool = False


class PluginPatch(SdkModel):
    id: Identifier
    disabled: StrictBool | None = None
    config: JsonObject = Field(default_factory=dict)


class PluginConfiguration(SdkModel):
    """The public YAML/JSON document shape; parsing and loading belong to runtime."""

    version: Literal[1] = 1
    plugins: tuple[PluginEntry, ...] = ()
    includes: tuple[NonEmptyString, ...] = ()
    groups: dict[Identifier, PluginGroup] = Field(default_factory=dict)
    patches: tuple[PluginPatch, ...] = ()

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
