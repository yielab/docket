class DocketCli < Formula
  desc "Governed runtime and control plane for autonomous coding-agent pods"
  homepage "https://github.com/yielab/docket"
  url "https://github.com/yielab/docket/releases/download/v#{version}/docket-v#{version}.tar.gz"
  # Exact digest reported by the immutable GitHub release asset.
  sha256 "7ca506cf69d3fecf57a6fefa9b5ce299112855888a88018fa312ee393724766c"
  license "Apache-2.0"
  # This pin is updated only by the approved release cut after the immutable
  # versioned asset has been built and its digest verified.
  version "0.2.0-beta.2"

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
