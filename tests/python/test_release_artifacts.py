"""Release assets are immutable, verified, and protected before publication."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
FORMULA = ROOT / "Formula" / "docket-cli.rb"
INSTALLER = ROOT / "install.sh"


def test_release_workflow_builds_verifiable_package_assets() -> None:
    """The tag workflow must produce packages plus verification evidence."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "uv build" in workflow
    assert re.search(r"dist/.*\.whl", workflow)
    assert re.search(r"dist/.*\.tar\.gz", workflow)
    assert "sha256" in workflow.lower()
    assert "sbom" in workflow.lower()
    assert "attest-build-provenance" in workflow


def test_release_publication_is_a_protected_build_consumer() -> None:
    """Publishing cannot run in the same unprotected job that creates bytes."""
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    jobs = document["jobs"]

    assert "build" in jobs
    assert "publish" in jobs
    publish = jobs["publish"]
    needs = publish.get("needs", [])
    assert "build" in ([needs] if isinstance(needs, str) else needs)
    assert publish.get("environment") == "release"
    assert publish.get("permissions", {}).get("contents") == "write"
    assert publish.get("permissions", {}).get("id-token") == "write"


def test_publish_job_resolves_the_repository_without_a_checkout() -> None:
    """`gh` cannot infer a repository in a job that never checks out source.

    The publish job downloads `build`'s verified bytes and nothing else -- that
    is the property `test_release_publication_is_a_protected_build_consumer`
    exists to keep. The cost of it is that there is no git remote for `gh` to
    read, so an implicit `gh release create` dies with
    `failed to run git: fatal: not a git repository` after the attestation has
    already been produced. The repository must be named explicitly.
    """
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    publish = document["jobs"]["publish"]
    steps = publish["steps"]

    assert not any("checkout" in str(step.get("uses", "")) for step in steps), (
        "the publish job must not check out source; keep it a consumer of build's bytes"
    )

    release_steps = [step for step in steps if "gh release create" in str(step.get("run", ""))]
    assert release_steps, "the publish job no longer creates a GitHub release"
    for step in release_steps:
        explicit_flag = "--repo" in step["run"]
        explicit_env = "GH_REPO" in (step.get("env") or {})
        assert explicit_flag or explicit_env, (
            "gh release create must name the repository (--repo or GH_REPO): "
            "there is no checkout for it to infer one from"
        )


def test_formula_uses_the_release_asset_and_apache_metadata() -> None:
    formula = FORMULA.read_text(encoding="utf-8")

    assert "releases/download/v#{version}/docket-v#{version}.tar.gz" in formula
    assert 'license "Apache-2.0"' in formula
    checksum = re.search(r'^\s*sha256 "([0-9a-f]{64})"', formula, re.MULTILINE)
    assert checksum is not None
    assert checksum.group(1) != "0" * 64


RELEASE_ASSET_SIDECAR = (
    "https://github.com/yielab/docket/releases/download/v{version}/docket-v{version}.tar.gz.sha256"
)


def test_formula_digest_matches_the_published_release_asset() -> None:
    """The formula must pin the digest of the asset users will actually download.

    This cannot be precomputed. The wheel builds byte-identically anywhere, but
    the sdist -- which is what `docket-v<version>.tar.gz` is a copy of -- does
    not: the same tagged commit produced three different sdist digests on a
    developer machine, on the release runner, and in the pin committed with the
    tag. Only the runner's bytes ever become the release asset, so the pin can
    only be written afterwards, with `scripts/update-homebrew-sha.sh`.

    Reads the tiny `.sha256` sidecar rather than the multi-megabyte tarball; the
    release workflow generates both from the same bytes and `sha256sum --check`s
    them in the build job and again in publish.
    """
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    pinned = re.search(r'^\s*sha256 "([0-9a-f]{64})"', FORMULA.read_text(encoding="utf-8"), re.M)
    assert pinned is not None, "the formula lost its sha256 pin"

    url = RELEASE_ASSET_SIDECAR.format(version=version)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            sidecar = response.read().decode()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            pytest.skip(
                f"release v{version} is not published yet; the formula pin is "
                "unverifiable until it is, and must then be refreshed with "
                "scripts/update-homebrew-sha.sh"
            )
        raise
    except urllib.error.URLError as error:  # pragma: no cover - offline environments
        pytest.skip(f"cannot reach the release asset sidecar: {error}")

    published = sidecar.split()[0]
    assert pinned.group(1) == published, (
        f"Formula/docket-cli.rb pins {pinned.group(1)} but the published "
        f"v{version} asset is {published}; run scripts/update-homebrew-sha.sh v{version}"
    )


def test_remote_installer_uses_a_versioned_verified_asset() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")

    assert "/archive/refs/heads/main" not in installer
    assert "/releases/download/" in installer
    assert ".sha256" in installer


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_remote_installer(
    tmp_path: Path, *, payload: bytes, trusted: bytes
) -> tuple[int, str, bool]:
    remote = tmp_path / "remote"
    fake_bin = tmp_path / "fake-bin"
    prefix = tmp_path / "prefix"
    remote.mkdir()
    fake_bin.mkdir()
    shutil.copy2(INSTALLER, remote / "install.sh")
    payload_path = tmp_path / "payload.tar.gz"
    payload_path.write_bytes(payload)
    tar_marker = tmp_path / "tar-called"

    _write_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
output=""
url=""
while (($#)); do
  case "$1" in
    -o|--output) output="$2"; shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
if [[ "$url" == *.sha256 ]]; then
  asset_name="${url##*/}"
  body="${TRUSTED_SHA}  ${asset_name%.sha256}"
else
  body="$(cat "$PAYLOAD_PATH")"
fi
if [[ -n "$output" ]]; then
  printf '%s' "$body" > "$output"
else
  printf '%s' "$body"
fi
""",
    )
    _write_executable(
        fake_bin / "tar",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'called' > "$TAR_MARKER"
exit 23
""",
    )
    _write_executable(
        fake_bin / "python3",
        """#!/usr/bin/env bash
exit 0
""",
    )
    env = {
        **os.environ,
        "DOCKET_PREFIX": str(prefix),
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PAYLOAD_PATH": str(payload_path),
        "TAR_MARKER": str(tar_marker),
        "TRUSTED_SHA": hashlib.sha256(trusted).hexdigest(),
    }
    completed = subprocess.run(
        ["bash", str(remote / "install.sh")],
        cwd=remote,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr, tar_marker.exists()


def test_valid_checksum_reaches_extraction(tmp_path: Path) -> None:
    payload = b"trusted release bytes"

    _returncode, _output, extracted = _run_remote_installer(
        tmp_path, payload=payload, trusted=payload
    )

    assert extracted is True


def test_tampered_asset_is_rejected_before_extraction(tmp_path: Path) -> None:
    returncode, output, extracted = _run_remote_installer(
        tmp_path,
        payload=b"trusted release bytes with one changed byte",
        trusted=b"trusted release bytes",
    )

    assert returncode != 0
    assert "checksum" in output.lower()
    assert extracted is False
