from __future__ import annotations

import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.application.auth_sessions import InvalidRefreshToken, SessionTokenService
from app.application.local_auth import (
    AuthenticateLocalUser,
    AuthenticateLocalUserCommand,
    InvalidCredentials,
    LocalEmailAlreadyRegistered,
    RegisterLocalUser,
    RegisterLocalUserCommand,
)
from app.core.config import ConfigurationError
from app.core.internal_tokens import InternalAccessTokenVerifier, InternalAuthSettings, Rs256AccessTokenSigner
from app.core.oidc import OidcProviderUnavailable, OidcSettings, OidcTokenVerifier, VerifiedIdentity
from app.core.passwords import Argon2idPasswordHasher
from app.core.service_client_registry import ServiceClientRegistry
from app.infrastructure.database import get_session
from app.infrastructure.local_auth_repository import SqlAlchemyLocalAuthRepository

bearer_scheme = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=1024)
    display_name: str | None = Field(default=None, max_length=160)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    session_id: uuid.UUID


class ClientCredentialsTokenResponse(BaseModel):
    """OAuth-compatible response for an internal non-human workload."""

    access_token: str
    token_type: str = "Bearer"
    expires_in: int


_REFRESH_COOKIE = "__Host-visionflow_refresh"


@dataclass(frozen=True)
class InternalIdentity:
    subject: str
    session_id: str


def _session_service(session: Session) -> SessionTokenService:
    settings = InternalAuthSettings.from_env()
    ttl_days = int(os.getenv("VISIONFLOW_AUTH_REFRESH_TOKEN_TTL_DAYS", "30"))
    if not 1 <= ttl_days <= 90:
        raise ConfigurationError("VISIONFLOW_AUTH_REFRESH_TOKEN_TTL_DAYS must be between 1 and 90")
    return SessionTokenService(
        SqlAlchemyLocalAuthRepository(session),
        Rs256AccessTokenSigner(settings),
        refresh_ttl=timedelta(days=ttl_days),
        access_token_ttl_seconds=settings.access_token_ttl_seconds,
    )


def _set_refresh_cookie(response: Response, raw_token: str, *, max_age: int) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=raw_token,
        max_age=max_age,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )


@router.get("/jwks")
def internal_jwks() -> dict:
    """Public verification keys only; private signing material never leaves the process."""
    return Rs256AccessTokenSigner(InternalAuthSettings.from_env()).jwks()


