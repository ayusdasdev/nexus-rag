from app.core import security
from app.repositories import auth_repository
from app.repositories.auth_repository import (
    EmailAlreadyExists,
    TenantRecord,
    UserRecord,
)


class EmailAlreadyRegistered(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class AuthService:
    async def signup(
        self, tenant_name: str, email: str, password: str
    ) -> tuple[TenantRecord, UserRecord, str]:
        if await auth_repository.get_user_by_email(email) is not None:
            raise EmailAlreadyRegistered

        password_hash = security.hash_password(password)
        try:
            tenant, user = await auth_repository.create_tenant_and_admin_user(
                tenant_name, email, password_hash
            )
        except EmailAlreadyExists as exc:
            raise EmailAlreadyRegistered from exc

        token = security.create_access_token(user.id, user.tenant_id, user.role)
        return tenant, user, token

    async def login(self, email: str, password: str) -> tuple[UserRecord, str]:
        user = await auth_repository.get_user_by_email(email)
        # Always run verify_password, even for an unknown email (against a
        # fixed dummy hash), so an unknown-email response takes the same
        # time as a wrong-password response - otherwise bcrypt's cost makes
        # the two cases distinguishable by timing alone, re-enabling email
        # enumeration despite the identical error message.
        hash_to_check = user.password_hash if user is not None else security.DUMMY_HASH
        password_ok = security.verify_password(password, hash_to_check)
        if user is None or not password_ok:
            raise InvalidCredentials

        token = security.create_access_token(user.id, user.tenant_id, user.role)
        return user, token


def get_auth_service() -> AuthService:
    return AuthService()
