import json
import subprocess
from pathlib import Path

import pytest

from ss13_mcp import setup as setup_mod
from ss13_mcp.snapshot import config_path, is_configured

FIXTURE_SS13 = Path(__file__).parent / "fixtures" / "mini-ss13"


@pytest.fixture
def empty_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("SS13_SNAPSHOT_DIR", str(tmp_path / "snap"))
    monkeypatch.delenv("SS13_PATH", raising=False)
    # Skip the real dm-dump download + probe + DM index build in unit tests.
    fake = tmp_path / "dm-dump-fake"
    fake.write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("SS13_DM_DUMP_PATH", str(fake))

    def fake_build(ss13, dm_dump, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "types.json").write_text(json.dumps({"/datum": {}}))

    monkeypatch.setattr(setup_mod, "_build_dm_index", fake_build)
    monkeypatch.setattr(setup_mod, "_probe_dm_dump", lambda _: None)
    return tmp_path


def test_setup_uses_existing_ss13_checkout(empty_snapshot):
    result = setup_mod.setup(str(FIXTURE_SS13))
    assert result["configured"] is True
    assert result["ss13_path"] == str(FIXTURE_SS13.resolve())
    assert is_configured()
    cfg = json.loads(config_path().read_text())
    assert cfg["ss13_path"] == str(FIXTURE_SS13.resolve())


def test_setup_rejects_non_ss13_dir(empty_snapshot, tmp_path):
    bogus = tmp_path / "not-ss13"
    bogus.mkdir()
    (bogus / "random.txt").write_text("nope")
    with pytest.raises(ValueError, match="doesn't look like an SS13 checkout"):
        setup_mod.setup(str(bogus))


def test_setup_requires_clone_flag_for_missing_path(empty_snapshot, tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(FileNotFoundError, match="clone_if_missing=true"):
        setup_mod.setup(str(missing))


def test_setup_clone_requires_fork_or_url(empty_snapshot, tmp_path, monkeypatch):
    """clone_if_missing=true without fork/repo_url should error before touching git."""
    # Make `git` lookup succeed so the error comes from missing fork/url, not git.
    monkeypatch.setattr(setup_mod.shutil, "which", lambda _: "/usr/bin/git")
    missing = tmp_path / "fresh"
    with pytest.raises(ValueError, match=r"fork=|repo_url="):
        setup_mod.setup(str(missing), clone_if_missing=True)


def test_setup_rejects_both_fork_and_url(empty_snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda _: "/usr/bin/git")
    missing = tmp_path / "fresh"
    with pytest.raises(ValueError, match="not both"):
        setup_mod.setup(
            str(missing),
            clone_if_missing=True,
            fork="vg",
            repo_url="https://example.com/x.git",
        )


def test_setup_rejects_unknown_fork(empty_snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda _: "/usr/bin/git")
    missing = tmp_path / "fresh"
    with pytest.raises(ValueError, match="unknown fork"):
        setup_mod.setup(str(missing), clone_if_missing=True, fork="nonesuch")


def test_setup_is_idempotent(empty_snapshot):
    setup_mod.setup(str(FIXTURE_SS13))
    # Second call should not rebuild (we count fake_build invocations indirectly
    # by ensuring the second call succeeds and config is still present).
    result = setup_mod.setup(str(FIXTURE_SS13))
    assert result["configured"] is True


def test_unconfigured_tools_raise_helpful_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SS13_SNAPSHOT_DIR", str(tmp_path / "empty"))
    monkeypatch.delenv("SS13_PATH", raising=False)
    from ss13_mcp.tools.source import list_dir

    with pytest.raises(RuntimeError, match="setup"):
        list_dir(".")


# --- _probe_dm_dump (issue #16) ---


def test_probe_passes_when_version_returns_expected_banner(monkeypatch, tmp_path):
    fake = tmp_path / "dm-dump"
    fake.write_text("")

    def fake_run(cmd, **kwargs):
        assert cmd[1:] == ["--version"]
        return subprocess.CompletedProcess(cmd, 0, stdout="dm-dump 0.1.0\n", stderr="")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    setup_mod._probe_dm_dump(fake)


def test_probe_rejects_wrong_binary(monkeypatch, tmp_path):
    """A working binary that isn't dm-dump (stdout banner mismatch) must be rejected."""
    fake = tmp_path / "dm-dump"
    fake.write_text("")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="dmm-tools 1.10.0\n", stderr="")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="failed its version probe"):
        setup_mod._probe_dm_dump(fake)


