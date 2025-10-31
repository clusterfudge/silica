"""Authentication middleware using heare-auth."""

import logging
from typing import Dict

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings

logger = logging.getLogger(__name__)

security = HTTPBearer()


async def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Dict:
    """
    Verify authentication token with heare-auth service.

    Args:
        credentials: Bearer token from Authorization header

    Returns:
        User information from auth service

    Raises:
        HTTPException: If token is invalid or auth service is unavailable
    """
    settings = Settings()
    api_key = credentials.credentials

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.heare_auth_url}/verify",
                json={"api_key": api_key},
            )

            if response.status_code == 200:
                user_info = response.json()
                logger.debug(
                    f"Token verified for user: {user_info.get('user_id', 'unknown')}"
                )
                return user_info
            elif response.status_code == 401:
                logger.warning("Invalid token presented")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            else:
                logger.error(
                    f"Auth service returned {response.status_code}: {response.text}"
                )
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Authentication service unavailable",
                )

    except httpx.TimeoutException:
        logger.error("Auth service timeout")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service timeout",
        )
    except httpx.RequestError as e:
        logger.error(f"Auth service request error: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service unavailable",
        )
