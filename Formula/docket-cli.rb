class DocketCli < Formula
  # The Python package is the whole product; every command dispatches to it.
  include Language::Python::Virtualenv

  desc "Governed runtime and control plane for autonomous coding-agent pods"
  homepage "https://github.com/yielab/docket"
  # The version is written into the URL literally and Homebrew reads it from there;
  # scripts/update-homebrew-sha.sh rewrites both occurrences at release time. Never
  # interpolate `#{version}` here: it is evaluated while the class body runs, before any
  # `version` line below it exists, and resolves to ".../download/v/docket-v.tar.gz".
  url "https://github.com/yielab/docket/releases/download/v0.2.0-beta.4/docket-v0.2.0-beta.4.tar.gz"
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
  depends_on "rust" => :build # pydantic-core builds from its sdist
  depends_on "libyaml"
  depends_on "python@3.11"

  # Homebrew's pip runs with --no-deps, so every runtime dependency of the
  # package (pyproject.toml [project] dependencies and their closure) must be a
  # resource here or the installed `docket` dies on `import typer` (found by the
  # first Homebrew install, 2026-10-07). Regenerate with
  #   brew update-python-resources --print-only --ignore-non-pypi-packages \
  #     --extra-packages typer,rich,pydantic,pydantic-settings,filelock,pyyaml \
  #     yielab/docket-cli/docket-cli
  # scripts/update-homebrew-sha.sh rewrites only the FIRST sha256 (the asset).
  resource "annotated-doc" do
    url "https://files.pythonhosted.org/packages/5a/8e/38aa427ed5402449e226975b649c5dc73ccadfefeb95e6aecb8f8ea4b6b6/annotated_doc-0.0.5.tar.gz"
    sha256 "c7e58ce09192557605d8bbd92836d7e1d520ac9580096042c0bfd197efacf1bb"
  end

  resource "annotated-types" do
    url "https://files.pythonhosted.org/packages/5f/56/a8120250d128bed162cd73c76d45f6ef9991f3e068f62a8ee060afa3104a/annotated_types-0.8.0.tar.gz"
    sha256 "13b2beaad985e05e2d6407ee4c4f35590b11f8d693a258a561055cac8f64cab7"
  end

  resource "filelock" do
    url "https://files.pythonhosted.org/packages/53/e4/34efcb869715cf299e47d1ac7b2624d2bcb6f2d3dffc2f0abe8417f65ab2/filelock-4.0.12.tar.gz"
    sha256 "cf42711a7ac791818b299fab0332a088c65aeeefa36290de98db92c434303b0c"
  end

  resource "markdown-it-py" do
    url "https://files.pythonhosted.org/packages/06/ff/7841249c247aa650a76b9ee4bbaeae59370dc8bfd2f6c01f3630c35eb134/markdown_it_py-4.2.0.tar.gz"
    sha256 "04a21681d6fbb623de53f6f364d352309d4094dd4194040a10fd51833e418d49"
  end

  resource "mdurl" do
    url "https://files.pythonhosted.org/packages/d6/54/cfe61301667036ec958cb99bd3efefba235e65cdeb9c84d24a8293ba1d90/mdurl-0.1.2.tar.gz"
    sha256 "bb413d29f5eea38f31dd4754dd7377d4465116fb207585f97bf925588687c1ba"
  end

  resource "pydantic" do
    url "https://files.pythonhosted.org/packages/53/ef/fc4f868f4e2cee79f863883abffceff107875f569b848507319842d2a681/pydantic-2.13.5.tar.gz"
    sha256 "51a9c5f7b2f8e636f04c6cada605d9b6a3bf1348fdf945a3d8869b19bba0ee08"
  end

  resource "pydantic-core" do
    url "https://files.pythonhosted.org/packages/af/f9/8a06bea35ef8daf588f707784c973a7046e0034c8d8cfb08828eeffb8b75/pydantic_core-2.46.5.tar.gz"
    sha256 "10416c15b8839ecc4ef4d0885da76da6fd0f67333a0eb8aff6d93c4b8f2910fc"
  end

  resource "pydantic-settings" do
    url "https://files.pythonhosted.org/packages/68/ca/31c57507b13119d7d3cfa1576dad2911a4861e3be07b579395f4e9d393f9/pydantic_settings-2.15.0.tar.gz"
    sha256 "694b793e84f766ba76a90ebdefc01d0a9a045dab0382bee70393da93712ad117"
  end

  resource "pygments" do
    url "https://files.pythonhosted.org/packages/49/2e/ced460408999b33da6b31b0021b0f37d329e202d4169aeb164493778f25b/pygments-2.21.0.tar.gz"
    sha256 "610ca751c9bc2492b38eb9a38a7fbc93edbbb2d7182edaf34e66ae493dee5c8c"
  end

  resource "python-dotenv" do
    url "https://files.pythonhosted.org/packages/74/26/2fbeedb218a787a5eea551c7532cac4e009f83d689dd2faa0d0353473f86/python_dotenv-1.2.4.tar.gz"
    sha256 "f0d53e69935a851c0dcc78f3ab7aaccd8cabef0b92382b576b824212902873c0"
  end

  resource "pyyaml" do
    url "https://files.pythonhosted.org/packages/05/8e/961c0007c59b8dd7729d542c61a4d537767a59645b82a0b521206e1e25c2/pyyaml-6.0.3.tar.gz"
    sha256 "d76623373421df22fb4cf8817020cbb7ef15c725b9d5e45f17e189bfc384190f"
  end

  resource "rich" do
    url "https://files.pythonhosted.org/packages/c0/8f/0722ca900cc807c13a6a0c696dacf35430f72e0ec571c4275d2371fca3e9/rich-15.0.0.tar.gz"
    sha256 "edd07a4824c6b40189fb7ac9bc4c52536e9780fbbfbddf6f1e2502c31b068c36"
  end

  resource "shellingham" do
    url "https://files.pythonhosted.org/packages/58/15/8b3609fd3830ef7b27b655beb4b4e9c62313a4e8da8c676e142cc210d58e/shellingham-1.5.4.tar.gz"
    sha256 "8dbca0739d487e5bd35ab3ca4b36e11c4078f3a234bfce294b0a0291363404de"
  end

  resource "typer" do
    url "https://files.pythonhosted.org/packages/16/f7/57713ba479fd405eb76de31404b2c744c289e336b2d999511ebf51e496f7/typer-0.27.2.tar.gz"
    sha256 "269b7eb9d3c202ca84b4bc9618cb04ebb43d3d4d1e567e4c768607232c05f945"
  end

  resource "typing-extensions" do
    url "https://files.pythonhosted.org/packages/f6/cc/6253133b5bb138fc3306cebfbda2c520f545d36b5be2c7255cc528bb45d6/typing_extensions-4.16.0.tar.gz"
    sha256 "dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5"
  end

  resource "typing-inspection" do
    url "https://files.pythonhosted.org/packages/a3/26/b09b8010994eccc3c09092e6b34058f36a460eea2d4c3e8b910c695975a0/typing_inspection-0.4.4.tar.gz"
    sha256 "547274fa6b0a561ccf549cc9524b999a578e737d015d8709d021f9d0d13bea47"
  end

  def install
    # The CLI is a thin Bash launcher over the Python package; install the
    # vendored dependencies and then the package into an isolated venv.
    venv = virtualenv_create(libexec, "python3.11")
    venv.pip_install resources
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
    # The package reports its PEP 440 form: `0.2.0-beta.4` installs as `0.2.0b4`.
    tags = { "alpha" => "a", "beta" => "b", "rc" => "rc" }
    pep440 = version.to_s.sub(/-(alpha|beta|rc)\.?(\d+)\z/) do
      tags[Regexp.last_match(1)] + Regexp.last_match(2)
    end
    assert_match pep440, shell_output("#{bin}/docket --version")
    assert_match "Usage", shell_output("#{bin}/docket --help")
  end
end
