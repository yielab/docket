class DocketCli < Formula
  desc "CLI for managing OpenClaw autonomous agent deployments"
  homepage "https://github.com/santiagoyie/docket-cli"
  url "https://github.com/santiagoyie/docket-cli/archive/refs/tags/v#{version}.tar.gz"
  # sha256 is updated automatically by the release workflow (scripts/update-homebrew-sha.sh)
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  version "0.1.0"

  # macOS ships with Bash 3.2 (GPL-3 license change); docket requires 4.0+
  depends_on "bash"
  depends_on "python@3"

  # fzf is optional — docket falls back to a numbered picker without it
  depends_on "fzf" => :optional

  def install
    # Keep the relative bin/../lib layout so the entry point can resolve its modules
    prefix.install "lib"
    bin.install "bin/docket"
  end

  def caveats
    <<~EOS
      docket requires the OpenClaw daemon and openclaw CLI to be installed separately.
      See the quick-start guide for setup instructions:
        https://github.com/santiagoyie/docket-cli/blob/main/docs/QUICK-START-DOCKET.md

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
