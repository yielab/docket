import unittest

from cfg.registry import SERVICES


class ServiceSettingsTests(unittest.TestCase):
    def test_every_service_honours_its_timeout_override(self) -> None:
        for name, module in SERVICES.items():
            with self.subTest(service=name):
                got = module.load({module.PREFIX + "TIMEOUT_S": "45"}).timeout_s
                self.assertEqual(got, 45, f"{name}: TIMEOUT_S=45 gave {got}")

    def test_defaults_apply_when_nothing_is_set(self) -> None:
        for name, module in SERVICES.items():
            with self.subTest(service=name):
                self.assertEqual(module.load({}).timeout_s, module.DEFAULT_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
