from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
import os
from pathlib import Path
import re
import sys
import traceback
from typing import Any
import unicodedata

import cv2
import numpy as np

from passport_reader_tool.models import PassportRecord
from passport_reader_tool.mrz import MrzData, parse_mrz, parse_mrz_date


@dataclass(frozen=True, slots=True)
class OcrConfig:
    target_width: int = 1600
    mrz_crop_ratio: float = 0.22
    bottom_crop_ratio: float = 0.38
    fallback_bottom_crop_ratio: float = 0.60
    min_valid_score: int = 100
    language: str = "en"
    use_angle_cls: bool = True
    visual_info_left_ratio: float = 0.34
    visual_info_top_ratio: float = 0.52
    visual_info_right_ratio: float = 0.86
    visual_info_bottom_ratio: float = 0.88


class PaddleOcrEngine:
    def __init__(self, config: OcrConfig) -> None:
        self.config = config
        self._ocr: Any | None = None
        self._mode: str | None = None

    def read_text(self, image: np.ndarray) -> list[tuple[str, float | None]]:
        ocr = self._get_ocr()
        if self._mode == "predict":
            return self._read_predict_result(ocr.predict(image))
        try:
            result = ocr.ocr(image, cls=self.config.use_angle_cls)
        except TypeError as exc:
            if "unexpected keyword argument 'cls'" not in str(exc):
                raise
            result = ocr.ocr(image)
        return self._read_ocr_result(result)

    def _get_ocr(self) -> Any:
        if self._ocr is not None:
            return self._ocr
        _configure_paddle_runtime_environment()
        try:
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise RuntimeError("PaddleOCR is not installed. Run `uv sync` after updating dependencies.") from exc

        try:
            model_dirs = _bundled_ocr_model_dirs()
            model_params = {}
            if "text_detection_model_dir" in model_dirs:
                model_params["text_detection_model_dir"] = model_dirs["text_detection_model_dir"]
                model_params["text_detection_model_name"] = "PP-OCRv5_server_det"
            if "text_recognition_model_dir" in model_dirs:
                model_params["text_recognition_model_dir"] = model_dirs["text_recognition_model_dir"]
                model_params["text_recognition_model_name"] = "en_PP-OCRv5_mobile_rec"
            if "textline_orientation_model_dir" in model_dirs:
                model_params["textline_orientation_model_dir"] = model_dirs["textline_orientation_model_dir"]
                model_params["textline_orientation_model_name"] = "PP-LCNet_x1_0_textline_ori"

            self._ocr = PaddleOCR(
                lang=self.config.language,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=self.config.use_angle_cls,
                device="cpu",
                enable_mkldnn=False,
                **model_params,
            )
            self._mode = "predict"
        except (TypeError, ValueError):
            self._ocr = PaddleOCR(
                lang=self.config.language,
                use_angle_cls=self.config.use_angle_cls,
            )
            self._mode = "ocr"
        return self._ocr

    def _read_predict_result(self, result: Any) -> list[tuple[str, float | None]]:
        rows: list[tuple[str, float | None]] = []
        for page in result or []:
            data = page if isinstance(page, dict) else getattr(page, "json", None)
            if callable(data):
                data = data()
            if not isinstance(data, dict):
                continue
            data = data.get("res", data)
            texts = data.get("rec_texts") or data.get("texts") or []
            scores = data.get("rec_scores") or data.get("scores") or []
            for index, text in enumerate(texts):
                score = scores[index] if index < len(scores) else None
                rows.append((str(text), _float_or_none(score)))
        return rows

    def _read_ocr_result(self, result: Any) -> list[tuple[str, float | None]]:
        rows: list[tuple[str, float | None]] = []
        for item in _flatten_ocr_result(result):
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], (list, tuple)):
                text_score = item[1]
                if text_score:
                    rows.append((str(text_score[0]), _float_or_none(text_score[1] if len(text_score) > 1 else None)))
        return rows


