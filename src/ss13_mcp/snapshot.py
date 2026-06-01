import json
import os
from pathlib import Path

from platformdirs import user_cache_dir

_APP_NAME = "ss13-mcp"


def _default_root() -> Path:
    return Path(user_cache_dir(_APP_NAME))


def snapshot_dir() -> Path:
    """Root directory of generated state (DM index, dmm-tools binary, config)."""
    return Path(os.environ.get("SS13_SNAPSHOT_DIR", str(_default_root() / "snapshot")))


def cache_dir() -> Path:
    """Disk cache root for DMI conversions."""
    d = Path(os.environ.get("SS13_CACHE_DIR", str(_default_root() / "conversions")))
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return snapshot_dir() / "config.json"


def is_configured() -> bool:
    return config_path().exists()


def load_config() -> dict:
    """Return the persisted config. Raises if setup has not been run."""
    p = config_path()
    if not p.exists():
        raise RuntimeError(
            "ss13-mcp is not set up yet. Ask the user which SS13 fork they want to "
            "work with (vg / tg / paradise / bay / goon / cm, or a custom repo URL) "
            "and where their checkout lives or should be cloned to, then call the "
            "`setup` tool with ss13_path=<that path>."
        )
    return json.loads(p.read_text())


def write_config(cfg: dict) -> None:
    snapshot_dir().mkdir(parents=True, exist_ok=True)
    config_path().write_text(json.dumps(cfg, indent=2))


def approvals_path() -> Path:
    return snapshot_dir() / "license_approvals.json"


def load_approvals() -> dict:
    """Persisted {repo: {resolved_class: approved_effective_license_or_null}}."""
    p = approvals_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save_approvals(data: dict) -> None:
    snapshot_dir().mkdir(parents=True, exist_ok=True)
    approvals_path().write_text(json.dumps(data, indent=2))


def is_license_approved(repo: str, resolved_class: str) -> bool:
    return resolved_class in load_approvals().get(repo, {})


def approved_license(repo: str, resolved_class: str) -> str | None:
    return load_approvals().get(repo, {}).get(resolved_class)


def record_approval(repo: str, resolved_class: str, effective_license: str | None) -> None:
    data = load_approvals()
    data.setdefault(repo, {})[resolved_class] = effective_license
    _save_approvals(data)


def ss13_dir() -> Path:
    """Path to the user's SS13 checkout. Env var wins for tests/overrides."""
    env = os.environ.get("SS13_PATH")
    if env:
        return Path(env)
    return Path(load_config()["ss13_path"])


def read_snapshot_sha() -> str:
    try:
        cfg = load_config()
    except RuntimeError:
        return "unknown"
    return cfg.get("ss13_sha", "unknown")


def read_fork() -> str:
    """Short fork identifier from config, or "custom" if a raw URL was used."""
    try:
        cfg = load_config()
    except RuntimeError:
        return "unknown"
    return cfg.get("fork", "custom")
