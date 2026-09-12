"""mkdocs build hooks for the docket documentation site (W31-C6 / D-36).

W31-C6 owns `mkdocs.yml` and `docs/commands.md` only -- it may not add,
move, or symlink files under `docs/`, and `specs/**`, `README.md`, and every
other repository doc are someone else's tree entirely. Two problems follow
from that, and both are solved here without editing anything this card does
not own:

1. **Three fixed-nav entries live outside `docs_dir`.** The nav this card
   specifies (ROADMAP D-36) names the spec index (`specs/README.md`), the
   changelog (`CHANGELOG.md`), and the `docket-runtime` API page
   (`packages/docket-runtime/docs/api.md`) -- none of them under `docs/`.
   MkDocs refuses a `docs_dir` that is an ancestor of the config file's own
   directory, so `docs_dir: ..` (the repository root) is not an option;
   `on_files` below adds these three as generated `File`s instead, read
   directly from their real location, at the site path their own relative
   links expect.

2. **Every existing doc's relative links were authored for a repository
   browser, not a `docs_dir`-scoped site.** `docs/DOCKET.md` links
   `../README.md`; `docs/cycles-ended/README.md` links `todo-waves.md`
   (fine on GitHub, both real repository-relative paths) -- but under
   `docs_dir: docs`, MkDocs resolves a link relative to the *page's
   position inside docs_dir*, not its real filesystem position, so
   `../README.md` from a page sitting directly in `docs/` resolves to
   nothing MkDocs knows about. `on_page_markdown` below rewrites exactly
   the links MkDocs cannot resolve into absolute GitHub blob links, but
   only when the target genuinely exists on disk -- computed from the
   *real* file location, matching how these links were actually authored.
   A link to something that does not exist anywhere is left broken, so a
   genuinely dead link still fails `--strict` (this is what makes planting
   one in a test still work as a regression check on this file).
"""

from __future__ import annotations

import posixpath
import re
from pathlib import Path
from typing import TYPE_CHECKING

from mkdocs.structure.files import File, Files

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.pages import Page

ROOT = Path(__file__).resolve().parent.parent
REPO_BLOB_BASE = "https://github.com/yielab/docket/blob/main/"

# (site src_uri, real path on disk) -- content this card's fixed nav must
# reference from outside docs_dir. See module docstring, problem 1.
_EXTERNAL_FILES = (
    ("specs/README.md", ROOT / "specs" / "README.md"),
    ("CHANGELOG.md", ROOT / "CHANGELOG.md"),
    (
        "packages/docket-runtime/docs/api.md",
        ROOT / "packages" / "docket-runtime" / "docs" / "api.md",
    ),
)


def on_files(files: Files, *, config: MkDocsConfig) -> Files:
    for src_uri, real_path in _EXTERNAL_FILES:
        files.append(File.generated(config, src_uri, abs_src_path=str(real_path)))
    return files


# Matches `[label](target)` and `![label](target)`. Deliberately simple (no
# nested-paren handling) -- adequate for this repository's existing docs,
# all of which use plain, paren-free relative paths and URLs.
_LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")


def _target_uri(src_uri: str, href_path: str) -> str:
    """Mirror MkDocs' own `_RelativePathTreeprocessor._target_uri`."""
    return posixpath.normpath(posixpath.join(posixpath.dirname(src_uri), href_path).lstrip("/"))


def on_page_markdown(markdown: str, *, page: Page, config: MkDocsConfig, files: Files) -> str:
    def _rewrite(match: re.Match[str]) -> str:
        prefix, href, suffix = match.group(1), match.group(2), match.group(3)

        if re.match(r"^[a-z][a-z0-9+.-]*:", href, flags=re.IGNORECASE):
            return match.group(0)  # already absolute (http:, mailto:, ...)
        if href.startswith("#") or href.endswith("/"):
            return match.group(0)  # pure anchor, or a directory-style link

        path_part, _, anchor = href.partition("#")
        if not path_part:
            return match.group(0)

        if files.get_file_from_path(_target_uri(page.file.src_uri, path_part)) is not None:
            return match.group(0)  # MkDocs can already resolve this one

        # Unresolvable inside the site. Try the *real* filesystem location
        # the link was actually authored against.
        assert page.file.abs_src_path is not None
        real_target = (Path(page.file.abs_src_path).parent / path_part).resolve()
        try:
            repo_relative = real_target.relative_to(ROOT)
        except ValueError:
            return match.group(0)  # outside the repo entirely -- leave it
        if not real_target.exists():
            return match.group(0)  # genuinely missing -- let --strict catch it

        blob_url = REPO_BLOB_BASE + repo_relative.as_posix()
        if anchor:
            blob_url += f"#{anchor}"
        return f"{prefix}{blob_url}{suffix}"

    return _LINK_RE.sub(_rewrite, markdown)
