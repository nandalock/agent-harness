"""Plugin group configuration and enablement."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, StrictBool


class Group(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    disabled: StrictBool = False


def is_group_disabled(group: str | None, groups: Mapping[str, Group]) -> bool:
    settings = groups.get(group) if group is not None else None
    return settings is not None and settings.disabled
