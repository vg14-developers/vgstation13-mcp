"""Writes a Robust SS14 RSI directory from a parsed DMI.

Sprite ordering:
- DMI sheet lays a state's cells in frame-major order: (frame=0,dir=0),
  (frame=0,dir=1), ..., (frame=0,dir=N-1), (frame=1,dir=0), ...
- RSI sheet is F columns x N rows, with row r = direction r (South, North,
  East, West, then SE/SW/NE/NW for 8-dir) and column c = frame c.
"""

import json
from pathlib import Path

from PIL import Image

from ss13_mcp.dmi import Dmi, DmiState


def _safe(name: str) -> str:
    # Use "__" for "/" so e.g. "alert/red" and "alert_red" stay distinct on disk.
    return name.replace("/", "__").replace(" ", "_") or "_unnamed"


def _crop_state(dmi: Dmi, state_idx: int) -> list[Image.Image]:
    """Return the cells of state `state_idx` in DMI frame-major order."""
    cells_per_row = dmi.image.width // dmi.width
    cells_consumed = 0
    for s in dmi.states[:state_idx]:
        cells_consumed += s.dirs * s.frames
    state = dmi.states[state_idx]
    cells: list[Image.Image] = []
    for i in range(state.dirs * state.frames):
        idx = cells_consumed + i
        x = (idx % cells_per_row) * dmi.width
        y = (idx // cells_per_row) * dmi.height
        cells.append(dmi.image.crop((x, y, x + dmi.width, y + dmi.height)))
    return cells


def _state_to_rsi(state: DmiState, cells: list[Image.Image]) -> tuple[dict, Image.Image]:
    w = cells[0].width
    h = cells[0].height
    directions = state.dirs
    out = Image.new("RGBA", (w * state.frames, h * directions), (0, 0, 0, 0))
    for frame in range(state.frames):
        for d in range(directions):
            # cells are in DMI frame-major order: idx = frame * dirs + dir.
            out.paste(cells[frame * directions + d], (frame * w, d * h))
    delays_per_dir = state.delay or [1.0] * state.frames
    meta: dict = {"name": state.name, "directions": directions}
    if state.frames > 1 or state.delay:
        meta["delays"] = [delays_per_dir] * directions
    return meta, out


def write_rsi(
    dmi: Dmi,
    out_dir: Path,
    state_filter: str | None = None,
    *,
    license: str | None = None,
    copyright: str | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_states = []
    used: set[str] = set()
    for i, s in enumerate(dmi.states):
        if state_filter and s.name != state_filter:
            continue
        safe = _safe(s.name)
        # Defensive dedup: in the unlikely event two states still collide,
        # append the DMI index so writes don't overwrite each other.
        if safe in used:
            safe = f"{safe}_{i}"
        used.add(safe)
        cells = _crop_state(dmi, i)
        meta_entry, sheet = _state_to_rsi(s, cells)
        sheet.save(out_dir / f"{safe}.png", format="PNG")
        meta_states.append(meta_entry)
    meta: dict = {"version": 1}
    if license is not None:
        meta["license"] = license
    if copyright is not None:
        meta["copyright"] = copyright
    meta["size"] = {"x": dmi.width, "y": dmi.height}
    meta["states"] = meta_states
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))
