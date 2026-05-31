from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(slots=True)
class PassportRecord:
    row_number: int
    full_name: str = ""
    mrz_full_name: str = ""
    name_mismatch: bool = False
    date_of_birth: date | None = None
    sex: str = ""
    passport_number: str = ""
    issue_date: date | None = None
    expiry_date: date | None = None
    added_date: date | None = None
    status: str = "ok"
    error_message: str = ""
    debug_message: str = ""
    source_file: str = ""

    @property
    def is_error(self) -> bool:
        return self.status != "ok"
