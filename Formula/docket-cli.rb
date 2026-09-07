class DocketCli < Formula
  desc "Governed runtime and control plane for autonomous coding-agent pods"
  homepage "https://github.com/yielab/docket"
  url "https://github.com/yielab/docket/releases/download/v#{version}/docket-v#{version}.tar.gz"
  # Digest of the published release asset, written by
  # scripts/update-homebrew-sha.sh AFTER the release exists -- never before.
  # It cannot be precomputed: the wheel builds byte-identically anywhere, but
  # the sdist this tarball copies does not, so a locally built digest will not
  # match the runner's bytes. Four distinct sdist digests were measured for the
  # one tagged commit; only the published one counts.
  # Pinned by test_release_artifacts.py::test_formula_digest_matches_the_published_release_asset,
  # which skips while the release is absent and fails the moment it is stale.
  sha256 "9f48ba443f4c5da6d79ad8071d0e236490bfc33dee725efd2ac3248091e6a955"
  license "Apache-2.0"
  version "0.2.0-beta.2"

  # Deliberately no Homebrew Bash dependency: bin/docket, the only shell this
  # formula installs, runs on the Bash 3.2 macOS ships. The dependency existed
  # for a 4.0 floor the shell surface never actually needed.
  depends_on "python@3.11"

  # fzf is optional — docket falls back to a numbered picker without it
  depends_on "fzf" => :optional

  # docket has no external daemon dependency (Phase 19 clean break) — the
  # Python package is the whole product; every command dispatches to it.
  include Language::Python::Virtualenv

  def install
    # The CLI is a thin Bash launcher over the Python package; install the
    # package into an isolated venv (pulls typer/rich/pydantic/filelock).
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
        docket install                 # bootstrap docket's home + specialist agents
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
