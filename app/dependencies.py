from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Role, User


DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, db: DbSession) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    user = await db.get(User, int(user_id))
    if user is None or not user.is_active:
        request.session.clear()
        return None
    return user


CurrentUser = Annotated[User | None, Depends(get_current_user)]


async def require_user(current_user: CurrentUser) -> User:
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please log in to continue.")
    return current_user


LoggedInUser = Annotated[User, Depends(require_user)]


async def require_admin(current_user: LoggedInUser) -> User:
    if current_user.role != Role.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access is required.")
    return current_user


AdminUser = Annotated[User, Depends(require_admin)]
