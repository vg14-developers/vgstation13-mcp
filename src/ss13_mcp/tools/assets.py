import base64
import json
import mimetypes
from pathlib import Path

from ss13_mcp import cache, dmi, licenses, rsi, snapshot
from ss13_mcp.setup import KNOWN_FORKS
from ss13_mcp.snapshot import ss13_dir


def _resolve(path: str) -> Path:
    root = ss13_dir().resolve()
    target = (root / path).resolve()
    if root not in target.parents and target != root:
        raise ValueError(f"path outside SS13 checkout: {path}")
    return target


def read_asset(path: str) -> dict:
    target = _resolve(path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(path)
    data = target.read_bytes()
    mime, _ = mimetypes.guess_type(str(target))
    if path.endswith(".dmi"):
        mime = "image/png"
    return {
        "size": len(data),
        "mime": mime or "application/octet-stream",
        "bytes_b64": base64.b64encode(data).decode("ascii"),
    }


def list_dmi_states(dmi_path: str) -> list[dict]:
    target = _resolve(dmi_path)
    if not target.exists():
        raise FileNotFoundError(dmi_path)
    return dmi.list_states(target)


def _owner_repo(cfg: dict) -> str | None:
    """Resolve <owner>/<repo> from config: stored repo_url first, then fork map."""
    url = cfg.get("repo_url")
    if not url:
        url = KNOWN_FORKS.get(cfg.get("fork"))
    return licenses.owner_repo_from_url(url)


def _resolve_repo(cfg: dict) -> tuple[str | None, str]:
    """Return (owner_repo_or_None, sha) from a loaded config."""
    return _owner_repo(cfg), (cfg.get("ss13_sha") or "unknown")


def _attribution_for_path(owner_repo: str | None, sha: str, dmi_path: str) -> dict:
    """Resolve repo/license/copyright/source_url for one DMI path."""
    if owner_repo is None:
        return {
            "repo": "(unknown)",
            "resolved_license": None,
            "resolved_class": "(unknown)",
            "copyright": "Ported from SS13",
            "source_url": None,
        }
    attr = licenses.attribution(owner_repo, sha, dmi_path)
    return {
        "repo": owner_repo,
        "resolved_license": attr.resolved_license,
        "resolved_class": attr.resolved_class,
        "copyright": attr.copyright,
        "source_url": attr.source_url,
    }


def _attribution_for(dmi_path: str) -> dict:
    """Resolve repo/license/copyright/source_url for one DMI path (loads config)."""
    cfg = snapshot.load_config()
    owner_repo, sha = _resolve_repo(cfg)
    return _attribution_for_path(owner_repo, sha, dmi_path)


def preview_asset_licenses(dmi_paths: list[str]) -> dict:
    """Resolve licenses for a batch WITHOUT converting, grouped by license.

    Lets the agent show one consolidated approval prompt for many assets.
    """
    cfg = snapshot.load_config()
    owner_repo, sha = _resolve_repo(cfg)
    approvals = snapshot.load_approvals()
    repo = None
    groups: dict[str, dict] = {}
    for p in dmi_paths:
        info = _attribution_for_path(owner_repo, sha, p)
        repo = info["repo"]
        cls = info["resolved_class"]
        g = groups.setdefault(
            cls,
            {
                "count": 0,
                "approved": cls in approvals.get(info["repo"], {}),
                "paths": [],
            },
        )
        g["count"] += 1
        g["paths"].append(p)
    return {
        "repo": repo,
        "groups": groups,
        "instructions": (
            "Show the user this per-license breakdown and ask for ONE approval "
            "covering all not-yet-approved groups. Then convert each file with "
            "license_confirmed=true (and license_override=<id> for any group the "
            "user corrects). Approved groups need no further prompting, now or in "
            "future sessions."
        ),
    }


def convert_dmi(
    dmi_path: str,
    state: str | None = None,
    *,
    license_confirmed: bool = False,
    license_override: str | None = None,
) -> dict:
    target = _resolve(dmi_path)
    if not target.exists():
        raise FileNotFoundError(dmi_path)

    info = _attribution_for(dmi_path)
    repo = info["repo"]
    resolved_class = info["resolved_class"]
    copyright = info["copyright"]

    # Decide the effective license and whether we may write.
    force_rewrite = False
    if license_confirmed and license_override is not None:
        effective = license_override
        snapshot.record_approval(repo, resolved_class, effective)
        force_rewrite = True
    elif snapshot.is_license_approved(repo, resolved_class):
        effective = snapshot.approved_license(repo, resolved_class)
    elif license_confirmed:
        effective = info["resolved_license"]
        snapshot.record_approval(repo, resolved_class, effective)
    else:
        states = [s["name"] for s in dmi.list_states(target)]
        return {
            "status": "needs_license_approval",
            "dmi_path": dmi_path,
            "repo": repo,
            "source_url": info["source_url"],
            "resolved_license": info["resolved_license"],
            "resolved_class": resolved_class,
            "effective_license": license_override
            if license_override is not None
            else info["resolved_license"],
            "copyright": copyright,
            "states": states,
            "instructions": (
                "This license class is not yet approved. Approving it (re-call with "
                "license_confirmed=true) applies to ALL assets in this repo that "
                "resolve to the same license, now and in future sessions — you will "
                "not be prompted again for it. If it is wrong or unknown "
                "(resolved_license is null), re-call with license_override='<SPDX/CC "
                "id>' and license_confirmed=true. For a multi-file batch, call "
                "preview_asset_licenses first and ask the user once. Do NOT write "
                "assets without explicit human approval."
            ),
        }

    slot = cache.slot(dmi_path, state)
    hit = cache.is_hit(dmi_path, state)

    if not hit or force_rewrite:
        parsed = dmi.load_dmi(target)
        slot.mkdir(parents=True, exist_ok=True)
        rsi.write_rsi(parsed, slot, state_filter=state, license=effective, copyright=copyright)
        cache.evict_if_needed()

    cache.touch(dmi_path, state)

    meta = json.loads((slot / "meta.json").read_text())
    return {
        "rsi_path": str(slot),
        "states": [s["name"] for s in meta["states"]],
        "url": None,
        "cache_hit": hit and not force_rewrite,
        "license": meta.get("license"),
        "source_url": info["source_url"],
    }
