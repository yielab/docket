import migrations


def test_the_free_plan_zero_is_a_plan():
    rows = [{"id": 1, "plan_id": 0}, {"id": 2, "plan_id": None}, {"id": 3, "plan_id": 3}]
    assert migrations.needs_plan(rows) == [2]
