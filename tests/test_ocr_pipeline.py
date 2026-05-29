from datetime import date

from passport_reader_tool.ocr_pipeline import MrzOcrPipeline


def test_parse_mrz_date_uses_reasonable_century():
    pipeline = MrzOcrPipeline()

    assert pipeline._parse_mrz_date("900102") == date(1990, 1, 2)
    assert pipeline._parse_mrz_date("300304") == date(1930, 3, 4)
    assert pipeline._parse_mrz_date("300304", prefer_future=True) == date(2030, 3, 4)
    assert pipeline._parse_mrz_date("") is None
