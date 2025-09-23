# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Job(BaseModel):
    jobId: str
    status: str


class JobStatus(BaseModel):
    jobId: str
    status: str
    progress: int = Field(ge=0, le=100)
    totals: dict[str, int] | None = None


class AllocationRunRequest(BaseModel):
    priority_mode: Literal["balanced", "fastest"] = Field(default="balanced")
    guarantee_assignment: bool = Field(default=False)

    @field_validator("priority_mode")
    @classmethod
    def validate_priority_mode(cls, v: str) -> str:
        if v not in ("balanced", "fastest"):
            raise ValueError("priority_mode must be 'balanced' or 'fastest'")
        return v
