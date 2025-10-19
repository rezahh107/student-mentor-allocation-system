from __future__ import annotations

import pathlib
from dataclasses import dataclass

from .io_utils import atomic_write, ensure_crlf
from .logging_utils import JsonLogger
from .retry import RetryPolicy


@dataclass(slots=True)
class EnvDoctor:
    root: pathlib.Path
    apply: bool
    logger: JsonLogger
    retry: RetryPolicy

    def ensure(self) -> None:
        env_path = self.root / ".env"
        example_path = self.root / ".env.example"
        if env_path.exists() and env_path.stat().st_size > 0:
            self.logger.info(".env already exists")
            return

        if example_path.exists():
            content = example_path.read_text(encoding="utf-8")
        else:
            content = "METRICS_TOKEN=change-me-please"
        if self.apply:
            atomic_write(env_path, ensure_crlf(content), newline="")
            self.logger.info("Created .env from example", path=str(env_path))
        else:
            self.logger.info(".env dry-run", path=str(env_path))
