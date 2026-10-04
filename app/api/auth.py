from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, get_current_user
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserProfile
from app.services.auth_service import (
    AuthService,
    EmailAlreadyRegistered,
    InvalidCredentials,
    get_auth_service,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED
)
async def signup(
    body: SignupRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008 - FastAPI DI pattern
) -> TokenResponse:
    """Create a new tenant and its first (admin) user, and log them in."""
    try:
        _tenant, user, token = await service.signup(
            body.tenant_name, body.email, body.password
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from exc

    return TokenResponse(
        access_token=token,
        user=UserProfile(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
            created_at=user.created_at,
        ),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    service: AuthService = Depends(get_auth_service),  # noqa: B008 - FastAPI DI pattern
) -> TokenResponse:
    """Log in with email and password."""
    try:
        user, token = await service.login(body.email, body.password)
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        ) from exc

    return TokenResponse(
        access_token=token,
        user=UserProfile(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
            created_at=user.created_at,
        ),
    )


@router.get("/me", response_model=UserProfile, summary="Get the current user's profile")
async def me(
    current_user: CurrentUser = Depends(get_current_user),  # noqa: B008 - FastAPI DI pattern
) -> UserProfile:
    """Return the authenticated user's own profile, including their tenant_id."""
    return UserProfile(
        id=current_user.id,
        tenant_id=current_user.tenant_id,
        email=current_user.email,
        role=current_user.role,
        created_at=current_user.created_at,
    )
