# -*- coding: utf-8 -*-
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Dict, List, Sequence, Tuple

from src.domain.mentor.entities import Mentor
from src.shared.counter_rules import stable_counter_hash


class FairnessStrategy(StrEnum):
    NONE = "none"
    DETERMINISTIC_JITTER = "deterministic_jitter"
    BUCKET_ROUND_ROBIN = "bucket_round_robin"


@dataclass(slots=True)
class FairnessConfig:
    strategy: FairnessStrategy = FairnessStrategy.NONE
    bucket_size: float = 0.1


class FairnessPlanner:
    """Deterministic ordering strategies for allocation candidates."""

    def __init__(self, config: FairnessConfig | None = None) -> None:
        self._config = config or FairnessConfig()
        self._round_robin_state: Dict[str, int] = {}

    def rank(
        self,
        items: Sequence[Tuple[Mentor, List[object]]],
        *,
        academic_year: str | None,
    ) -> List[Tuple[Mentor, List[object]]]:
        if len(items) <= 1 or self._config.strategy is FairnessStrategy.NONE:
            return list(items)
        key = academic_year or "default"
        if self._config.strategy is FairnessStrategy.DETERMINISTIC_JITTER:
            return self._with_deterministic_jitter(items, key)
        if self._config.strategy is FairnessStrategy.BUCKET_ROUND_ROBIN:
            return self._with_bucket_round_robin(items, key)
        return list(items)

    def _with_deterministic_jitter(
        self,
        items: Sequence[Tuple[Mentor, List[object]]],
        key: str,
    ) -> List[Tuple[Mentor, List[object]]]:
        jittered = []
        for mentor, trace in items:
            seed = f"{key}:{mentor.mentor_id}"
            jitter = (stable_counter_hash(seed) % 10_000) / 1_000_000.0
            jittered.append((mentor, trace, jitter))
        jittered.sort(
            key=lambda entry: (
                entry[0].occupancy_ratio + entry[2],
                entry[0].current_load,
                entry[0].mentor_id,
            )
        )
        return [(mentor, trace) for mentor, trace, _ in jittered]

    def _with_bucket_round_robin(
        self,
        items: Sequence[Tuple[Mentor, List[object]]],
        key: str,
    ) -> List[Tuple[Mentor, List[object]]]:
        bucket_size = max(0.01, min(1.0, self._config.bucket_size))
        buckets: Dict[int, List[Tuple[Mentor, List[object], int]]] = defaultdict(list)
        for mentor, trace in items:
            bucket_key = int(mentor.occupancy_ratio / bucket_size)
            seed = stable_counter_hash(f"{key}:{bucket_key}:{mentor.mentor_id}")
            buckets[bucket_key].append((mentor, trace, seed))
        ordered_bucket_keys = sorted(buckets.keys())
        if not ordered_bucket_keys:
            return list(items)
        for bucket_key in ordered_bucket_keys:
            buckets[bucket_key].sort(
                key=lambda entry: (
                    entry[0].current_load,
                    entry[0].mentor_id,
                    entry[2],
                )
            )
        positions = {bk: 0 for bk in ordered_bucket_keys}
        total = sum(len(bucket) for bucket in buckets.values())
        interleaved: List[Tuple[Mentor, List[object], int]] = []
        idx = 0
        while len(interleaved) < total:
            bucket_key = ordered_bucket_keys[idx]
            pos = positions[bucket_key]
            if pos < len(buckets[bucket_key]):
                mentor, trace, seed = buckets[bucket_key][pos]
                positions[bucket_key] += 1
                interleaved.append((mentor, trace, seed))
            idx = (idx + 1) % len(ordered_bucket_keys)

        last_mentor = self._round_robin_state.get(key)
        start_index = 0
        if last_mentor is not None:
            for index, (mentor, _trace, _seed) in enumerate(interleaved):
                if mentor.mentor_id == last_mentor:
                    start_index = (index + 1) % len(interleaved)
                    break
        rotated = interleaved[start_index:] + interleaved[:start_index]
        if rotated:
            self._round_robin_state[key] = rotated[0][0].mentor_id
        return [(mentor, trace) for mentor, trace, _seed in rotated]


__all__ = [
    "FairnessStrategy",
    "FairnessConfig",
    "FairnessPlanner",
]

