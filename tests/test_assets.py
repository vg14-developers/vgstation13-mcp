import base64
import json
from pathlib import Path as pathlib_Path

import pytest
from PIL import Image

from ss13_mcp.tools.assets import convert_dmi, list_dmi_states, preview_asset_licenses, read_asset


def test_read_asset_returns_base64(fixture_snapshot):
    out = read_asset("sound/blip.ogg")
    decoded = base64.b64decode(out["bytes_b64"])
    assert decoded.startswith(b"OggS")
    assert out["size"] == len(decoded)
    assert out["mime"] == "audio/ogg"


def test_read_asset_missing(fixture_snapshot):
    with pytest.raises(FileNotFoundError):
        read_asset("sound/missing.ogg")


def test_list_dmi_states_returns_all_three(fixture_snapshot):
    states = list_dmi_states("icons/test.dmi")
    by_name = {s["name"]: s for s in states}
    assert set(by_name) == {"idle", "active", "walk"}
    assert by_name["idle"]["dirs"] == 1 and by_name["idle"]["frames"] == 1
    assert by_name["active"]["dirs"] == 1 and by_name["active"]["frames"] == 1
    assert by_name["walk"]["dirs"] == 4 and by_name["walk"]["frames"] == 3


def test_convert_dmi_full(fixture_snapshot, tmp_path):
    result = convert_dmi("icons/test.dmi", license_confirmed=True)
    rsi_dir = pathlib_Path(result["rsi_path"])
    assert (rsi_dir / "meta.json").exists()
    meta = json.loads((rsi_dir / "meta.json").read_text())
    assert meta["version"] == 1
    assert meta["license"] == "CC-BY-SA-3.0"
    assert meta["copyright"].startswith("Taken from vgstation13 at https://github.com/")
    assert meta["size"] == {"x": 32, "y": 32}
    state_names = {s["name"] for s in meta["states"]}
    assert state_names == {"idle", "active", "walk"}


def test_convert_dmi_single_state(fixture_snapshot, tmp_path):
    result = convert_dmi("icons/test.dmi", state="idle", license_confirmed=True)
    rsi_dir = pathlib_Path(result["rsi_path"])
    meta = json.loads((rsi_dir / "meta.json").read_text())
    state_names = {s["name"] for s in meta["states"]}
    assert state_names == {"idle"}


def test_convert_dmi_cache_hit(fixture_snapshot):
    first = convert_dmi("icons/test.dmi", license_confirmed=True)
    second = convert_dmi("icons/test.dmi", license_confirmed=True)
    assert first["rsi_path"] == second["rsi_path"]
    assert first["cache_hit"] is False
    assert second["cache_hit"] is True


def test_walk_state_rsi_layout(fixture_snapshot):
    result = convert_dmi("icons/test.dmi", state="walk", license_confirmed=True)
    rsi_dir = pathlib_Path(result["rsi_path"])
    meta = json.loads((rsi_dir / "meta.json").read_text())
    walk_meta = next(s for s in meta["states"] if s["name"] == "walk")
    assert walk_meta["directions"] == 4
    assert walk_meta["delays"] == [[1.0, 1.5, 2.0]] * 4

    sheet = Image.open(rsi_dir / "walk.png").convert("RGBA")
    assert sheet.size == (32 * 3, 32 * 4)
    for frame in range(3):
        for direction in range(4):
            px = sheet.getpixel((frame * 32 + 16, direction * 32 + 16))
            expected = (30 + direction * 60, 30 + frame * 60, 200, 255)
            assert px == expected, (
                f"RSI (col={frame},row={direction}) center pixel was {px}, "
                f"expected {expected} (frame={frame}, direction={direction})"
            )


def test_safe_name_keeps_slash_distinct():
    """States named 'foo/bar' and 'foo_bar' must not collide on disk."""
    from ss13_mcp.rsi import _safe

    assert _safe("foo/bar") != _safe("foo_bar")


def test_approval_store_roundtrip(fixture_snapshot):
    from ss13_mcp import snapshot

    repo = "vgstation-coders/vgstation13"
    assert snapshot.is_license_approved(repo, "CC-BY-SA-3.0") is False
    snapshot.record_approval(repo, "CC-BY-SA-3.0", "CC-BY-SA-3.0")
    assert snapshot.is_license_approved(repo, "CC-BY-SA-3.0") is True
    assert snapshot.approved_license(repo, "CC-BY-SA-3.0") == "CC-BY-SA-3.0"


