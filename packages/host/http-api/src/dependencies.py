"""HTTP adapters borrow services from the plugin instance that owns the app."""
from fastapi import Request


def agent_entry(request: Request):
    return request.app.state.agent_entry


def chat_service(request: Request):
    return request.app.state.chat


def approval_inbox(request: Request):
    return request.app.state.approval


def agent_config(request: Request):
    return request.app.state.agent_config
