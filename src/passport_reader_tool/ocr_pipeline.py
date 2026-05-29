from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import NamedTemporaryFile

import cv2
import numpy as np
from passporteye import read_mrz

from passport_reader_tool.models import PassportRecord
from passport_reader_tool.tesseract_runtime import configure_tesseract


@dataclass(frozen=True, slots=True)
class OcrConfig:
    target_width: int = 1600
    bottom_crop_ratio: float = 0.38
    min_valid_score: int = 100


class MrzOcrPipeline:
    def __init__(self, config: OcrConfig | None = None) -> None:
        self.config = config or OcrConfig()
        configure_tesseract()

    def read_passport(self, image_path: str | Path, row_number: int, added_date: date | None = None) -> PassportRecord:
        source_path = Path(image_path)
        try:
            image = self._read_image(source_path)
            candidates = self._preprocess_candidates(image)
            last_error = "Không đọc được MRZ"
            for candidate in candidates:
                record, error = self._read_candidate(candidate, source_path, row_number, added_date)
                if record and not record.is_error:
                    return record
                if error:
                    last_error = error
            return PassportRecord(
                row_number=row_number,
                added_date=added_date,
                status="error",
                error_message=last_error,
                source_file=str(source_path),
            )
        except Exception as exc:
            return PassportRecord(
                row_number=row_number,
                added_date=added_date,
                status="error",
                error_message=str(exc),
                source_file=str(source_path),
            )

    def _read_image(self, image_path: Path) -> np.ndarray:
        image = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError(f"Không mở được ảnh: {image_path}")
        return image

    def _preprocess_candidates(self, image: np.ndarray) -> list[np.ndarray]:
        cropped = self._crop_bottom(image)
        resized = self._resize(cropped)
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

    def _crop_bottom(self, image: np.ndarray) -> np.ndarray:
        height = image.shape[0]
        start = max(0, int(height * (1 - self.config.bottom_crop_ratio)))
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
        source_path: Path,
        row_number: int,
        added_date: date | None,
    ) -> tuple[PassportRecord | None, str]:
        with NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
            temp_path = Path(temp_file.name)
        try:
            cv2.imwrite(str(temp_path), image)
            mrz = read_mrz(str(temp_path))
            if mrz is None:
                return None, "Không tìm thấy MRZ"
            data = mrz.to_dict()
            valid_score = int(data.get("valid_score") or getattr(mrz, "valid_score", 0) or 0)
            if valid_score < self.config.min_valid_score:
                return self._record_from_mrz(data, source_path, row_number, added_date, "error", "Checksum MRZ không hợp lệ"), "Checksum MRZ không hợp lệ"
            return self._record_from_mrz(data, source_path, row_number, added_date), ""
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _record_from_mrz(
        self,
        data: dict[str, object],
        source_path: Path,
        row_number: int,
        added_date: date | None,
        status: str = "ok",
        error_message: str = "",
    ) -> PassportRecord:
        surname = str(data.get("surname") or "").replace("<", " ").strip()
        names = str(data.get("names") or "").replace("<", " ").strip()
        full_name = " ".join(part for part in [surname, names] if part).strip()
        return PassportRecord(
            row_number=row_number,
            full_name=full_name,
            date_of_birth=self._parse_mrz_date(data.get("date_of_birth")),
            sex=str(data.get("sex") or "").strip(),
            passport_number=str(data.get("number") or "").replace("<", "").strip(),
            expiry_date=self._parse_mrz_date(data.get("expiration_date"), prefer_future=True),
            added_date=added_date,
            status=status,
            error_message=error_message,
            source_file=str(source_path),
        )

    def _parse_mrz_date(self, value: object, prefer_future: bool = False) -> date | None:
        text = str(value or "").strip()
        if len(text) != 6 or not text.isdigit():
            return None
        year = int(text[:2])
        month = int(text[2:4])
        day = int(text[4:6])
        if prefer_future:
            full_year = 2000 + year
        else:
            full_year = 1900 + year if year > date.today().year % 100 else 2000 + year
        return date(full_year, month, day)
