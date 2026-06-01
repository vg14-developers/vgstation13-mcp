"""Setup tool exposed via MCP.

Flow: the agent asks the user which SS13 fork they want to work with and
where their checkout lives (or where they'd like one cloned), then invokes
`setup(ss13_path=..., fork=..., repo_url=...)`. This validates or clones
the repo, downloads the matching dmm-tools binary, builds the DM type
index, and writes a small config so future tool calls know where to look.

Idempotent: re-running with the same ss13_path is a no-op unless force=true.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from ss13_mcp.snapshot import config_path, snapshot_dir, write_config

log = logging.getLogger(__name__)

# We ship our own type-tree dumper (built from the dreammaker parser crate)
# because upstream SpacemanDMM doesn't expose a `dump-types` subcommand. See
# dm-dump/ in this repo and issue #16.
DM_DUMP_RELEASE = "dm-dump-v0.2.0"
DM_DUMP_REPO = "vg14-developers/ss13-mcp"

# Short identifiers for well-known SS13 forks. Pass `fork="<key>"` to setup()
# instead of spelling out the full repo_url. Add new entries here as forks
# get exercised. Order matters for documentation only.
KNOWN_FORKS: dict[str, str] = {
    "vg": "https://github.com/vgstation-coders/vgstation13.git",
    "tg": "https://github.com/tgstation/tgstation.git",
    "paradise": "https://github.com/ParadiseSS13/Paradise.git",
    "bay": "https://github.com/Baystation12/Baystation12.git",
    "goon": "https://github.com/goonstation/goonstation.git",
    "cm": "https://github.com/cmss13-devs/cmss13.git",
}


def _step(msg: str) -> None:
    print(f"[setup] {msg}", file=sys.stderr, flush=True)


def _dm_dump_url() -> tuple[str, str]:
    """Return (download_url, local_filename) for the current platform's dm-dump."""
    sysname = platform.system().lower()
    machine = platform.machine().lower()
    base = f"https://github.com/{DM_DUMP_REPO}/releases/download/{DM_DUMP_RELEASE}"
    if sysname == "windows" and machine in {"x86_64", "amd64"}:
        return f"{base}/dm-dump-x86_64-pc-windows-msvc.exe", "dm-dump.exe"
    if sysname == "linux" and machine in {"x86_64", "amd64"}:
        return f"{base}/dm-dump-x86_64-unknown-linux-gnu", "dm-dump"
    raise RuntimeError(
        f"no prebuilt dm-dump for {sysname}/{machine}. Build it from source: "
        f"`cargo build --release --manifest-path dm-dump/Cargo.toml` in a "
        f"clone of https://github.com/{DM_DUMP_REPO}, then set SS13_DM_DUMP_PATH "
        "to the resulting binary."
    )


def _download(url: str, dest: Path) -> None:
    req = Request(url, headers={"User-Agent": "ss13-mcp-setup"})
    with urlopen(req) as resp:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as f:
            shutil.copyfileobj(resp, f)


