"""FAQ service key."""
from agent_platform_plugin_sdk import ServiceKey, ServiceRef

from .service import FAQService

FAQ: ServiceKey[FAQService] = ServiceKey(ServiceRef(name="faq", api_version=1))
