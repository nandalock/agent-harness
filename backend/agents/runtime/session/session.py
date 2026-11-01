"""Compatibility import; implementation lives in agent_platform_session.session."""
import sys
from importlib import import_module
sys.modules[__name__] = import_module("agent_platform_session.session")
