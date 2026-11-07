import migrations


def test_numbers_sort_as_numbers():
    names = ["10_index", "7_backfill_plan", "9_seed"]
    assert migrations.pending(set(), names) == ["7_backfill_plan", "9_seed", "10_index"]