def test_probe_rejects_nonzero_exit(monkeypatch, tmp_path):
    fake = tmp_path / "dm-dump"
    fake.write_text("")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom\n")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="failed its version probe"):
        setup_mod._probe_dm_dump(fake)


def test_probe_includes_stderr_in_error(monkeypatch, tmp_path):
    fake = tmp_path / "dm-dump"
    fake.write_text("")
    expected = "library load failed"

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr=expected + "\n")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match=expected):
        setup_mod._probe_dm_dump(fake)


def test_probe_handles_missing_binary(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError(2, "No such file", cmd[0])

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="dm-dump binary not found"):
        setup_mod._probe_dm_dump(tmp_path / "nonexistent")


def test_probe_handles_timeout(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=15)

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="failed to invoke dm-dump"):
        setup_mod._probe_dm_dump(tmp_path / "dm-dump")


def test_probe_handles_oserror(monkeypatch, tmp_path):
    """Non-FileNotFoundError OSError (e.g., permission denied) surfaces clearly."""

    def fake_run(cmd, **kwargs):
        raise PermissionError(13, "Permission denied", cmd[0])

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="failed to invoke dm-dump"):
        setup_mod._probe_dm_dump(tmp_path / "dm-dump")


def test_probe_falls_back_when_stderr_empty(monkeypatch, tmp_path):
    """Probe failure with empty stderr still produces an actionable error."""
    fake = tmp_path / "dm-dump"
    fake.write_text("")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match=r"\(no stderr\)"):
        setup_mod._probe_dm_dump(fake)


def test_build_dm_index_surfaces_pipeline_stderr(monkeypatch, tmp_path):
    """When the pipeline subprocess fails, its stderr must reach the caller (issue #16)."""
    expected = "RuntimeError: dm-dump failed (exit 1): preprocessor failed"

    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output=None, stderr=expected)

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="preprocessor failed"):
        setup_mod._build_dm_index(tmp_path / "ss13", tmp_path / "dm-dump", tmp_path / "out")


def test_build_dm_index_handles_empty_stderr(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd, output=None, stderr="")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match=r"\(no stderr\)"):
        setup_mod._build_dm_index(tmp_path / "ss13", tmp_path / "dm-dump", tmp_path / "out")


def test_setup_fails_fast_when_probe_fails(monkeypatch, tmp_path):
    """Probe failure should surface before any clone work begins (issue #16)."""
    monkeypatch.setenv("SS13_SNAPSHOT_DIR", str(tmp_path / "snap"))
    monkeypatch.delenv("SS13_PATH", raising=False)
    fake = tmp_path / "dm-dump-fake"
    fake.write_text("")
    monkeypatch.setenv("SS13_DM_DUMP_PATH", str(fake))

    clone_called = False

    def fake_clone(*a, **kw):
        nonlocal clone_called
        clone_called = True
        return "deadbeef"

    monkeypatch.setattr(setup_mod, "_clone", fake_clone)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 127, stdout="", stderr="not a valid binary\n")

    monkeypatch.setattr(setup_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(setup_mod.shutil, "which", lambda _: "/usr/bin/git")

    missing = tmp_path / "fresh"
    with pytest.raises(RuntimeError, match="failed its version probe"):
        setup_mod.setup(str(missing), clone_if_missing=True, fork="vg")
    assert not clone_called, "probe must run before clone so we fail fast"


def test_setup_persists_repo_url_on_clone(empty_snapshot, tmp_path, monkeypatch):
    monkeypatch.setattr(setup_mod.shutil, "which", lambda _: "/usr/bin/git")
    monkeypatch.setattr(setup_mod, "_clone", lambda url, sha, dest: "deadbeef")
    fresh = tmp_path / "fresh"
    setup_mod.setup(str(fresh), clone_if_missing=True, fork="vg")
    cfg = json.loads(config_path().read_text())
    assert cfg["repo_url"] == "https://github.com/vgstation-coders/vgstation13.git"


def test_setup_reads_repo_url_from_existing_checkout(empty_snapshot, monkeypatch):
    monkeypatch.setattr(setup_mod, "_git_remote_url", lambda _p: "https://github.com/foo/bar.git")
    result = setup_mod.setup(str(FIXTURE_SS13))
    assert result["configured"] is True
    cfg = json.loads(config_path().read_text())
    assert cfg["repo_url"] == "https://github.com/foo/bar.git"
