import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

FIXTURE_SS13 = Path(__file__).parent / "fixtures" / "mini-ss13"
FIXTURE_SHA = (FIXTURE_SS13 / "SHA").read_text().strip()


def _bake_index(out_dir: Path) -> None:
    """Generate index/ from a synthetic dmm-tools dump so DM-query tests have data."""
    from ss13_mcp.pipeline.build_dm_index import massage_dmm_output

    records = [
        {
            "path": "/datum",
            "parent": None,
            "vars": [],
            "procs": [],
            "file": "code/datum.dm",
            "line": 1,
        },
        {
            "path": "/atom",
            "parent": "/datum",
            "vars": [],
            "procs": [],
            "file": "code/atom.dm",
            "line": 1,
        },
        {
            "path": "/obj",
            "parent": "/atom",
            "vars": [],
            "procs": [],
            "file": "code/obj.dm",
            "line": 1,
        },
        {
            "path": "/obj/test",
            "parent": "/obj",
            "vars": [],
            "procs": [],
            "file": "code/test.dm",
            "line": 1,
        },
        {
            "path": "/obj/test/widget",
            "parent": "/obj/test",
            "vars": [],
            "procs": [],
            "file": "code/modules/test/widget.dm",
            "line": 1,
        },
        {
            "path": "/obj/test/widget/super",
            "parent": "/obj/test/widget",
            "vars": [{"name": "charge", "value": "100"}],
            "procs": [{"name": "megazap"}],
            "file": "code/modules/test/super_widget.dm",
            "line": 1,
        },
        {
            "path": "/obj/test/widget",
            "parent": "/obj/test",
            "vars": [{"name": "charge", "value": "0"}],
            "procs": [{"name": "zap"}, {"name": "attack_self"}],
            "file": "code/modules/test/widget.dm",
            "line": 1,
        },
    ]
    massage_dmm_output(records, out_dir)


@pytest.fixture
def fixture_snapshot(monkeypatch, tmp_path):
    """Stand up a fresh per-test snapshot dir + config pointing at the fixture SS13 tree."""
    snap = tmp_path / "snapshot"
    snap.mkdir()
    _bake_index(snap / "index")
    (snap / "config.json").write_text(
        json.dumps(
            {
                "ss13_path": str(FIXTURE_SS13),
                "ss13_sha": FIXTURE_SHA,
                "fork": "vg",
                "repo_url": "https://github.com/vgstation-coders/vgstation13.git",
                "bumped_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    )
    monkeypatch.setenv("SS13_SNAPSHOT_DIR", str(snap))
    monkeypatch.setenv("SS13_PATH", str(FIXTURE_SS13))
    monkeypatch.setenv("SS13_CACHE_DIR", str(tmp_path / "cache"))
    return snap
