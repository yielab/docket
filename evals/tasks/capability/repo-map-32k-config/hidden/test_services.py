"""Every service honours its overrides, and only the faulty module was touched."""

import hashlib
import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(os.environ["EVAL_REPO"])
sys.path.insert(0, str(REPO))

BAD = "payments_ledger"
MANIFEST = {
    "auth_archive": "a656aa58a103f19fe8ece495aface52d55bdcee1f42609480f502cdec6e9fed7",
    "auth_audit": "a644804698b990fd7fd6f92458e235425b6222f161b28400d02b0c0d949be756",
    "auth_cache": "dde2204e0e42919ee68bcfa7711a4ea72d93a17464838dadf861c1344a9a9b31",
    "auth_export": "8819c61635d7354858633f1bda2beee52ab24d7a5288c0e3eeee44975c1919a0",
    "auth_gateway": "f289ff9d111bf55457cdfb41c0bde5b01fb40a31004bdb844c399a56222c9d70",
    "auth_import": "fd3cea1195ae96798c117812128cd4c298687e02dc71c17fb0bda5dbbfdfd113",
    "auth_ledger": "82bfa65c8abea2c302de0f52616861cf27fcc460526b231cc3f82cbca354b0a6",
    "auth_queue": "33d5e52c45a407d234f911d4ae1d08ee9b4c5bbe179012323f68dc10d5428a2e",
    "auth_sync": "894d18743bc5ce2f23aa1996e93c5dcb572f16e75b2e138d9cf6282bfddeb9dd",
    "billing_archive": "6659f327231670d566a45550e743099329c9f1b494e2a566e6fe80c8daa5cb7f",
    "billing_audit": "cc17b31c8859f4552902f48370cafe457d0da1a2c9983d4d65de67780d229dc7",
    "billing_cache": "171cf3ed6f27365c11778c9ea28f81f8fbb6cc549635b0a0d84fe53892e8707a",
    "billing_export": "cabff78fdc64947f31e30f8c0a30d41efda961c15f88d45784e7d584fda9d715",
    "billing_gateway": "f28687cbfdbf889e798024740f427afc590ea1b20381dde4b1c8f6ccb3440fa7",
    "billing_import": "4aaab8c105c2ad875852fa143b57caaac78065d36e0340c9defd50ffe0093ff8",
    "billing_ledger": "96956f12c2d17cb4b913ddb6b10dd3a33f71424b3b055a7ec60de8f210fa0c28",
    "billing_queue": "3683e4adaa15cd3592c9093c117ada2d728ceb16488cc17d322161094454733a",
    "billing_sync": "1b8d2541b9e08c3217282f359964958e427e4bf6a3d616e739c4021cc6ff3829",
    "catalog_archive": "9b49012fe9665e3a0ceb366db0bad2ef19821a83bce1eaa32016d4609428f6a0",
    "catalog_audit": "868fa00e46cd826cb1cae83c493afc9be5792122ddf6ddf59dcfefda63944d5e",
    "catalog_cache": "a677e585cae94b9df384512e4ca9290e24bd2e79418fc18ff2e906754c7aab77",
    "catalog_export": "ab97a4c8ac8cae583997133b0a8cd84954b3c352adfd25db6dceeba4bf85cf72",
    "catalog_gateway": "4864af49c965db5d4f95197d3a1ba15e2ce73a8ccd552a383d9d2696a1914292",
    "catalog_import": "975d23d8020c50e72a58b492513f4719e565e3e20a29bc7f648f8df90f5e9e62",
    "catalog_ledger": "e1047efbbb4bc15bcde4372cae056a2902317da8442a80b39cbc7d82f4a1d91c",
    "catalog_queue": "f97ad3fb4d091ef0ce782449b4961a437d75784934439e4eef954d8dcf09fe8b",
    "catalog_sync": "38818bee00db250571cdb549fc8dc264a689208317ae1be4f20a88495aeb0ddf",
    "checkout_archive": "1e11311b9d2c0e3135ea8cf4bc0ae4572ba71f71253ccaa67227ae691d1f7abc",
    "checkout_audit": "90e1ba4c88596b9465c36dd60bdb23b61aac7c399a51b936e40101379936a84c",
    "checkout_cache": "aae44045f5e7be2333cd58567f8592d5aead2155d254996056a7e56b37bca282",
    "checkout_export": "4536b196640357ad95fcc22c0b32e360c073fc4adf044180e65231e96413eddd",
    "checkout_gateway": "df647af7ed1e7d5e42c1beb474e64436e0b72d0e6978d7b1d2a0768e84bdf501",
    "checkout_import": "f86aee37f8578f16a3b3aad5199018dc54f231f75c5a5ce27a2a348297522237",
    "checkout_ledger": "7ef2f9beb78a4681be55d996616c202e22a771d8bd95c1319b58b833e64b1776",
    "checkout_queue": "2f5581a8e738b2b00a3640cceacfbd22a28aadb382ede23d36f720c8ac58a682",
    "checkout_sync": "34449260cf9b27b593055e3a1cf4021176e2ee3ab4947b5900a5eb5a97103245",
    "orders_archive": "402431de87729c780cc9bec8ca17b762e98157ce9621e079aa0c9bf84e10ffa3",
    "orders_audit": "fa8a8da0d858ac6f715fffcd3eab8b6d30dafdd12039060b9e5dce436f7e166b",
    "orders_cache": "c846c113310c37b82d57bffa3af9d7ba1a5c2a7f9f21fd0267667cc93dee8504",
    "orders_export": "65ca0b8d117e16df5c4fe4d5068423d723c463f3581fffca5fdf72b8f92c87e9",
    "orders_gateway": "cd03e8f463a5c815794a06b7035a656f29bbe6bf6a9dfbcd63c89be1edbc45f8",
    "orders_import": "dc4fbf86ef01926aff47990d442ef4e172d58db144e8eaca5866d3fa9917e841",
    "orders_ledger": "50c71ba743a80faa96c9d66db2ef8d81c0e5f91d54e73feb74ce4b8823c9806a",
    "orders_queue": "8e9c200edd1cc0e02a684017a3d4cb39aefe44e0ae8a56744f3c19b67ff1461b",
    "orders_sync": "2c2951c84ac33b1a083eb05d6c13894fce3911175966749c1268f9f4b6bec518",
    "payments_archive": "84ee23e899a7e5b9758ccc50d5f69e61123de60cd5f4c8f62de447d40da3cc3b",
    "payments_audit": "8d1219e0608ede1969964d24b638fc6a41c563760dd727146dd6f139a58f4f04",
    "payments_cache": "f3e32068e4568a0afde0d52b8da6620309e416d92ea1a0b977408045fdb8c536",
    "payments_export": "8081032349a7075e53188277a47bff3f3a93faedd506a3315a0976f05ee130be",
    "payments_gateway": "038aa8c08dbb82ed5eb1420f113021a63f5c5ce457d491de6426481ac49ccc30",
    "payments_import": "ac6e8e55c635562c8714879a3661cd9915c0dd21c4cc2722e8778a50109f5649",
    "payments_queue": "91bb0306ee03fb5d4558c6a191f3a03ee2b03cb93e249a8a69979440ec71e9fe",
    "payments_sync": "f3c86b9b19bb9f2139aef9523807fbf94f6bb6b1d510a39e17187a421ffc121f",
    "profiles_archive": "3d5894684bbcfa24aa23562ecb5946076753d4b0db6f6574de3949b966241e76",
    "profiles_audit": "0d8cac47ec702ea6277109a6cf6e29cfd02748b186bf3b4df75da171ff430b63",
    "profiles_cache": "c0b1dcdb9507e92a216e5b4a92c2adfbddd21cfe9438befeba612413312e85cd",
    "profiles_export": "93a7ab7c2bbc94fa6d0a2d43a7f6c5055cb9f1e2bc8e681bbfe91766d8c5900d",
    "profiles_gateway": "6baca98064bca3174dcaf84c9dde869f871cf24f2605bf35410a728b531d09cc",
    "profiles_import": "8a815cf170bb877bab57a8b817d6c899e3a1d287a9cccc522919a7572b76e1e2",
    "profiles_ledger": "cf933079afa1fd9bd3e9a8507153c6bbb177d2282c3d223fff35b253e14fda4b",
    "profiles_queue": "71403c35d347221a4556c6dd4aa3f8f5392eab6b31debc2946ab4dcc369b1aff",
    "profiles_sync": "fb8e5bace0060d787d62d1d535e893e65a6d32240d83866bbef9d8216ea263af",
    "reports_archive": "01a99aa9eca397567fea0dded766cea584bb49e449ee20fc64bf72b2aad09154",
    "reports_audit": "f5049d2122bd95fa821622459b20049948ae6e50fe3a85e21fe82e396d5d7241",
    "reports_cache": "3517d7406b1165cf9a33412cce008bb2390a8224b74366c2555fa9845dcb2d98",
    "reports_export": "96d201f14dd735d35ee79d0093f5513129b37468a89ca50f2495cc63bb4728cd",
    "reports_gateway": "50d8dd8c55e27256115ba78f270c9e36138f1d8d6f929ae48d9142ce0c7003d8",
    "reports_import": "b3045f747fd7b44f9aa38d8f9cbe242c146db551204e69596c974c2484c49103",
    "reports_ledger": "8ec133141d5c011cb8f12a669c98faeaf06e7b28ec08d3379b873ed3d4fb6346",
    "reports_queue": "1f3f3a9df4b9d2f504cd7bce43daf258db0ca1981bf31f323470a6a203461cdb",
    "reports_sync": "06daddebe7b81109e3e51aa2bb9374205ded836b0d5f02268a1a7c896a946436",
    "search_archive": "434725ff757456a1993820f80ab270c07ea31ff4f498214b537f179d729d4d60",
    "search_audit": "276544f1cef4c2cb68b6509eb6176ed88114ee7d8d129a720298866278dc987b",
    "search_cache": "8249b0dafd1d0c52cadf884cd6be49a17f52f09b0593785d8500a508de921b4d",
    "search_export": "a3bb6eba1ceb129f70a03765102751f6e09f6f78433c1c1b2a56cbafd6ed7938",
    "search_gateway": "91102161b4b73e292093d1215436c6de5063b24d227f8f3a906ce5420b48f6b4",
    "search_import": "ff6cb6309cfdb837d813bc4db828c3fae9b59fa2cbb419d0eb835a894f473f37",
    "search_ledger": "7d2fae40e308401fa56b8a8e54418ed6a563eac185849e4fd673ec480f1967cc",
    "search_queue": "6f8fbb3d8258c396658fa54ea9f7c06cc735caa1df43335973d6fe96c0ba88e2",
    "search_sync": "fbd3d601fbd794a660ccf8e329d974e234630e7a02f37b9f92be283a3abd55c8",
    "shipping_archive": "1a9eedc5271c1cdc677cd83617c9c4c93928a9f211f4d31320b46fa2ba13a25c",
    "shipping_audit": "167885e0c23f50c77f6c501823e78ab983f00336c15f4b0f77bd7c725bc8cb42",
    "shipping_cache": "cd40f2e56394008ecfd7fb99ef080b27d8d264a79542234eee67203c367698cc",
    "shipping_export": "527ddf416062253be6276b7f69a682e91055bb85b2a1ad7e07e159050d61d8ae",
    "shipping_gateway": "302f8e18dd54b4122847f1cd976e7edb82e0bfde1192db4444f0696cf45b7801",
    "shipping_import": "e44a792bd49c348f08c6e668b78eaa83d3c7e5d8bcdec97c2c0fb2092228f233",
    "shipping_ledger": "76721f4244a166dca008e6cf6bcf45b00ab47ab8b0baa8ffe4b65876897eb7d2",
    "shipping_queue": "929c0b176d8f21795a52bd14504c860e260dd685804f45d0be372e31596908e7",
    "shipping_sync": "091b60be9aa359e18ce4fa3bf1035b1b3372fbdcfb20cb60e7b636ed1200c40e",
}


