from __future__ import annotations


class DatasetError(Exception):
    """Dataset error with a stable category and client-safe message."""

    def __init__(self, category: str, safe_message: str) -> None:
        super().__init__(category)
        self.category = category
        self.safe_message = safe_message
