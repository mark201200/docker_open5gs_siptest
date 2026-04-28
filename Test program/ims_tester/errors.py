from __future__ import annotations

from typing import Iterable, List


class ConfigValidationError(ValueError):
    def __init__(self, errors: Iterable[str]) -> None:
        self.errors: List[str] = list(errors)
        message = "Configuration validation failed:\n" + "\n".join(f"- {e}" for e in self.errors)
        super().__init__(message)
