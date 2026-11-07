import migrations


def test_the_rows_passed_in_are_not_modified():
    rows = [{"id": 1, "plan_id": None}]
    out = migrations.backfill_plan(rows, 1)
    assert out == [{"id": 1, "plan_id": 1}]
    assert rows == [{"id": 1, "plan_id": None}]
