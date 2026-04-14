from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class KeySchema:
    pk_name: str = "pk"
    sk_name: str = "sk"
    pk_separator: str = "::"
    sk_separator: str = "#"
    active_prefix: str | None = None
    inactive_prefix: str | None = None

    def __post_init__(self) -> None:
        if not self.pk_name.strip():
            raise ValueError("pk_name must not be empty")
        if not self.sk_name.strip():
            raise ValueError("sk_name must not be empty")
        if not self.pk_separator:
            raise ValueError("pk_separator must not be empty")
        if not self.sk_separator:
            raise ValueError("sk_separator must not be empty")
        if self.active_prefix is None:
            object.__setattr__(self, "active_prefix", f"1{self.sk_separator}")
        if self.inactive_prefix is None:
            object.__setattr__(self, "inactive_prefix", f"0{self.sk_separator}")


DEFAULT_KEY_SCHEMA = KeySchema()
UPPERCASE_KEY_SCHEMA = KeySchema(pk_name="PK", sk_name="SK")
