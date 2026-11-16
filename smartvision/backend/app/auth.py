"""
SmartVision - Authentication & Access Control
Provides lightweight API Key and Bearer token verification for REST and WebSocket endpoints.
Configurable via settings.AUTH_ENABLED with safe defaults for local development.
"""

from typing import Optional
from fastapi import Header, HTTPException, Query, Security, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

# Optional HTTP Bearer security scheme
bearer_scheme = HTTPBearer(auto_error=False)


def check_key(provided_key: Optional[str]) -> bool:
    """Verifies provided key against configured settings.API_KEY."""
    if not settings.AUTH_ENABLED:
        return True
    if not provided_key:
        return False
    return provided_key.strip() == settings.API_KEY.strip()


async def verify_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    token: Optional[str] = Query(None, alias="token"),
    api_key_query: Optional[str] = Query(None, alias="api_key"),
) -> bool:
    """
    FastAPI dependency for authenticating REST requests.
    Accepts API key via X-API-Key header, Authorization Bearer token, or query parameters.
    """
    if not settings.AUTH_ENABLED:
        return True

    # Check X-API-Key header
    if x_api_key and check_key(x_api_key):
        return True

    # Check Bearer token
    if bearer and bearer.credentials and check_key(bearer.credentials):
        return True

    # Check query params (useful for browser img/video tags)
    if token and check_key(token):
        return True
    if api_key_query and check_key(api_key_query):
        return True

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing API key. Provide X-API-Key header or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_websocket(websocket: WebSocket) -> bool:
    """
    Verifies authentication for inbound WebSocket connections.
    Inspects query parameters and headers.
    """
    if not settings.AUTH_ENABLED:
        return True

    # Check query params (e.g. ws://.../ws/client?token=secret)
    token = websocket.query_params.get("token") or websocket.query_params.get("api_key")
    if token and check_key(token):
        return True

    # Check headers
    header_key = websocket.headers.get("x-api-key")
    if header_key and check_key(header_key):
        return True

    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        bearer_val = auth_header[7:].strip()
        if check_key(bearer_val):
            return True

    return False
