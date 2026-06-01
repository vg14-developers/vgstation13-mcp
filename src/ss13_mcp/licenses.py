"""Resolve SS14 RSI asset licenses from a source path.

Mirrors space-wizards/RSIEdit's license resolution. The bundled
``data/repository-licenses.json`` is a verbatim copy of
https://github.com/space-wizards/RSIEdit/blob/master/Editor/Assets/repository-licenses.json
(copied 2026-06-01). It maps ordered, anchored regexes over GitHub blob paths
(``<owner>/<repo>/blob/<ref>/<path>``) to license ids; the first matching
pattern wins, so path-specific entries must precede the general repo entry.
When nothing matches we return ``None`` and never fabricate a license.
"""

import json
import re
from dataclasses import dataclass
from importlib import resources


def _load_patterns() -> list[tuple[re.Pattern[str], str]]:
    text = (
        resources.files("ss13_mcp")
        .joinpath("data/repository-licenses.json")
        .read_text(encoding="utf-8")
    )
    data = json.loads(text)  # dict preserves file order (Python 3.7+)
    return [(re.compile(pattern), lic) for pattern, lic in data.items()]


try:
    _PATTERNS = _load_patterns()
except FileNotFoundError as exc:  # pragma: no cover - packaging guard
    raise RuntimeError(
        "ss13_mcp: bundled data/repository-licenses.json is missing from the "
        "installed package"
    ) from exc


def resolve_license(blob_path: str) -> str | None:
    """First-match-wins over the ordered regex map; None if nothing matches."""
    for pattern, lic in _PATTERNS:
        if pattern.search(blob_path):
            return lic
    return None


def owner_repo_from_url(url: str | None) -> str | None:
    """Extract ``<owner>/<repo>`` from an https or scp-style git URL."""
    if not url:
        return None
    u = url.strip()
    if u.endswith(".git"):
        u = u[:-4]
    if "://" in u:
        rest = u.split("://", 1)[1]
        u = rest.split("/", 1)[1] if "/" in rest else ""
    elif ":" in u and "@" in u:  # scp-like: git@host:owner/repo
        u = u.split(":", 1)[1]
    u = u.split("?", 1)[0].split("#", 1)[0]
    parts = [p for p in u.split("/") if p]
    if len(parts) < 2:
        return None
    return "/".join(parts[:2])


@dataclass
class Attribution:
    source_url: str
    copyright: str
    resolved_license: str | None
    resolved_class: str


def attribution(owner_repo: str, sha: str, rel_path: str) -> Attribution:
    """Resolve license + build the source URL / copyright for one DMI."""
    rel = rel_path.replace("\\", "/").lstrip("/")
    source_url = f"https://github.com/{owner_repo}/blob/{sha}/{rel}"
    repo = owner_repo.rsplit("/", 1)[-1]
    lic = resolve_license(f"{owner_repo}/blob/{sha}/{rel}")
    return Attribution(
        source_url=source_url,
        copyright=f"Taken from {repo} at {source_url}",
        resolved_license=lic,
        resolved_class=lic or "(unknown)",
    )
