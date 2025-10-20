# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Annotated, Sequence

from fastapi import Depends, HTTPException, Request, status


class User:
    def __init__(self, sub: str, roles: Sequence[str]):
        self.sub = sub
        self.roles = set(roles)


async def get_current_user(request: Request) -> User:
    # NOTE: For Phase 1 design, parse roles from header for demonstration.
    # Replace with proper JWT validation in Phase 2.
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    roles = request.headers.get("X-Roles", "").split(",") if request.headers.get("X-Roles") else []
    return User(sub="demo", roles=roles)


def require_roles(*required: str):
    async def _checker(user: Annotated[User, Depends(get_current_user)]):
        if not set(required).issubset(user.roles):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _checker

