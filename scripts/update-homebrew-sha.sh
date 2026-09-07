#!/usr/bin/env bash
# Update the SHA256 checksum in Formula/docket-cli.rb from a PUBLISHED release.
# Usage: ./scripts/update-homebrew-sha.sh v0.2.0
#
# Run this AFTER the release workflow has published the tag's assets: it reads
# the digest off the release itself, so there is nothing to read before then.
# The digest is also not reproducible off the release runner -- the wheel is
# byte-identical everywhere, the sdist this tarball copies is not -- so the pin
# genuinely cannot be computed ahead of the release.
set -euo pipefail

version="${1:?Usage: $0 <version-tag>   e.g. v0.2.0}"
version="${version#v}"  # strip leading 'v' if present

repo="yielab/docket"
tarball_url="https://github.com/${repo}/releases/download/v${version}/docket-v${version}.tar.gz"
formula="Formula/docket-cli.rb"

[[ -f "$formula" ]] || { echo "Error: $formula not found (run from repo root)"; exit 1; }

echo "Downloading tarball to compute SHA256..."
sha=$(curl -fsSL "$tarball_url" | sha256sum | awk '{print $1}')

echo "SHA256: $sha"
echo "Updating $formula..."

portable_sed_i() {
  local expr="$1" file="$2"
  if sed --version 2>/dev/null | grep -q GNU; then
    sed -i "$expr" "$file"
  else
    sed -i '' "$expr" "$file"
  fi
}

portable_sed_i "s|sha256 \"[0-9a-f]*\"|sha256 \"${sha}\"|" "$formula"
portable_sed_i "s|version \"[^\"]*\"|version \"${version}\"|" "$formula"

echo "Done. Commit the updated formula; it necessarily lands after the tag."
