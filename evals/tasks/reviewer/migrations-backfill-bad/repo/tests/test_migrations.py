import migrations


def test_applied_migrations_are_left_out():
    assert migrations.pending({"1_a"}, ["1_a", "2_b"]) == ["2_b"]