class MrzOcrPipeline:
    def __init__(self, config: OcrConfig | None = None, ocr_engine: PaddleOcrEngine | None = None) -> None:
        self.config = config or OcrConfig()
        self.ocr_engine = ocr_engine or PaddleOcrEngine(self.config)

    def read_passport(self, image_path: str | Path, row_number: int, added_date: date | None = None) -> PassportRecord:
        source_path = Path(image_path)
        try:
            image = self._read_image(source_path)
            candidates = self._preprocess_candidates(image)
            last_error = "Could not read MRZ"
            debug_messages: list[str] = []
            for candidate_index, candidate in enumerate(candidates, start=1):
                record, error, debug_message = self._read_candidate(
                    candidate,
                    image,
                    source_path,
                    row_number,
                    added_date,
                    candidate_index,
                )
                if debug_message:
                    debug_messages.append(debug_message)
                if record and not record.is_error:
                    return record
                if error:
                    last_error = error
            return PassportRecord(
                row_number=row_number,
                added_date=added_date,
                status="error",
                error_message=last_error,
                debug_message="\n".join(debug_messages),
                source_file=str(source_path),
            )
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            return PassportRecord(
                row_number=row_number,
                added_date=added_date,
                status="error",
                error_message=str(exc),
                debug_message=f"Exception: {type(exc).__name__}: {exc}",
                source_file=str(source_path),
            )

    def _read_image(self, image_path: Path) -> np.ndarray:
        image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Could not open image: {image_path}")
        return image

    def _preprocess_candidates(self, image: np.ndarray) -> list[np.ndarray]:
        candidates: list[np.ndarray] = []
        for source in self._candidate_source_regions(image):
            candidates.extend(self._preprocess_region(source))
        return candidates

    def _candidate_source_regions(self, image: np.ndarray) -> list[np.ndarray]:
        regions = [
            self._crop_bottom(image, self.config.mrz_crop_ratio),
            self._crop_bottom(image, self.config.bottom_crop_ratio),
            self._crop_bottom(image, self.config.fallback_bottom_crop_ratio),
            image,
        ]
        unique_regions: list[np.ndarray] = []
        seen_shapes: set[tuple[int, ...]] = set()
        for region in regions:
            shape = region.shape
            if shape not in seen_shapes:
                seen_shapes.add(shape)
                unique_regions.append(region)
        return unique_regions

    def _preprocess_region(self, image: np.ndarray) -> list[np.ndarray]:
        resized = self._resize(image)
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        normalized = cv2.equalizeHist(gray)
        _, threshold = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = cv2.adaptiveThreshold(
            normalized,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            11,
        )
        return [resized, threshold, adaptive]

    def _crop_bottom(self, image: np.ndarray, ratio: float | None = None) -> np.ndarray:
        height = image.shape[0]
        crop_ratio = self.config.bottom_crop_ratio if ratio is None else ratio
        crop_ratio = min(1.0, max(0.0, crop_ratio))
        start = max(0, int(height * (1 - crop_ratio)))
        return image[start:height, :]

    def _resize(self, image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        if width <= self.config.target_width:
            return image
        scale = self.config.target_width / width
        return cv2.resize(image, (self.config.target_width, int(height * scale)), interpolation=cv2.INTER_AREA)

    def _read_candidate(
        self,
        image: np.ndarray,
        original_image: np.ndarray,
        source_path: Path,
        row_number: int,
        added_date: date | None,
        candidate_index: int,
    ) -> tuple[PassportRecord | None, str, str]:
        candidate_label = f"candidate {candidate_index} ({image.shape[1]}x{image.shape[0]})"
        text_rows = self.ocr_engine.read_text(image)
        mrz = parse_mrz([text for text, _score in text_rows])
        if mrz is None:
            return None, "MRZ not found", self._debug_text_message(candidate_label, text_rows)

        visual_rows = self.ocr_engine.read_text(self._crop_visual_info_region(original_image))
        visual_data = _extract_visual_passport_data(visual_rows, mrz)
        data = mrz.to_dict()
        debug_message = self._debug_message(candidate_label, data, visual_data)
        if mrz.validation.score < self.config.min_valid_score:
            record = self._record_from_mrz(
                mrz,
                source_path,
                row_number,
                added_date,
                "error",
                "Invalid MRZ checksum",
                debug_message,
                visual_data,
            )
            return record, record.error_message, debug_message

        return (
            self._record_from_mrz(
                mrz,
                source_path,
                row_number,
                added_date,
                debug_message=debug_message,
                visual_data=visual_data,
            ),
            "",
            debug_message,
        )

    def _record_from_mrz(
        self,
        mrz: MrzData,
        source_path: Path,
        row_number: int,
        added_date: date | None,
        status: str = "ok",
        error_message: str = "",
        debug_message: str = "",
        visual_data: "VisualPassportData | None" = None,
    ) -> PassportRecord:
        mrz_full_name = " ".join(part for part in [mrz.surname, mrz.names] if part).strip()
        visual_name = visual_data.full_name if visual_data else ""
        return PassportRecord(
            row_number=row_number,
            full_name=visual_name or mrz_full_name,
            mrz_full_name=mrz_full_name,
            name_mismatch=bool(visual_data and visual_data.name_mismatch),
            date_of_birth=parse_mrz_date(mrz.date_of_birth),
            sex=mrz.sex,
            passport_number=mrz.number,
            issue_date=visual_data.issue_date if visual_data else None,
            expiry_date=parse_mrz_date(mrz.expiration_date, prefer_future=True),
            added_date=added_date,
            status=status,
            error_message=error_message,
            debug_message=debug_message,
            source_file=str(source_path),
        )

    def _debug_text_message(self, candidate_label: str, text_rows: list[tuple[str, float | None]]) -> str:
        text = " | ".join(f"{value} ({score:.3f})" if score is not None else value for value, score in text_rows)
        return f"{candidate_label}: no MRZ detected | ocr_text={text}"

    def _crop_visual_info_region(self, image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        left = int(width * self.config.visual_info_left_ratio)
        right = int(width * self.config.visual_info_right_ratio)
        top = int(height * self.config.visual_info_top_ratio)
        bottom = int(height * self.config.visual_info_bottom_ratio)
        return image[max(0, top) : min(height, bottom), max(0, left) : min(width, right)]

    def _debug_message(self, candidate_label: str, data: dict[str, object], visual_data: "VisualPassportData | None") -> str:
        fields = [
            f"{candidate_label}: MRZ detected",
            f"valid_score={data.get('valid_score')}",
            f"mrz_type={data.get('mrz_type')}",
            f"number={data.get('number')}",
            f"surname={data.get('surname')}",
            f"names={data.get('names')}",
            f"date_of_birth={data.get('date_of_birth')}",
            f"expiration_date={data.get('expiration_date')}",
            f"parsed_date_of_birth={parse_mrz_date(data.get('date_of_birth'))}",
            f"parsed_expiration_date={parse_mrz_date(data.get('expiration_date'), prefer_future=True)}",
            f"sex={data.get('sex')}",
            f"valid_number={data.get('valid_number')}",
            f"valid_date_of_birth={data.get('valid_date_of_birth')}",
            f"valid_expiration_date={data.get('valid_expiration_date')}",
            f"valid_composite={data.get('valid_composite')}",
            f"valid_personal_number={data.get('valid_personal_number')}",
            f"raw_text={str(data.get('raw_text') or '').strip()}",
        ]
        if visual_data:
            fields.extend(
                [
                    f"visual_name={visual_data.full_name}",
                    f"visual_name_match={not visual_data.name_mismatch}",
                    f"issue_date={visual_data.issue_date}",
                ]
            )
        return " | ".join(fields)

    def _parse_mrz_date(self, value: object, prefer_future: bool = False) -> date | None:
        return parse_mrz_date(value, prefer_future)


@dataclass(frozen=True, slots=True)
class VisualPassportData:
    full_name: str = ""
    issue_date: date | None = None
    name_mismatch: bool = False


def _extract_visual_passport_data(
    text_rows: list[tuple[str, float | None]],
    mrz: MrzData,
    issue_date_rows: list[tuple[str, float | None]] | None = None,
) -> VisualPassportData:
    lines = [_clean_visual_line(text) for text, _score in text_rows]
    lines = [line for line in lines if line]
    issue_lines = [_clean_visual_line(text) for text, _score in issue_date_rows] if issue_date_rows is not None else lines
    issue_lines = [line for line in issue_lines if line]
    mrz_full_name = " ".join(part for part in [mrz.surname, mrz.names] if part).strip()
    full_name = _extract_visual_full_name(lines, mrz_full_name)
    issue_date = _extract_issue_date(issue_lines)
    name_mismatch = bool(full_name and _normalize_compare_name(full_name) != _normalize_compare_name(mrz_full_name))
    return VisualPassportData(full_name=full_name, issue_date=issue_date, name_mismatch=name_mismatch)


def _extract_visual_full_name(lines: list[str], mrz_full_name: str) -> str:
    surname = _extract_labeled_name_value(lines, ("HO SURNAME", "SURNAME"))
    given_names = _extract_labeled_name_value(lines, ("CHU DEM VA TEN", "GIVEN NAMES", "GIVEN NAME"))
    if surname and given_names:
        candidate = _ascii_name(f"{surname} {given_names}")
        if _is_close_to_mrz_name(candidate, mrz_full_name):
            return candidate

    label_indexes = [
        index
        for index, line in enumerate(lines)
        if _contains_any(_normalize_for_search(line), ("HO VA TEN", "FULL NAME"))
    ]
    for index in label_indexes:
        candidate = _first_plausible_name(lines[index + 1 : index + 4], mrz_full_name)
        if candidate:
            return candidate

    candidates = [_clean_name_candidate(line) for line in lines]
    candidates = [candidate for candidate in candidates if _is_plausible_visual_name(candidate)]
    if not candidates:
        return ""

    normalized_mrz = _normalize_compare_name(mrz_full_name)
    best_candidate = max(
        candidates,
        key=lambda candidate: SequenceMatcher(None, _normalize_compare_name(candidate), normalized_mrz).ratio(),
    )
    return best_candidate if _is_close_to_mrz_name(best_candidate, mrz_full_name) else ""


def _first_plausible_name(lines: list[str], mrz_full_name: str) -> str:
    for line in lines:
        candidate = _clean_name_candidate(line)
        if _is_plausible_visual_name(candidate) and _is_close_to_mrz_name(candidate, mrz_full_name):
            return candidate
    return ""


def _extract_labeled_name_value(lines: list[str], labels: tuple[str, ...]) -> str:
    for index, line in enumerate(lines):
        if not _contains_any(_normalize_for_search(line), labels):
            continue
        for nearby_line in lines[index + 1 : index + 3]:
            candidate = _clean_name_candidate(nearby_line)
            if _is_plausible_name_value(candidate):
                return candidate
    return ""


def _extract_issue_date(lines: list[str]) -> date | None:
    for index, line in enumerate(lines):
        normalized = _normalize_for_search(line)
        if _contains_any(normalized, ("NGAY CAP", "DATE OF ISSUE", "ISSUE DATE", "DATE D ISSUE")):
            date_value = _parse_visual_date(line)
            if date_value:
                return date_value
            for nearby_line in lines[index + 1 : index + 3]:
                date_value = _parse_visual_date(nearby_line)
                if date_value:
                    return date_value
    return None


def _parse_visual_date(value: str) -> date | None:
    text = _normalize_for_search(value)
    numeric_match = re.search(r"(\d{1,2})\D+(\d{1,2})\D+(\d{4})", text)
    if numeric_match:
        return _date_from_parts(numeric_match.group(1), numeric_match.group(2), numeric_match.group(3))

    month_names = {
        "JAN": 1,
        "FEB": 2,
        "MAR": 3,
        "APR": 4,
        "MAY": 5,
        "JUN": 6,
        "JUL": 7,
        "AUG": 8,
        "SEP": 9,
        "OCT": 10,
        "NOV": 11,
        "DEC": 12,
    }
    month_match = re.search(r"(\d{1,2})\s+([A-Z]{3,9})\s+(\d{4})", text)
    if month_match:
        month = month_names.get(month_match.group(2)[:3])
        if month:
            return _date_from_parts(month_match.group(1), str(month), month_match.group(3))
    return None


def _date_from_parts(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _clean_visual_line(value: str) -> str:
    return " ".join(str(value or "").replace("|", " ").split()).strip()


# def _clean_name_candidate(value: str) -> str:
#     text = re.sub(r"[^A-Za-zÀ-ỹ\s]", " ", value)
#     return " ".join(part for part in text.upper().split() if part)


def _is_plausible_visual_name(value: str) -> bool:
    if not value:
        return False
    normalized = _normalize_for_search(value)
    blocked_words = (
        "PASSPORT",
        "VIET NAM",
        "SOCIALIST",
        "REPUBLIC",
        "HO VA TEN",
        "FULL NAME",
        "DATE",
        "NGAY",
        "SEX",
        "GIOI TINH",
        "NATIONALITY",
        "QUOC TICH",
        "PLACE",
        "NOI",
        "AUTHORITY",
        "CUC",
    )
    if _contains_any(normalized, blocked_words):
        return False
    words = normalized.split()
    return 2 <= len(words) <= 6 and sum(len(word) >= 2 for word in words) >= 2


def _is_plausible_name_value(value: str) -> bool:
    if not value:
        return False
    normalized = _normalize_for_search(value)
    if _contains_any(
        normalized,
        (
            "SURNAME",
            "GIVEN",
            "DATE",
            "NGAY",
            "PLACE",
            "NATIONALITY",
            "SEX",
            "PASSPORT",
            "VIET NAM",
            "VNM",
        ),
    ):
        return False
    words = normalized.split()
    return 1 <= len(words) <= 4 and all(len(word) >= 2 for word in words)


def _normalize_compare_name(value: str) -> str:
    return "".join(_normalize_for_search(value).split())


def _ascii_name(value: str) -> str:
    return _normalize_for_search(value)


def _is_close_to_mrz_name(candidate: str, mrz_full_name: str) -> bool:
    normalized_candidate = _normalize_compare_name(candidate)
    normalized_mrz = _normalize_compare_name(mrz_full_name)
    if not normalized_candidate or not normalized_mrz:
        return False
    if normalized_candidate in normalized_mrz or normalized_mrz in normalized_candidate:
        return True
    ratio = SequenceMatcher(None, normalized_candidate, normalized_mrz).ratio()
    candidate_words = set(_normalize_for_search(candidate).split())
    mrz_words = set(_normalize_for_search(mrz_full_name).split())
    shared_words = candidate_words & mrz_words
    return ratio >= 0.68 or len(shared_words) >= 2


def _normalize_for_search(value: str) -> str:
    text = unicodedata.normalize("NFKD", value.upper())
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.replace("Đ", "D")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    return " ".join(text.split())


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


# def _clean_name_candidate_unused(value: str) -> str:
#     text = re.sub(r"[^A-Za-zÀ-ỹ\s]", " ", value)
#     text = " ".join(part for part in text.upper().split() if part)
#     return _strip_mrz_name_prefix(text)


def _clean_name_candidate(value: str) -> str:
    text = re.sub(r"[^A-Za-zÀ-ỹ\s]", " ", value)
    text = " ".join(part for part in text.upper().split() if part)
    return _ascii_name(_strip_mrz_name_prefix(text))


def _strip_mrz_name_prefix(value: str) -> str:
    parts = value.split()
    if len(parts) >= 2 and re.fullmatch(r"P[A-Z]?", parts[0]) and re.match(r"^[A-Z]{3}[A-Z]+$", parts[1]):
        stripped = " ".join([parts[1][3:], *parts[2:]]).strip()
        return stripped or value
    if len(parts) >= 3 and re.fullmatch(r"P[A-Z]?", parts[0]) and re.fullmatch(r"[A-Z]{3}", parts[1]):
        stripped = " ".join(parts[2:]).strip()
        return stripped or value
    spaced_match = re.match(r"^P[A-Z]?\s*[A-Z]{3}\s+(.+)$", value)
    if spaced_match:
        return spaced_match.group(1).strip() or value
    compact = "".join(value.split())
    match = re.match(r"^P[A-Z]?([A-Z]{3})([A-Z].*)$", compact)
    if not match:
        return value
    remainder = match.group(2)
    if len(remainder) < 4:
        return value
    return " ".join(re.findall(r"[A-Z]+", remainder)) or value


def _flatten_ocr_result(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    flattened: list[Any] = []
    for item in value:
        if isinstance(item, list) and item and all(isinstance(child, list) for child in item):
            flattened.extend(_flatten_ocr_result(item))
        else:
            flattened.append(item)
    return flattened


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _configure_paddle_runtime_environment() -> None:
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    os.environ.setdefault("FLAGS_enable_pir_api", "0")
    os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")


def _bundled_ocr_model_dirs() -> dict[str, str]:
    root = _bundled_model_root()
    model_names = {
        "text_detection_model_dir": "PP-OCRv5_server_det",
        "text_recognition_model_dir": "en_PP-OCRv5_mobile_rec",
        "textline_orientation_model_dir": "PP-LCNet_x1_0_textline_ori",
    }
    model_dirs: dict[str, str] = {}
    for key, name in model_names.items():
        model_dir = root / name
        if model_dir.exists():
            model_dirs[key] = str(model_dir)
    return model_dirs


def _bundled_model_root() -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "paddlex_models"
    executable_root = Path(sys.executable).resolve().parent / "paddlex_models"
    if executable_root.exists():
        return executable_root
    return Path(__file__).resolve().parents[2] / "vendor" / "paddlex_models"
