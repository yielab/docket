import unittest

from api.registry import RESOURCES


class ResourceTests(unittest.TestCase):
    def test_the_first_page_holds_the_first_rows(self) -> None:
        for name, module in RESOURCES.items():
            with self.subTest(resource=name):
                ids = [row["id"] for row in module.list_(1, 2)["items"]]
                self.assertEqual(ids, [1, 2], f"{name}: page 1 gave ids {ids}")

    def test_the_last_page_is_short(self) -> None:
        for name, module in RESOURCES.items():
            with self.subTest(resource=name):
                ids = [row["id"] for row in module.list_(3, 2)["items"]]
                self.assertEqual(ids, [5], f"{name}: page 3 gave ids {ids}")


if __name__ == "__main__":
    unittest.main()
