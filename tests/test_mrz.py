from datetime import date

from passport_reader_tool.mrz import calculate_check_digit, parse_mrz, parse_mrz_date


TD3_LINE_1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
TD3_LINE_2 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"


def test_parse_td3_mrz_validates_checksums_and_fields():
    mrz = parse_mrz([TD3_LINE_1, TD3_LINE_2])

    assert mrz is not None
    assert mrz.validation.is_valid
    assert mrz.validation.score == 100
    assert mrz.surname == "ERIKSSON"
    assert mrz.names == "ANNA MARIA"
    assert mrz.number == "L898902C3"
    assert mrz.date_of_birth == "740812"
    assert mrz.expiration_date == "120415"
    assert mrz.sex == "F"


def test_parse_td3_mrz_reports_invalid_checksum():
    bad_line_2 = f"{TD3_LINE_2[:-1]}1"

    mrz = parse_mrz([TD3_LINE_1, bad_line_2])

    assert mrz is not None
    assert not mrz.validation.is_valid
    assert not mrz.validation.composite


def test_calculate_check_digit_uses_mrz_weighting():
    assert calculate_check_digit("L898902C3") == "6"


def test_parse_mrz_date_uses_reasonable_century():
    assert parse_mrz_date("900102", today=date(2026, 5, 31)) == date(1990, 1, 2)
    assert parse_mrz_date("300304", today=date(2026, 5, 31)) == date(1930, 3, 4)
    assert parse_mrz_date("300304", prefer_future=True, today=date(2026, 5, 31)) == date(2030, 3, 4)
    assert parse_mrz_date("") is None
