from fastapi import APIRouter

from ..auth import LoginRequest, LoginResponse
from ..auth import login

router = APIRouter(prefix="/api/auth", tags=["Auth"])


@router.post("/login")
def login_route(body: LoginRequest) -> LoginResponse:
    ok, token, error = login(body.username, body.password)
    if ok:
        return LoginResponse(ok=True, token=token)
    return LoginResponse(ok=False, error=error)