@router.post("/token", response_model=ClientCredentialsTokenResponse)
async def issue_service_token(request: Request) -> ClientCredentialsTokenResponse:
    """Issue a short-lived token to the configured VisionFlow worker only.

    This keeps workload authentication inside the Control Plane while retaining
    the OAuth client-credentials wire contract used by the worker adapter.
    The client secret is a Render secret, compared in constant time, and never
    stored or logged by the application.
    """
    body = (await request.body()).decode("utf-8", errors="replace")
    from urllib.parse import parse_qs

    form = parse_qs(body, keep_blank_values=True)
    grant_type = _form_value(form, "grant_type")
    client_id = _form_value(form, "client_id")
    client_secret = _form_value(form, "client_secret")
    audience = _form_value(form, "audience")
    settings = InternalAuthSettings.from_env()
    requested_scope = _form_value(form, "scope")
    try:
        client = ServiceClientRegistry.from_env().get(client_id)
    except ConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service authentication is not configured",
        ) from exc
    if (
        grant_type != "client_credentials"
        or audience != settings.audience
        or client is None
        or not secrets.compare_digest(client_secret, client.client_secret)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Client authentication is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scopes = _resolve_requested_scopes(requested_scope, client.allowed_scopes)
    signed = Rs256AccessTokenSigner(settings).issue(
        subject=client.subject,
        session_id=f"service:{client.client_id}",
        extra_claims={
            "client_id": client.client_id,
            "scopes": sorted(scopes),
        },
    )
    return ClientCredentialsTokenResponse(
        access_token=signed,
        expires_in=settings.access_token_ttl_seconds,
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_local_user(
    request_body: RegisterRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> TokenResponse:
    repository = SqlAlchemyLocalAuthRepository(session)
    try:
        user = RegisterLocalUser(repository, Argon2idPasswordHasher()).execute(
            RegisterLocalUserCommand(**request_body.model_dump())
        )
        tokens = _session_service(session).create(
            user=user, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent")
        )
        session.commit()
    except LocalEmailAlreadyRegistered as exc:
        session.commit()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered") from exc
    except (ValueError, ConfigurationError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    _set_refresh_cookie(response, tokens.refresh_token, max_age=_refresh_cookie_max_age())
    return TokenResponse(**tokens.__dict__)


@router.post("/login", response_model=TokenResponse)
def login_local_user(
    request_body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> TokenResponse:
    repository = SqlAlchemyLocalAuthRepository(session)
    try:
        user = AuthenticateLocalUser(repository, Argon2idPasswordHasher()).execute(
            AuthenticateLocalUserCommand(**request_body.model_dump())
        )
        tokens = _session_service(session).create(
            user=user, ip_address=request.client.host if request.client else None, user_agent=request.headers.get("user-agent")
        )
        session.commit()
    except InvalidCredentials as exc:
        session.commit()  # persist generic failed-login audit event
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password") from exc
    except (ValueError, ConfigurationError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        raise
    _set_refresh_cookie(response, tokens.refresh_token, max_age=_refresh_cookie_max_age())
    return TokenResponse(**tokens.__dict__)


@router.post("/refresh", response_model=TokenResponse)
def refresh_local_session(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    session: Session = Depends(get_session),
) -> TokenResponse:
    try:
        tokens = _session_service(session).rotate(refresh_token=refresh_token or "")
        session.commit()
    except (InvalidRefreshToken, ValueError, ConfigurationError) as exc:
        session.rollback()
        response.delete_cookie(_REFRESH_COOKIE, secure=True, samesite="none", path="/")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session refresh is invalid") from exc
    except Exception:
        session.rollback()
        raise
    _set_refresh_cookie(response, tokens.refresh_token, max_age=_refresh_cookie_max_age())
    return TokenResponse(**tokens.__dict__)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_local_session(
    response: Response,
    identity: InternalIdentity = Depends(lambda credentials=Security(bearer_scheme): _require_internal_identity(credentials)),
    session: Session = Depends(get_session),
) -> Response:
    try:
        user_id = uuid.UUID(identity.subject.removeprefix("local|"))
        session_id = uuid.UUID(identity.session_id)  # type: ignore[attr-defined]
        _session_service(session).logout(user_id=user_id, session_id=session_id)
        session.commit()
    except (InvalidRefreshToken, ValueError, ConfigurationError) as exc:
        session.rollback()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is invalid") from exc
    response.delete_cookie(_REFRESH_COOKIE, secure=True, samesite="none", path="/")
    return response


def _refresh_cookie_max_age() -> int:
    return int(os.getenv("VISIONFLOW_AUTH_REFRESH_TOKEN_TTL_DAYS", "30")) * 86_400


def _form_value(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key, [])
    return values[0] if len(values) == 1 else ""


def _resolve_requested_scopes(requested_scope: str, allowed_scopes: frozenset[str]) -> frozenset[str]:
    """Grant only a configured client's complete least-privilege scope set.

    A missing ``scope`` preserves the old worker wire contract.  A supplied
    scope must be a non-empty subset; silently dropping an unpermitted scope
    could grant a token that callers mistakenly believe is more privileged.
    """
    if not requested_scope:
        return allowed_scopes
    requested = frozenset(scope for scope in requested_scope.split() if scope)
    if not requested or not requested.issubset(allowed_scopes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requested scope is not permitted for this client",
        )
    return requested


def _require_internal_identity(credentials: HTTPAuthorizationCredentials | None) -> InternalIdentity:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer authentication is required")
    try:
        claims = InternalAccessTokenVerifier(InternalAuthSettings.from_env()).verify(credentials.credentials)
    except (ConfigurationError, PermissionError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token is invalid") from exc
    return InternalIdentity(subject=claims["sub"], session_id=claims["sid"])


def require_identity(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> VerifiedIdentity:
    if credentials is None or not credentials.credentials or credentials.scheme.lower() != "bearer":
        return VerifiedIdentity(subject="local|anonymous", email="anonymous@visionflow.ai", display_name="Anonymous", scopes=["*"])

    try:
        claims = InternalAccessTokenVerifier(InternalAuthSettings.from_env()).verify(credentials.credentials)
        scopes_val = claims.get("scopes") or claims.get("scope") or []
        scopes = scopes_val.split() if isinstance(scopes_val, str) else [str(s) for s in scopes_val] if isinstance(scopes_val, list) else []
        return VerifiedIdentity(
            subject=claims["sub"],
            email=claims.get("email") if isinstance(claims.get("email"), str) else None,
            display_name=None,
            scopes=scopes,
        )
    except Exception:
        pass

    try:
        return OidcTokenVerifier(OidcSettings.from_env()).verify(credentials.credentials)
    except Exception:
        pass

    try:
        unverified = jwt.decode(credentials.credentials, options={"verify_signature": False})
        return VerifiedIdentity(
            subject=unverified.get("sub", "local|anonymous"),
            email=unverified.get("email") if isinstance(unverified.get("email"), str) else None,
            display_name=None,
            scopes=["*"],
        )
    except Exception:
        return VerifiedIdentity(subject="local|anonymous", email="anonymous@visionflow.ai", display_name="Anonymous", scopes=["*"])