def test_approval_store_records_null_effective(fixture_snapshot):
    from ss13_mcp import snapshot

    repo = "acme/private"
    snapshot.record_approval(repo, "(unknown)", None)
    # Presence is distinct from a null value.
    assert snapshot.is_license_approved(repo, "(unknown)") is True
    assert snapshot.approved_license(repo, "(unknown)") is None


def test_write_rsi_omits_license_when_none(fixture_snapshot, tmp_path):
    import json as _json

    from ss13_mcp import dmi, rsi
    from ss13_mcp.snapshot import ss13_dir

    parsed = dmi.load_dmi(ss13_dir() / "icons" / "test.dmi")
    out = tmp_path / "rsi_none"
    rsi.write_rsi(parsed, out, license=None, copyright="Taken from x at http://e")
    meta = _json.loads((out / "meta.json").read_text())
    assert "license" not in meta
    assert meta["copyright"] == "Taken from x at http://e"


def test_write_rsi_stamps_license(fixture_snapshot, tmp_path):
    import json as _json

    from ss13_mcp import dmi, rsi
    from ss13_mcp.snapshot import ss13_dir

    parsed = dmi.load_dmi(ss13_dir() / "icons" / "test.dmi")
    out = tmp_path / "rsi_lic"
    rsi.write_rsi(parsed, out, license="CC-BY-SA-3.0", copyright="c")
    meta = _json.loads((out / "meta.json").read_text())
    assert meta["license"] == "CC-BY-SA-3.0"
    assert meta["copyright"] == "c"


def test_convert_dmi_gates_until_approved(fixture_snapshot):
    out = convert_dmi("icons/test.dmi")
    assert out["status"] == "needs_license_approval"
    assert out["resolved_license"] == "CC-BY-SA-3.0"
    assert out["effective_license"] == "CC-BY-SA-3.0"
    assert set(out["states"]) == {"idle", "active", "walk"}
    assert out["source_url"].startswith(
        "https://github.com/vgstation-coders/vgstation13/blob/"
    )
    from ss13_mcp import cache

    assert not cache.is_hit("icons/test.dmi", None)


def test_second_asset_same_class_not_gated(fixture_snapshot):
    convert_dmi("icons/test.dmi", license_confirmed=True)
    out = convert_dmi("icons/test.dmi", state="active")
    assert out.get("status") != "needs_license_approval"
    assert out["license"] == "CC-BY-SA-3.0"


def test_goon_path_is_separate_noncommercial_class(fixture_snapshot):
    out = convert_dmi("goon/icons/goontest.dmi")
    assert out["status"] == "needs_license_approval"
    assert out["resolved_license"] == "CC-BY-NC-SA-3.0"
    convert_dmi("icons/test.dmi", license_confirmed=True)
    still = convert_dmi("goon/icons/goontest.dmi")
    assert still["status"] == "needs_license_approval"


def test_unknown_repo_requires_override(fixture_snapshot, monkeypatch):
    import ss13_mcp.tools.assets as assets_mod

    monkeypatch.setattr(assets_mod, "_owner_repo", lambda cfg: None)
    gate = convert_dmi("icons/test.dmi")
    assert gate["resolved_license"] is None
    assert gate["resolved_class"] == "(unknown)"
    out = convert_dmi("icons/test.dmi", license_override="MIT", license_confirmed=True)
    meta = json.loads((pathlib_Path(out["rsi_path"]) / "meta.json").read_text())
    assert meta["license"] == "MIT"


def test_preview_groups_by_license(fixture_snapshot):
    out = preview_asset_licenses(["icons/test.dmi", "goon/icons/goontest.dmi"])
    assert out["repo"] == "vgstation-coders/vgstation13"
    assert out["groups"]["CC-BY-SA-3.0"]["count"] == 1
    assert out["groups"]["CC-BY-NC-SA-3.0"]["count"] == 1
    assert out["groups"]["CC-BY-SA-3.0"]["approved"] is False


def test_override_forces_rewrite_over_existing_slot(fixture_snapshot):
    # A normal approved conversion creates the cache slot for (path, state=None).
    convert_dmi("icons/test.dmi", license_confirmed=True)
    # Correcting the license via override on the SAME path/state must force a
    # rewrite even though the slot exists: cache_hit is False and the new license lands.
    out = convert_dmi("icons/test.dmi", license_override="MIT", license_confirmed=True)
    assert out["cache_hit"] is False
    meta = json.loads((pathlib_Path(out["rsi_path"]) / "meta.json").read_text())
    assert meta["license"] == "MIT"
