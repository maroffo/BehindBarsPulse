# ABOUTME: OIDC token verification for Cloud Scheduler authentication.
# ABOUTME: Validates Google OIDC tokens in Authorization header for API endpoints.

from typing import Annotated

import structlog
from fastapi import Depends, HTTPException, Request

from behind_bars_pulse.config import get_settings

log = structlog.get_logger()


async def verify_oidc_token(request: Request) -> str | None:
    """Verify OIDC token from Cloud Scheduler.

    Returns the verified email/subject if valid, None if no authentication required.

    Raises:
        HTTPException: If token is present but invalid.
    """
    settings = get_settings()

    # Skip verification in development (no audience configured)
    if not settings.scheduler_audience:
        log.debug("oidc_verification_skipped", reason="no_audience_configured")
        return None

    # Get authorization header
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        log.warning("oidc_missing_authorization")
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not auth_header.startswith("Bearer "):
        log.warning("oidc_invalid_auth_format")
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = auth_header[7:]  # Remove "Bearer " prefix

    try:
        # Import google-auth library for token verification
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        # Verify the token with Google's public keys
        claims = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=settings.scheduler_audience,
        )

        # Verify issuer
        issuer = claims.get("iss")
        if issuer not in ("https://accounts.google.com", "accounts.google.com"):
            log.warning("oidc_invalid_issuer", issuer=issuer)
            raise HTTPException(status_code=401, detail="Invalid token issuer")

        email = claims.get("email", claims.get("sub"))
        log.info("oidc_verified", email=email)
        return email

    except ImportError as e:
        log.error("google_auth_not_installed")
        raise HTTPException(
            status_code=500, detail="OIDC verification not available (google-auth not installed)"
        ) from e
    except ValueError as e:
        log.warning("oidc_invalid_token", error=str(e))
        raise HTTPException(status_code=401, detail="Invalid OIDC token") from e


# Type alias for dependency injection
OIDCVerified = Annotated[str | None, Depends(verify_oidc_token)]
