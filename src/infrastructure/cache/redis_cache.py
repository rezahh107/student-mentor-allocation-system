# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Optional

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover - import guard for design phase
    redis = None  # type: ignore


CAPACITY_KEY = "cap:mentor:{id}"
SEQ_KEY = "seq:{year}:{gender}"
IDEMPOTENCY_KEY = "idem:alloc:{job}:{nid}"


LUA_RESERVE = """
local key = KEYS[1]
local field = ARGV[1]
local delta = tonumber(ARGV[2])
local capacity = tonumber(redis.call('HGET', key, 'capacity')) or 0
local load = tonumber(redis.call('HGET', key, 'current_load')) or 0
if (load + delta) <= capacity then
  redis.call('HINCRBY', key, 'current_load', delta)
  return 1
else
  return 0
end
"""


class RedisCache:
    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        if redis is None:
            raise RuntimeError("redis-py not installed in this environment")
        self.client = redis.Redis.from_url(url, decode_responses=True)
        self.reserve_script = self.client.register_script(LUA_RESERVE)

    def get_capacity(self, mentor_id: int) -> dict:
        key = CAPACITY_KEY.format(id=mentor_id)
        h = self.client.hgetall(key)
        return {"capacity": int(h.get("capacity", 0)), "current_load": int(h.get("current_load", 0))}

    def set_capacity(self, mentor_id: int, *, capacity: int, current_load: int) -> None:
        key = CAPACITY_KEY.format(id=mentor_id)
        self.client.hset(key, mapping={"capacity": capacity, "current_load": current_load})

    def reserve_capacity(self, mentor_id: int, delta: int = 1) -> bool:
        key = CAPACITY_KEY.format(id=mentor_id)
        return bool(self.reserve_script(keys=[key], args=["current_load", str(delta)]))

    def next_seq(self, year_two: str, gender_code: str) -> int:
        return int(self.client.incr(SEQ_KEY.format(year=year_two, gender=gender_code)))

    def acquire_idempotency(self, job_id: str, national_id: str, ttl_sec: int = 86400) -> bool:
        key = IDEMPOTENCY_KEY.format(job=job_id, nid=national_id)
        return bool(self.client.set(key, "1", nx=True, ex=ttl_sec))

