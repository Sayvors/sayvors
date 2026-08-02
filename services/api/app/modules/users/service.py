from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...security import create_access_token, hash_password, verify_password
from ..users.models import User
from ..users.schemas import LoginRequest, SignupRequest


async def create_user(body: SignupRequest, db: AsyncSession) -> str:
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ValueError("Email already registered")

    user = User(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password_hash=hash_password(body.password),
        business_type=body.business_type,
        referral=body.referral,
        newsletter=body.newsletter,
    )
    db.add(user)
    await db.commit()
    return create_access_token(user.id)


async def authenticate_user(body: LoginRequest, db: AsyncSession) -> str:
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise ValueError("Invalid email or password")
    return create_access_token(user.id)
