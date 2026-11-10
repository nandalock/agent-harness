"""FAQ service key."""
from agent_platform_plugin_sdk import ServiceKey

from .service import FAQService

FAQ: ServiceKey[FAQService] = ServiceKey("faq")
