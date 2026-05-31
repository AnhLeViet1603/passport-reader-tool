import os
from pathlib import Path

import numpy as np

from passport_reader_tool.ocr_pipeline import OcrConfig
from passport_reader_tool.ocr_pipeline import PaddleOcrEngine
from passport_reader_tool.ocr_pipeline import MrzOcrPipeline
from passport_reader_tool.ocr_pipeline import _configure_paddle_runtime_environment
from passport_reader_tool.ocr_pipeline import _extract_visual_passport_data
from passport_reader_tool.mrz import parse_mrz

TD3_LINE_1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
TD3_LINE_2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


class FakeOcrEngine:
    def __init__(self) -> None:
        self.calls = 0

    def read_text(self, _image):
        self.calls += 1
        if self.calls == 1:
            return [(TD3_LINE_1, 0.99), (TD3_LINE_2, 0.98)]
        return [("Surname", 0.99), ("ERIKSSON", 0.98), ("Given names", 0.98), ("ANNA MARIA", 0.97), ("Date of issue 03/02/2020", 0.96)]


class FakeLegacyPaddleOcr:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ocr(self, image, **kwargs):
        self.calls.append(kwargs)
        if "cls" in kwargs:
            raise TypeError("PaddleOCR.predict() got an unexpected keyword argument 'cls'")
        return [[[None, [TD3_LINE_1, 0.97]]]]


def test_candidate_source_regions_keep_wider_fallback_and_original():
    pipeline = MrzOcrPipeline(OcrConfig(mrz_crop_ratio=0.22, bottom_crop_ratio=0.38, fallback_bottom_crop_ratio=0.60))
    image = np.zeros((1000, 800, 3), dtype=np.uint8)

    regions = pipeline._candidate_source_regions(image)

    assert [region.shape[:2] for region in regions] == [(220, 800), (380, 800), (600, 800), (1000, 800)]


def test_visual_info_region_crops_passport_data_area():
    pipeline = MrzOcrPipeline(OcrConfig())
    image = np.zeros((1707, 1218, 3), dtype=np.uint8)

    crop = pipeline._crop_visual_info_region(image)

    assert crop.shape[:2] == (615, 633)


def test_read_candidate_uses_visual_info_region_for_name_and_issue_date():
    pipeline = MrzOcrPipeline(ocr_engine=FakeOcrEngine())
    image = np.zeros((220, 800, 3), dtype=np.uint8)

    record, error, debug_message = pipeline._read_candidate(image, image, Path("passport.jpg"), 3, None, 1)

    assert error == ""
    assert record is not None
    assert record.full_name == "ERIKSSON ANNA MARIA"
    assert record.mrz_full_name == "ERIKSSON ANNA MARIA"
    assert record.issue_date is not None
    assert str(record.issue_date) == "2020-02-03"
    assert record.passport_number == "L898902C3"
    assert not record.is_error
    assert "valid_score=100" in debug_message
    assert "issue_date=2020-02-03" in debug_message


def test_paddle_predict_result_reads_latest_res_payload():
    engine = PaddleOcrEngine(OcrConfig())

    rows = engine._read_predict_result([{"res": {"rec_texts": [TD3_LINE_1], "rec_scores": [0.97]}}])

    assert rows == [(TD3_LINE_1, 0.97)]


def test_paddle_ocr_result_retries_without_cls_for_compatibility():
    engine = PaddleOcrEngine(OcrConfig())
    fake_ocr = FakeLegacyPaddleOcr()
    engine._ocr = fake_ocr
    engine._mode = "ocr"

    rows = engine.read_text(np.zeros((20, 80, 3), dtype=np.uint8))

    assert rows == [(TD3_LINE_1, 0.97)]
    assert fake_ocr.calls == [{"cls": True}, {}]


def test_paddle_runtime_disables_pir_before_import(monkeypatch):
    monkeypatch.delenv("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", raising=False)
    monkeypatch.delenv("FLAGS_enable_pir_api", raising=False)
    monkeypatch.delenv("FLAGS_enable_pir_in_executor", raising=False)

    _configure_paddle_runtime_environment()

    assert os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] == "True"
    assert os.environ["FLAGS_enable_pir_api"] == "0"
    assert os.environ["FLAGS_enable_pir_in_executor"] == "0"


def test_extract_visual_passport_data_combines_surname_given_names_and_reads_issue_date():
    mrz = parse_mrz(
        [
            "P<VNMPHUNG<<THI<XUAN<<<<<<<<<<<<<<<<<<<<<<<<",
            "P042903609VNM9107201F3605048040191008413<<94",
        ]
    )
    assert mrz is not None

    data = _extract_visual_passport_data(
        [
            ("Surname", 0.99),
            ("PHUNG", 0.98),
            ("Given names", 0.98),
            ("THI XUÁN", 0.97),
            ("Place of birth", 0.96),
            ("NGHE AN", 0.95),
            ("Date of issue", 0.94),
            ("04/05/2026", 0.93),
        ],
        mrz,
    )

    assert data.full_name == "PHUNG THI XUAN"
    assert not data.name_mismatch
    assert str(data.issue_date) == "2026-05-04"


def test_extract_visual_passport_data_flags_visual_name_mismatch():
    mrz = parse_mrz(
        [
            "P<VNMTAN<<VAN<OA<<<<<<<<<<<<<<<<<<<<<<<<<<<<",
            "E044873574VNM9202014M3604203040092006876<<02",
        ]
    )
    assert mrz is not None

    data = _extract_visual_passport_data(
        [
            ("Surname", 0.99),
            ("TAN", 0.98),
            ("Given names", 0.98),
            ("VAN HOA", 0.97),
        ],
        mrz,
    )

    assert data.full_name == "TAN VAN HOA"
    assert data.name_mismatch
