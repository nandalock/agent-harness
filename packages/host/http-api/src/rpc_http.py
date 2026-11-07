"""Translate controller RpcError to the legacy REST HTTP error shape."""
from fastapi import HTTPException

from agent_platform_rpc_gateway import RpcError


def http_error(exc: RpcError) -> HTTPException:
    code = exc.code
    if code.endswith("/not-found"):
        status = 404
    elif code.endswith("/exists") or code.endswith("/conflict") or code.endswith("/name-conflict"):
        status = 409
    elif code.endswith("/unavailable"):
        status = 503
    elif code.endswith("/cancelled"):
        status = 499
    else:
        status = 400
    return HTTPException(status, exc.message)
