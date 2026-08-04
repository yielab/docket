class DocketCli < Formula
  desc "Governed runtime and control plane for autonomous coding-agent pods"
  homepage "https://github.com/yielab/docket"
  url "https://github.com/yielab/docket/archive/refs/tags/v#{version}.tar.gz"
  # sha256 is updated automatically by the release workflow (scripts/update-homebrew-sha.sh)
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  # NOTE (repo hygiene pass): the only tags that exist today are v0.1.0 and
  # v0.2.0-beta.1 -- pin here MUST be a real tag or `brew install` 404s on the
  # url above. Do not bump this past the newest real tag speculatively; run
  # scripts/update-homebrew-sha.sh <tag> after cutting a new release tag instead.
  version "0.2.0-beta.1"

  # macOS ships with Bash 3.2 (GPL-3 license change); docket requires 4.0+
  depends_on "bash"
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
