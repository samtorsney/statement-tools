"""Shared exception types for the statement_parser package.

Kept in their own module (rather than on profile.py / canonical.py / the
engine subpackage) so every module can raise structured errors without
creating import cycles.
"""
from __future__ import annotations

from typing import Optional


class ProfileError(Exception):
    """A profile YAML file is malformed or invalid.

    Raised at load time with an actionable message: which key was unknown,
    which strategy name isn't registered (and what the alternatives are), or
    which reserved-but-unimplemented field was used.
    """


class ExtractionError(Exception):
    """A PDF/CSV extraction step failed.

    Carries file / page / strategy context so failures are traceable without
    needing to print the offending statement contents.
    """

    def __init__(
        self,
        message: str,
        *,
        source_file: Optional[str] = None,
        page: Optional[int] = None,
        strategy: Optional[str] = None,
    ) -> None:
        parts = [message]
        if source_file is not None:
            parts.append(f"file={source_file}")
        if page is not None:
            parts.append(f"page={page}")
        if strategy is not None:
            parts.append(f"strategy={strategy}")
        super().__init__(" | ".join(parts))
        self.source_file = source_file
        self.page = page
        self.strategy = strategy


class CoercionError(Exception):
    """Raw extracted text could not be coerced into canonical typed values."""


class BalanceContinuityError(Exception):
    """A row's printed balance does not equal previous balance + amount."""
