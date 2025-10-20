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
    fairness_strategy: Literal["none", "deterministic_jitter", "bucket_round_robin"] = Field(default="none")

    @field_validator("priority_mode", mode="before")
    @classmethod
    def validate_priority_mode(cls, v: str) -> str:
        if v is None:
            return "balanced"
        value = str(v).strip().lower()
        if value == "normal":
            return "balanced"
        if value not in ("balanced", "fastest"):
            raise ValueError("priority_mode must be 'balanced' or 'fastest'")
        return value

    @field_validator("fairness_strategy", mode="before")
    @classmethod
    def normalize_fairness_strategy(cls, v: str) -> str:
        if v is None:
            return "none"
        value = str(v).strip().lower()
        if not value:
            return "none"
        allowed = {"none", "deterministic_jitter", "bucket_round_robin"}
        if value not in allowed:
            raise ValueError("fairness_strategy must be one of: none, deterministic_jitter, bucket_round_robin")
        return value
