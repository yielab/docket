import regions


def test_region_total(tmp_path):
    path = tmp_path / "region-01.csv"
    path.write_text("day,units\n1,79\n2,18\n", encoding="utf-8")
    assert regions.region_total(path) == 97