def _ensure_dm_dump() -> Path:
    override = os.environ.get("SS13_DM_DUMP_PATH")
    if override:
        return Path(override)
    bin_dir = snapshot_dir() / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    url, name = _dm_dump_url()
    dest = bin_dir / name
    if dest.exists():
        return dest
    _step(f"downloading dm-dump from {url}")
    _download(url, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return dest


def _probe_dm_dump(dm_dump: Path) -> None:
    """Verify the dm-dump binary is present and runnable.

    Runs `dm-dump --version` and confirms the output starts with `dm-dump`.
    Probing here lets setup fail fast with an actionable error rather than
    silently leaving a 0-byte dmm-raw.json mid-pipeline (issue #16).
    """
    _step(f"probing dm-dump at {dm_dump}")
    try:
        result = subprocess.run(
            [str(dm_dump), "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"dm-dump binary not found at {dm_dump}. Build it with `cargo build "
            "--release --manifest-path dm-dump/Cargo.toml` and set "
            "SS13_DM_DUMP_PATH to the resulting binary."
        ) from e
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"failed to invoke dm-dump at {dm_dump}: {e}") from e
    stdout = (result.stdout or "").strip()
    if result.returncode != 0 or not stdout.startswith("dm-dump"):
        stderr = (result.stderr or "").strip() or "(no stderr)"
        raise RuntimeError(
            f"dm-dump at {dm_dump} failed its version probe (exit "
            f"{result.returncode}, stdout={stdout!r}, stderr={stderr}). "
            f"Build the dm-dump binary from this repo (cargo build --release "
            "--manifest-path dm-dump/Cargo.toml) and point SS13_DM_DUMP_PATH "
            "at it. Tracking: https://github.com/vg14-developers/ss13-mcp/issues/16"
        )
    _step(f"dm-dump probe ok ({stdout})")


def _looks_like_ss13(path: Path) -> bool:
    """Standard SS13 fork layout: top-level code/ and icons/ directories."""
    return (path / "code").is_dir() and (path / "icons").is_dir()


def _git_head_sha(path: Path) -> str | None:
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=path,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_remote_url(path: Path) -> str | None:
    """Best-effort origin URL of an existing checkout; None if unavailable."""
    if not (path / ".git").exists():
        return None
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            check=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _resolve_repo_url(fork: str | None, repo_url: str | None) -> tuple[str, str]:
    """Returns (repo_url, fork_label). Exactly one of fork/repo_url must be given."""
    if fork and repo_url:
        raise ValueError("pass either `fork` or `repo_url`, not both")
    if fork:
        if fork not in KNOWN_FORKS:
            known = ", ".join(sorted(KNOWN_FORKS))
            raise ValueError(f"unknown fork {fork!r}. Known forks: {known}")
        return KNOWN_FORKS[fork], fork
    if repo_url:
        return repo_url, "custom"
    raise ValueError(
        "cloning requires either `fork=<key>` (one of "
        f"{', '.join(sorted(KNOWN_FORKS))}) or `repo_url=<git-url>`"
    )


def _clone(repo_url: str, sha: str | None, dest: Path) -> str:
    """Clone repo_url into dest. If sha is None, clone the remote's default branch.

    Returns the resolved HEAD SHA.
    """
    label = f"{repo_url} @ {sha[:8]}" if sha else f"{repo_url} (default branch HEAD)"
    _step(f"cloning {label} -> {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    # stdin=DEVNULL on every git call: Git for Windows hangs at startup when it
    # inherits a pipe stdin that another thread (here, the MCP stdio reader) is
    # already blocked reading from.
    subprocess.run(["git", "init", "-q"], cwd=dest, check=True, stdin=subprocess.DEVNULL)
    subprocess.run(
        ["git", "remote", "add", "origin", repo_url], cwd=dest, check=True, stdin=subprocess.DEVNULL
    )
    if sha:
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", sha],
            cwd=dest,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "checkout", "FETCH_HEAD"], cwd=dest, check=True, stdin=subprocess.DEVNULL
        )
    else:
        # Fetch and check out whatever the remote's HEAD points at.
        subprocess.run(
            ["git", "fetch", "--depth", "1", "origin", "HEAD"],
            cwd=dest,
            check=True,
            stdin=subprocess.DEVNULL,
        )
        subprocess.run(
            ["git", "checkout", "FETCH_HEAD"], cwd=dest, check=True, stdin=subprocess.DEVNULL
        )
    actual = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=dest,
        check=True,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if sha and actual != sha:
        raise RuntimeError(f"SHA mismatch: requested {sha}, got {actual}")
    return actual


