from datetime import date

import numpy as np

from passport_reader_tool.ocr_pipeline import OcrConfig
from passport_reader_tool.ocr_pipeline import MrzOcrPipeline


def test_parse_mrz_date_uses_reasonable_century():
    pipeline = MrzOcrPipeline()

    assert pipeline._parse_mrz_date("900102") == date(1990, 1, 2)
    assert pipeline._parse_mrz_date("300304") == date(1930, 3, 4)
    assert pipeline._parse_mrz_date("300304", prefer_future=True) == date(2030, 3, 4)
    assert pipeline._parse_mrz_date("") is None


def test_candidate_source_regions_keep_wider_fallback_and_original():
    pipeline = MrzOcrPipeline(OcrConfig(mrz_crop_ratio=0.22, bottom_crop_ratio=0.38, fallback_bottom_crop_ratio=0.60))
    image = np.zeros((1000, 800, 3), dtype=np.uint8)

    regions = pipeline._candidate_source_regions(image)

    assert [region.shape[:2] for region in regions] == [(220, 800), (380, 800), (600, 800), (1000, 800)]
