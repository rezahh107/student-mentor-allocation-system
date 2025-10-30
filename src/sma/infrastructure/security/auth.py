# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Annotated, Sequence

from fastapi import Depends, HTTPException, Request, status


class User:
    def __init__(self, sub: str = "dev-user", roles: Sequence[str] | None = None):
        self.sub = sub
        self.roles = set(roles or []) # یا فقط یک مجموعه خالی


async def get_current_user(request: Request) -> User:
    # NOTE: For Phase 1 design, parse roles from header for demonstration.
    # Replace with proper JWT validation in Phase 2.
    # --- حذف چک امنیتی ---
    # auth = request.headers.get("Authorization", "")
    # if not auth.startswith("Bearer "):
    #     raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    # roles = request.headers.get("X-Roles", "").split(",") if request.headers.get("X-Roles") else []
    # --- پایان حذف ---
    # فقط یک کاربر ساختگی/پیش‌فرض برمی‌گرداند
    return User(sub="dev-user", roles=["ADMIN"]) # یا هر نقش دیگر


def require_roles(*required: str):
    # تابع داخلی که دیگر چیزی چک نمی‌کند
    async def _checker(user: Annotated[User, Depends(get_current_user)]):
        # --- حذف بررسی نقش ---
        # if not set(required).issubset(user.roles):
        #     raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        # --- پایان حذف ---
        # فقط کاربر را برمی‌گرداند
        return user

    return _checker
