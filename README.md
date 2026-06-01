# ss13-mcp

Local-launch MCP server that exposes any SS13 fork's source and assets to AI
coding agents (Claude Code, etc.). Runs entirely on your machine — no hosted
service, no auth, no network calls after first-run setup.

Works with any fork that follows the standard SS13 layout (top-level `code/`
and `icons/` dirs). Ships with shortcuts for **vg**, **tg**, **paradise**,
**bay**, **goon**, and **cm**; for anything else, just pass a git URL.

## What it gives the agent

- **Source proxy:** read SS13 source files at the commit you've checked out.
- **DM index:** structured queries against the BYOND type tree (subtypes, procs,
  vars, fuzzy path lookup), built from a vendored Rust binary (`dm-dump`) that
  uses SpacemanDMM's `dreammaker` parser crate.
- **Assets:** on-demand DMI → Robust SS14 RSI conversion with disk-cached results.
  Each RSI is stamped with the source asset's real license (resolved per-path from
  RSIEdit's `repository-licenses.json`, e.g. `goon/icons/*` → `CC-BY-NC-SA-3.0`),
  not a hardcoded value. The first conversion of a new license asks for human
  approval; approval is per-license and persists, so batches are approved once.

## Install

```bash
uvx --from git+https://github.com/vg14-developers/ss13-mcp ss13-mcp
```

Or pin via your Claude Code configuration (`.mcp.json`):

```json
{
  "mcpServers": {
    "ss13": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/vg14-developers/ss13-mcp",
        "ss13-mcp"
      ]
    }
  }
}
```

## First-run setup

The server ships with **no** automatic setup. On first launch its tools will
respond with a setup-required hint pointing the agent at the `setup` tool.

Tell the agent something like:

- **"I already have my SS13 fork cloned at `<path>`"** — the agent will call
  `setup(ss13_path="<path>")` and reuse your existing checkout.
- **"Clone tg to `<path>`"** — the agent will call
  `setup(ss13_path="<path>", fork="tg", clone_if_missing=True)` which clones
  the remote's default-branch HEAD into that directory.
- **"Clone https://github.com/.../my-fork.git to `<path>`"** — the agent will
  call `setup(ss13_path="<path>", repo_url="...", clone_if_missing=True)`.

Pass `sha="<commit>"` if you want a specific commit instead of the default
branch HEAD.

Setup then downloads the matching `dm-dump` binary (from this repo's GitHub
Releases) and builds the DM type index (~3–10 min on a real fork). The result
is persisted under your platform's user cache dir so subsequent launches start
in seconds:

| OS | Default snapshot path |
|----|----|
| Linux | `~/.cache/ss13-mcp/snapshot` |
| macOS | `~/Library/Caches/ss13-mcp/snapshot` |
| Windows | `%LOCALAPPDATA%\ss13-mcp\snapshot` |

To re-run setup against a different checkout, just call `setup` again with the
new path. Pass `force=True` to rebuild the DM index in place.

### Known fork shortcuts

| Key | Repository |
|----|----|
| `vg` | https://github.com/vgstation-coders/vgstation13 |
| `tg` | https://github.com/tgstation/tgstation |
| `paradise` | https://github.com/ParadiseSS13/Paradise |
| `bay` | https://github.com/Baystation12/Baystation12 |
| `goon` | https://github.com/goonstation/goonstation |
| `cm` | https://github.com/cmss13-devs/cmss13 |

Any SS13 fork (or other BYOND project with `code/` and `icons/` at the root)
works via the `repo_url=` parameter.

## System requirements

- **git** on `$PATH` (only needed if you ask setup to clone for you).
- A platform with a prebuilt `dm-dump` binary (auto-downloaded from this
  repo's GitHub Releases): x86_64 Linux, x86_64 Windows. For other platforms
  (including macOS), build it yourself with
  `cargo build --release --manifest-path dm-dump/Cargo.toml` and point
  `SS13_DM_DUMP_PATH` at the resulting binary. Setup probes the binary up
  front and fails fast with guidance if it's missing or broken (issue #16).

## Configuration

All optional — defaults work out of the box.

| Env var | Default | Purpose |
|----|----|----|
| `SS13_PATH` | from config | Override the SS13 checkout used by tools. Takes precedence over the configured path. |
| `SS13_SHA` | none | Default commit to check out when `clone_if_missing=true` and no `sha` is passed. Without it, the remote's default-branch HEAD is used. |
| `SS13_SNAPSHOT_DIR` | platform cache dir | Where the DM index + config live. |
| `SS13_CACHE_DIR` | platform cache dir | Where DMI→RSI conversions are cached. |
| `SS13_DM_DUMP_PATH` | downloaded | Override the `dm-dump` binary location. |

Asset-license approvals are recorded in `<snapshot>/license_approvals.json`
(keyed by repo + resolved license). Delete it to re-vet licenses from scratch.

## Building dm-dump

The DM index pipeline shells out to `dm-dump`, a small Rust binary in
`dm-dump/` that uses SpacemanDMM's `dreammaker` parser crate to walk the
BYOND type tree and emit NDJSON. Prebuilts are downloaded from this repo's
releases; to build locally:

```bash
cargo build --release --manifest-path dm-dump/Cargo.toml
export SS13_DM_DUMP_PATH=$(pwd)/dm-dump/target/release/dm-dump
```

Releases are cut by pushing a `dm-dump-v*` tag; CI builds and attaches
platform binaries to the release.

## License

MIT.
