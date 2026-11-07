import unittest

from calendar_days import days_in_month


class CalendarDaysTests(unittest.TestCase):
    def test_spec(self) -> None:
        self.assertEqual(days_in_month(2023, 4), 30)
        self.assertEqual(days_in_month(1900, 2), 28)


if __name__ == "__main__":
    unittest.main()
