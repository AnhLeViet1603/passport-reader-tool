from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re


_NON_MRZ_RE = re.compile(r"[^A-Z0-9<]")


MRZ_WEIGHTS = (7, 3, 1)
MRZ_CHAR_VALUES = {str(index): index for index in range(10)}
MRZ_CHAR_VALUES.update({chr(ord("A") + index): 10 + index for index in range(26)})
MRZ_CHAR_VALUES["<"] = 0


@dataclass(frozen=True, slots=True)
class MrzValidation:
    number: bool
    date_of_birth: bool
    expiration_date: bool
    personal_number: bool
    composite: bool

    @property
    def is_valid(self) -> bool:
        return self.number and self.date_of_birth and self.expiration_date and self.personal_number and self.composite

    @property
    def score(self) -> int:
        checks = [
            self.number,
            self.date_of_birth,
            self.expiration_date,
            self.personal_number,
            self.composite,
        ]
        return int(sum(1 for valid in checks if valid) / len(checks) * 100)


@dataclass(frozen=True, slots=True)
class MrzData:
    mrz_type: str
    raw_text: str
    document_code: str
    issuing_country: str
    surname: str
    names: str
    number: str
    nationality: str
    date_of_birth: str
    sex: str
    expiration_date: str
    personal_number: str
    validation: MrzValidation

    def to_dict(self) -> dict[str, object]:
        return {
            "mrz_type": self.mrz_type,
            "raw_text": self.raw_text,
            "document_code": self.document_code,
            "country": self.issuing_country,
            "surname": self.surname,
            "names": self.names,
            "number": self.number,
            "nationality": self.nationality,
            "date_of_birth": self.date_of_birth,
            "sex": self.sex,
            "expiration_date": self.expiration_date,
            "personal_number": self.personal_number,
            "valid_score": self.validation.score,
            "valid_number": self.validation.number,
            "valid_date_of_birth": self.validation.date_of_birth,
            "valid_expiration_date": self.validation.expiration_date,
            "valid_personal_number": self.validation.personal_number,
            "valid_composite": self.validation.composite,
        }


def parse_mrz(raw_lines: list[str]) -> MrzData | None:
    lines = extract_td3_lines(raw_lines)
    if lines is None:
        return None
    line1, line2 = lines
    surname, names = _parse_names(line1[5:44])
    validation = MrzValidation(
        number=_has_valid_check_digit(line2[0:9], line2[9]),
        date_of_birth=_has_valid_check_digit(line2[13:19], line2[19]),
        expiration_date=_has_valid_check_digit(line2[21:27], line2[27]),
        personal_number=_has_valid_check_digit(line2[28:42], line2[42]),
        composite=_has_valid_check_digit(line2[0:10] + line2[13:20] + line2[21:43], line2[43]),
    )
    return MrzData(
        mrz_type="TD3",
        raw_text=f"{line1}\n{line2}",
        document_code=line1[0:2].replace("<", "").strip(),
        issuing_country=line1[2:5].replace("<", "").strip(),
        surname=surname,
        names=names,
        number=line2[0:9].replace("<", "").strip(),
        nationality=line2[10:13].replace("<", "").strip(),
        date_of_birth=line2[13:19],
        sex=line2[20].replace("<", "").strip(),
        expiration_date=line2[21:27],
        personal_number=line2[28:42].replace("<", "").strip(),
        validation=validation,
    )


def extract_td3_lines(raw_lines: list[str]) -> tuple[str, str] | None:
    candidates = [_normalize_line(line) for line in raw_lines]
    candidates = [line for line in candidates if _looks_like_mrz(line)]

    for index in range(len(candidates) - 1):
        line1 = _fit_td3_line(candidates[index])
        line2 = _fit_td3_line(candidates[index + 1])
        if line1 and line2 and line1.startswith("P<") and _looks_like_td3_second_line(line2):
            return line1, line2

    joined = "".join(candidates)
    for match in re.finditer(r"P<[A-Z0-9<]{86}", joined):
        first = match.group(0)[:44]
        second = match.group(0)[44:88]
        if _looks_like_td3_second_line(second):
            return first, second
    return None


def calculate_check_digit(value: str) -> str:
    total = 0
    for index, character in enumerate(value):
        total += MRZ_CHAR_VALUES.get(character, 0) * MRZ_WEIGHTS[index % len(MRZ_WEIGHTS)]
    return str(total % 10)


def parse_mrz_date(value: object, prefer_future: bool = False, today: date | None = None) -> date | None:
    text = str(value or "").strip()
    if len(text) != 6 or not text.isdigit():
        return None
    year = int(text[:2])
    month = int(text[2:4])
    day = int(text[4:6])
    current_year = (today or date.today()).year % 100
    if prefer_future:
        full_year = 2000 + year
    else:
        full_year = 1900 + year if year > current_year else 2000 + year
    try:
        return date(full_year, month, day)
    except ValueError:
        return None


def _normalize_line(value: str) -> str:
    text = value.upper()
    text = text.replace(" ", "").replace("\t", "")
    text = text.replace("«", "<").replace("‹", "<").replace("＜", "<")
    return _NON_MRZ_RE.sub("", text)


def _looks_like_mrz(line: str) -> bool:
    return len(line) >= 20 and ("<" in line or line.startswith("P")) and sum(character == "<" for character in line) >= 2


def _fit_td3_line(line: str) -> str | None:
    if len(line) < 40:
        return None
    if len(line) < 44:
        return line.ljust(44, "<")
    return line[:44]


def _looks_like_td3_second_line(line: str) -> bool:
    return len(line) == 44 and line[13:19].isdigit() and line[21:27].isdigit()


def _has_valid_check_digit(value: str, check_digit: str) -> bool:
    return check_digit.isdigit() and calculate_check_digit(value) == check_digit


def _parse_names(value: str) -> tuple[str, str]:
    parts = value.rstrip("<").split("<<", maxsplit=1)
    surname = _clean_name(parts[0]) if parts else ""
    names = _clean_name(parts[1]) if len(parts) > 1 else ""
    return surname, names


def _clean_name(value: str) -> str:
    return " ".join(part for part in value.replace("<", " ").split() if part)
