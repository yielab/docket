class RackCli < Formula
  desc "CLI for managing OpenClaw autonomous agent deployments"
  homepage "https://github.com/santiagoyie/rack-cli"
  url "https://github.com/santiagoyie/rack-cli/archive/refs/tags/v#{version}.tar.gz"
  # sha256 is updated automatically by the release workflow (scripts/update-homebrew-sha.sh)
  sha256 "0000000000000000000000000000000000000000000000000000000000000000"
  license "MIT"
  version "0.1.0"

  # macOS ships with Bash 3.2 (GPL-3 license change); rack requires 4.0+
  depends_on "bash"
  depends_on "python@3"

  # fzf is optional — rack falls back to a numbered picker without it
  depends_on "fzf" => :optional

  def install
    # Keep the relative bin/../lib layout so the entry point can resolve its modules
    prefix.install "lib"
    bin.install "bin/rack"
  end

  def caveats
    <<~EOS
      rack requires the OpenClaw daemon and openclaw CLI to be installed separately.
      See the quick-start guide for setup instructions:
        https://github.com/santiagoyie/rack-cli/blob/main/docs/QUICK-START-RACK.md

      OpenClaw uses the system Python (python3) for JSON operations. If your system
      Python is < 3.8 you may need to set PYTHON3 to the Homebrew python path:
        export PYTHON3="#{Formula["python@3"].opt_bin}/python3"
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/rack --version")
    assert_match "Usage", shell_output("#{bin}/rack --help", 0)
  end
end
