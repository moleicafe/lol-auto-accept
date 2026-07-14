# Auto-download + Install & restart — Design

**Date:** 2026-07-15
**Status:** Approved by user (this session)
**Builds on:** the v1.1.5 update-check feature (`laa/updates.py`, `Config.check_updates`,
`Bridge.update_available`, the worker's 3s-delayed check, and the App-tab update label).

## Goal

Extend update *notification* into update *delivery*: when a newer GitHub release exists,
silently download the new `LeagueAutoAccept.exe` in the background, verify its SHA-256, and
offer a one-click **Install & restart** that swaps the binary and relaunches. On by default.

## Behavior

Two config flags gate everything:
- `check_updates: bool = True` (existing) — master switch: check GitHub on launch at all.
- `auto_download: bool = True` (new) — when checking, also download the new exe.

Resulting matrix:
- `check_updates` off → nothing happens.
- `check_updates` on, `auto_download` off → **today's behavior**: tray notification + a
  "download" link on the App tab (`update_available`).
- `check_updates` on, `auto_download` on (**default**) → download + verify + offer Install &
  restart (`update_downloaded`).

Auto-download only runs when **frozen** (`getattr(sys, "frozen", False)`): from source there
is no installable target, so it degrades to notify-with-link regardless of the flag.

**Flow (in the existing 3s-delayed worker task):**
1. `info = check_for_update(__version__)`; if `None`, stop.
2. If not (`auto_download` and frozen) → `bridge.update_available.emit(version, url)` and stop.
3. Staging path = `%APPDATA%\LeagueAutoAccept\updates\LeagueAutoAccept-<version>.exe`. If it
   already exists and verifies against the expected hash, skip the download (no repeated
   ~58 MB pulls).
4. Otherwise download the exe asset, verify SHA-256, write to the staging path. Prune older
   staged `LeagueAutoAccept-*.exe` files.
5. On success → `bridge.update_downloaded.emit(version, staged_path)`. On any failure →
   fall back to `bridge.update_available.emit(version, url)` (link) and log.

**UI (App tab):**
- New checkbox **"Automatically download updates"** bound to `auto_download` (default checked),
  placed under the existing "Check for updates on launch" checkbox.
- On `update_downloaded`: show the new version and an **"Install & restart"** button.
- On `update_available` (notify-only path): the existing download link, unchanged.
- Tray message on `update_downloaded`: "Update downloaded — click Install & restart in the
  App tab."

**Install handoff (Windows-specific):** a running `.exe` cannot overwrite itself, so clicking
Install & restart:
1. Writes a batch script (from the pure `installer_script(pid, staged, target)`) to a temp
   file.
2. Launches it detached, then calls `app.quit()`.
3. The batch waits for `pid` to exit, `move /Y` the staged exe over `target` (=
   `sys.executable`), relaunches `target`, and deletes itself.
If launching the batch fails, log it and open the release page so the user can install
manually; do not quit.

## Integrity model (explicit)

The SHA-256 check reliably catches corrupted, partial, or truncated downloads before anything
is executed. It is **not** a trust anchor against a compromised release: the checksum ships
from the same GitHub release as the binary. A real trust anchor is Authenticode code signing,
which is a separate, deferred track (see the signing options discussed this session:
SignPath Foundation (free, OSS) or Azure Artifact Signing). This feature is designed so that
adding signature verification later is an additive step in `download_update`.

The expected hash is obtained from a `LeagueAutoAccept.exe.sha256` asset attached to each
release (a plain-text hex digest). The release process already computes this hash for the
notes; it now also uploads it as an asset. If the GitHub asset `digest` field
(`"sha256:<hex>"`) is present it may be used as a corroborating source, but the `.sha256`
asset is the contract.

## Architecture / where it lives

- **`src/laa/config.py`** — add `auto_download: bool = True`.
- **`src/laa/updates.py`** (extend the existing module):
  - `UpdateInfo` gains `exe_url: str | None` and `sha256_url: str | None` (the browser
    download URLs of the `LeagueAutoAccept.exe` and `LeagueAutoAccept.exe.sha256` assets).
    `check_for_update` reads these from the release JSON `assets[]`. Existing callers that
    only use `version`/`url` are unaffected.
  - `async download_update(info, dest_dir, http=None) -> Path | None` — resolves the expected
    hash (fetch `sha256_url`), downloads `exe_url`, verifies, writes to
    `dest_dir/LeagueAutoAccept-<version>.exe`, prunes older staged files, returns the path;
    returns `None` on missing asset, hash mismatch, or any error (never raises).
  - `verify_sha256(data: bytes, expected_hex: str) -> bool` — case-insensitive compare
    (helper, also used by the already-staged short-circuit).
  - `installer_script(pid: int, staged: str, target: str) -> str` — pure; returns the batch
    text (PID wait loop, `move /Y`, relaunch, self-delete).
  - `updates_dir() -> Path` — `config.config_dir() / "updates"`.
- **`src/laa/ui/bridge.py`** — add `update_downloaded = Signal(str, str)  # version, staged path`.
- **`src/laa/ui/worker.py`** — replace the notify-only branch of the existing `update_check`
  task with the flow above (import `download_update`, `updates_dir`; gate on `sys.frozen`
  and `auto_download`).
- **`src/laa/ui/main_window.py`** — the "Automatically download updates" checkbox; an
  Install & restart button (hidden until `update_downloaded`); `_on_update_downloaded`
  handler that stores the staged path and wires the button; `_do_install(staged)` that
  writes+launches the batch and quits. Reuses the existing `_update_label`.
- **Release process** — after computing the SHA-256, write it to
  `dist/LeagueAutoAccept.exe.sha256` and pass both files to `gh release create`.

`laa/updates.py` stays Qt-free (pure logic + httpx). All Qt lives in `laa/ui`.

## Error handling

- Every network and filesystem step in `download_update` is wrapped; failure returns `None`
  and the worker falls back to the notify-with-link path. Offline never nags (existing
  behavior preserved).
- Hash mismatch → discard the download, return `None`, log a warning (never execute a
  binary that failed verification).
- Install batch launch failure → log, open the release page, do not quit.
- Not frozen → never attempt download or install (notify-with-link only).
- Re-download avoidance: a verified already-staged file short-circuits step 4.

## Testing

**Unit (`tests/test_updates.py`), mock HTTP transport, tmp dirs:**
- `check_for_update` populates `exe_url`/`sha256_url` from a release JSON with assets; still
  returns `None` for same/older/garbage tags (existing tests keep passing).
- `verify_sha256`: correct hex (any case) → True; wrong → False.
- `download_update`: correct checksum → staged file exists at the versioned path and is
  returned; mismatch → `None` and no file left; HTTP error → `None`; a pre-existing verified
  staged file → returned without a second download (assert no exe fetch).
- `installer_script`: contains the target/staged paths, a PID-wait loop, `move /Y`, a
  relaunch, and self-delete.

**UI (`tests/test_ui_smoke.py`), offscreen Qt:**
- `auto_download` checkbox default-checked and writes config.
- `update_downloaded` signal → Install & restart button becomes visible and the version
  shows; `update_available` still shows the link (unchanged).

**Config (`tests/test_config.py`):** `auto_download` default `True` + roundtrip.

**Manual (documented, not CI-able):** build, stage a fake "newer" exe, click Install &
restart, confirm the running exe is replaced and the new one relaunches; confirm the
notify-with-link fallback when auto_download is off.

## Risks

- **Unsigned binary auto-run.** Mitigated by: not executing on hash failure, keeping a human
  click before install (not fully silent), and the explicit integrity note above. Signing is
  the real fix and is tracked separately.
- **Install handoff is Windows-timing-dependent** (waiting for process exit). Mitigated by a
  PID-based wait loop with a bounded retry and a manual verification step; failure falls back
  to the manual link.
- **Bandwidth**: ~58 MB per new version. Mitigated by the already-staged short-circuit
  (download once per version, not per launch) and by gating on an actual newer release.
