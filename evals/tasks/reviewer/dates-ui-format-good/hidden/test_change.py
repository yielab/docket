import dates


def test_the_day_comes_first():
    assert dates.format_for_ui("2026-11-07T09:00:00Z") == "07/11/2026"
    assert dates.format_for_ui("2027-01-31T23:59:59Z") == "31/01/2027"
