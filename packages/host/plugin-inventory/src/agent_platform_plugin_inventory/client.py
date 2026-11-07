"""Browser entry points bundled with started Python plugins."""
import logging
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Annotated

from pydantic import Field, ValidationError

from agent_platform_plugin_sdk import SdkModel

logger = logging.getLogger(__name__)


class ClientModule(SdkModel):
    id: Annotated[str, Field(pattern=r"^(?:@[a-z0-9._-]+/)?[a-z0-9._-]+$")]
    rev: Annotated[str, Field(pattern=r"^[a-f0-9]{16}$")]
    inject: tuple[str, ...] = ()


def discover_clients(packages: tuple[str, ...]) -> dict[str, tuple[ClientModule, Traversable]]:
    modules: dict[str, tuple[ClientModule, Traversable]] = {}
    for package in packages:
        try:
            web = files(package).joinpath("web")
            entry = ClientModule.model_validate_json(web.joinpath("client.json").read_bytes())
            script = web.joinpath("client.js")
            if not script.is_file():
                logger.warning("Client bundle missing for %s", package)
                continue
        except FileNotFoundError:
            # An editable or backend-only installation can omit browser assets.
            continue
        except (ImportError, OSError, ValidationError) as exc:
            logger.warning("Invalid client bundle for %s: %s", package, exc)
            continue
        if entry.id in modules:
            raise ValueError(f"duplicate installed browser plugin id: {entry.id}")
        modules[entry.id] = entry, script
    return modules