def _build_dm_index(ss13: Path, dm_dump: Path, out_dir: Path) -> None:
    _step("building DM type index (slowest local step, ~3-10 min)")
    env = os.environ.copy()
    env["SS13_DM_DUMP"] = str(dm_dump)
    try:
        subprocess.run(
            [sys.executable, "-m", "ss13_mcp.pipeline.build_dm_index", str(ss13), str(out_dir)],
            check=True,
            env=env,
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        # Surface the pipeline subprocess's stderr (RuntimeError + traceback)
        # to the MCP caller instead of letting it vanish into the server log.
        stderr = (e.stderr or "").strip() or "(no stderr)"
        raise RuntimeError(f"DM index build failed (exit {e.returncode}): {stderr}") from e


def setup(
    ss13_path: str,
    fork: str | None = None,
    repo_url: str | None = None,
    clone_if_missing: bool = False,
    sha: str | None = None,
    force: bool = False,
) -> dict:
    """Configure the MCP server against an SS13 fork checkout.

    Args:
        ss13_path: Absolute path to an existing SS13 fork clone, or the
            directory you'd like one cloned into (combine with
            clone_if_missing=true).
        fork: Shortcut for a known fork (one of: vg, tg, paradise, bay, goon,
            cm). Only consulted when cloning; ignored if the path already
            exists. Mutually exclusive with repo_url.
        repo_url: Git URL of an SS13 fork to clone. Use this for forks not
            covered by the `fork` shortcut. Mutually exclusive with fork.
        clone_if_missing: If true and `ss13_path` does not exist (or is empty),
            clone the chosen repo into it. If false and the path is missing,
            this raises.
        sha: Commit SHA to check out when cloning. Defaults to the remote's
            default branch HEAD.
        force: Rebuild the DM index even if one already exists for this path.

    Returns a summary dict the caller can show to the user.
    """
    ss13 = Path(ss13_path).expanduser().resolve()

    # Ensure and probe dm-dump before any heavy work (clone / index build) so a
    # missing or broken binary surfaces immediately rather than after a
    # multi-gigabyte clone. See issue #16.
    dm_dump = _ensure_dm_dump()
    _probe_dm_dump(dm_dump)

    fork_label = "unknown"
    repo_url_resolved: str | None = None
    if ss13.exists() and any(ss13.iterdir()):
        if not _looks_like_ss13(ss13):
            raise ValueError(
                f"{ss13} exists but doesn't look like an SS13 checkout "
                "(expected code/ and icons/ subdirs). Point setup at a real "
                "SS13 fork clone or an empty/nonexistent directory with "
                "clone_if_missing=true."
            )
        actual_sha = _git_head_sha(ss13) or "unknown"
        # Preserve fork label across re-runs that just reuse an existing checkout.
        fork_label = fork or "custom"
        repo_url_resolved = _git_remote_url(ss13) or repo_url
        _step(f"using existing SS13 checkout at {ss13} (HEAD={actual_sha[:8]})")
    else:
        if not clone_if_missing:
            raise FileNotFoundError(
                f"{ss13} does not exist. Re-run with clone_if_missing=true and "
                "either fork=<key> or repo_url=<git-url> to clone a fork into "
                "that directory."
            )
        if not shutil.which("git"):
            raise RuntimeError("git is required to clone but was not found on PATH")
        url, fork_label = _resolve_repo_url(fork, repo_url)
        repo_url_resolved = url
        clone_sha = sha or os.environ.get("SS13_SHA")
        actual_sha = _clone(url, clone_sha, ss13)

    index_dir = snapshot_dir() / "index"
    if force or not (index_dir.exists() and (index_dir / "types.json").exists()):
        if index_dir.exists():
            shutil.rmtree(index_dir)
        _build_dm_index(ss13, dm_dump, index_dir)
    else:
        _step(f"DM index already present at {index_dir}; skipping (pass force=true to rebuild)")

    cfg = {
        "ss13_path": str(ss13),
        "ss13_sha": actual_sha,
        "fork": fork_label,
        "repo_url": repo_url_resolved,
        "bumped_at": datetime.now(timezone.utc).isoformat(),
        "dm_dump_path": str(dm_dump),
    }
    write_config(cfg)
    _step(f"wrote config to {config_path()}")

    types_count = 0
    types_file = index_dir / "types.json"
    if types_file.exists():
        types_count = len(json.loads(types_file.read_text()))

    return {
        "configured": True,
        "ss13_path": str(ss13),
        "ss13_sha": actual_sha,
        "fork": fork_label,
        "dm_dump_path": str(dm_dump),
        "snapshot_dir": str(snapshot_dir()),
        "dm_types_count": types_count,
    }
