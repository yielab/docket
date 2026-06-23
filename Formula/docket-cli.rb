class DocketCli < Formula
  desc "CLI for managing OpenClaw autonomous agent deployments"
  homepage "https://github.com/yielab/docket"
  url "https://github.com/yielab/docket/archive/refs/tags/v#{version}.tar.gz"
  # sha256 is updated automatically by the release workflow (scripts/update-homebrew-sha.sh)
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  version "0.1.0"

  # macOS ships with Bash 3.2 (GPL-3 license change); docket requires 4.0+
  depends_on "bash"
  depends_on "python@3.11"

  # fzf is optional — docket falls back to a numbered picker without it
  depends_on "fzf" => :optional

  # Python core (M1+): every command except `install` dispatches to the Python
  # package, so it must be installed alongside the thin Bash bootstrap.
  include Language::Python::Virtualenv

  def install
    # Thin Bash bootstrap: the launcher + sourced modules (resolves <prefix>/lib).
    prefix.install "lib"

    # Python core in an isolated venv (pulls typer/rich/pydantic/filelock).
    venv = virtualenv_create(libexec, "python3.11")
    venv.pip_install buildpath

    # Install the launcher and point its Python dispatcher at the venv. bin/docket
    # honors $DOCKET_PYTHON (see the dispatcher seam) and $DOCKET_LIB_DIR.
    libexec.install "bin/docket" => "docket.sh"
    (bin/"docket").write_env_script libexec/"docket.sh",
      DOCKET_PYTHON:  "#{libexec}/bin/python",
      DOCKET_LIB_DIR: "#{prefix}/lib"
  end

  def caveats
    <<~EOS
      docket requires the OpenClaw daemon and openclaw CLI to be installed separately.
      See the quick-start guide for setup instructions:
        https://github.com/yielab/docket/blob/main/docs/QUICK-START-DOCKET.md

      OpenClaw uses the system Python (python3) for JSON operations. If your system
      Python is < 3.8 you may need to set PYTHON3 to the Homebrew python path:
        export PYTHON3="#{Formula["python@3"].opt_bin}/python3"
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/docket --version")
    assert_match "Usage", shell_output("#{bin}/docket --help", 0)
  end
end
