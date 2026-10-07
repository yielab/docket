class DocketCli < Formula
  desc "Governed runtime and control plane for autonomous coding-agent pods"
  homepage "https://github.com/yielab/docket"
  # `version` must be declared BEFORE `url`: the url string interpolates it at class-body
  # time, and an undeclared version yields ".../download/v/docket-v.tar.gz" (404; found by the
  # first Homebrew install, 2026-10-07). Pinned by test_public_release_truth.py.
  version "0.2.0-beta.4"
  url "https://github.com/yielab/docket/releases/download/v#{version}/docket-v#{version}.tar.gz"
  # Digest of the published release asset, written by
  # scripts/update-homebrew-sha.sh AFTER the release exists -- never before.
  # It cannot be precomputed: the wheel builds byte-identically anywhere, but
  # the sdist this tarball copies does not, so a locally built digest will not
  # match the runner's bytes. Four distinct sdist digests were measured for the
  # one tagged commit; only the published one counts.
  # Pinned by test_release_artifacts.py::test_formula_digest_matches_the_published_release_asset,
  # which skips while the release is absent and fails the moment it is stale.
  sha256 "a751db7f212031813782676e012a5edbb4932ba982eeddb07cdf2ac53709376c"
  license "Apache-2.0"

  # No Homebrew Bash dependency: bin/docket, the only shell this formula
  # installs, runs on the Bash 3.2 macOS ships.
  depends_on "python@3.11"

  # The Python package is the whole product; every command dispatches to it.
  include Language::Python::Virtualenv

  def install
    # The CLI is a thin Bash launcher over the Python package; install the
    # package into an isolated venv (pulls typer/rich/pydantic/pydantic-settings/
    # filelock/pyyaml).
    venv = virtualenv_create(libexec, "python3.11")
    venv.pip_install buildpath

    # Install the launcher and point it at the venv interpreter. bin/docket
    # honors $DOCKET_PYTHON (see the launcher).
    libexec.install "bin/docket" => "docket.sh"
    (bin/"docket").write_env_script libexec/"docket.sh",
      DOCKET_PYTHON: "#{libexec}/bin/python"
  end

  def caveats
    <<~EOS
      docket needs an OpenAI-compatible chat-completions endpoint to run agent
      turns -- a hosted provider API key, or a local llama.cpp/vLLM/LM Studio
      server. It has no other external service dependency.

      Get started:
        docket init                    # run inside a codebase: sets up docket and its first pod
        docket keys add ANTHROPIC_API_KEY   # or point at a local endpoint

      See the quick-start guide:
        https://github.com/yielab/docket/blob/main/docs/QUICK-START-DOCKET.md
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/docket --version")
    assert_match "Usage", shell_output("#{bin}/docket --help", 0)
  end
end
