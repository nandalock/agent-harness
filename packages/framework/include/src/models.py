"""Configuration models shared by Cordis hosts."""
from typing import Annotated, Literal, Self

from minidsh_cordis_plugin_group import Group
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool, StrictStr, field_validator, model_validator

Identifier = Annotated[StrictStr, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=128)]
NonEmptyString = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class _ConfigurationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False, validate_default=True)


class EntryOptions(_ConfigurationModel):
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
    config: dict[str, JsonValue] = Field(default_factory=dict)


class PatchOptions(_ConfigurationModel):
    id: Identifier
    disabled: StrictBool | None = None
    config: dict[str, JsonValue] = Field(default_factory=dict)


class PluginConfiguration(_ConfigurationModel):
    """The public YAML/JSON document shape; parsing and loading belong to runtime."""

    version: Literal[1] = 1
    plugins: tuple[EntryOptions, ...] = ()
    includes: tuple[NonEmptyString, ...] = ()
    groups: dict[Identifier, Group] = Field(default_factory=dict)
    patches: tuple[PatchOptions, ...] = ()

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