NAMES = sorted([*MANIFEST, BAD])


def _module(name: str):
    return importlib.import_module(f"cfg.services.{name}")


@pytest.mark.parametrize("name", NAMES)
def test_the_service_reads_every_override(name: str) -> None:
    module = _module(name)
    env = {
        module.PREFIX + "ENABLED": "false",
        module.PREFIX + "TIMEOUT_S": "45",
        module.PREFIX + "RETRIES": "7",
        module.PREFIX + "REGION": "sa-east",
    }
    settings = module.load(env)
    assert (settings.enabled, settings.timeout_s, settings.retries, settings.region) == (
        False,
        45,
        7,
        "sa-east",
    )


@pytest.mark.parametrize("name", NAMES)
def test_the_service_keeps_its_defaults(name: str) -> None:
    module = _module(name)
    settings = module.load({})
    assert settings.enabled is True
    assert settings.timeout_s == module.DEFAULT_TIMEOUT_S
    assert settings.retries == module.DEFAULT_RETRIES
    assert settings.region == module.DEFAULT_REGION


def test_no_other_module_was_edited() -> None:
    changed = [
        n
        for n, digest in MANIFEST.items()
        if hashlib.sha256((REPO / "cfg" / "services" / f"{n}.py").read_bytes()).hexdigest()
        != digest
    ]
    assert not changed, changed


def test_the_service_set_is_the_same() -> None:
    found = sorted(p.stem for p in (REPO / "cfg" / "services").glob("*.py") if p.stem != "__init__")
    assert found == NAMES


def test_the_visible_suite_is_green() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=REPO,
        env={**os.environ, "PYTHONPATH": "."},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-800:]
