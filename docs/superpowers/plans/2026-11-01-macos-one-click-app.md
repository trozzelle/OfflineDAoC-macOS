# OfflineDAoC.app Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed, notarized `OfflineDAoC.app` (DMG) that installs Offline DAoC 0.37/0.37b on an Apple Silicon Mac from nothing and then launches it, by running the existing `daoc` CLI underneath.

**Architecture:** `daoc_cli` gains five seams: a data home separate from the code root (`DAOC_DATA`), a JSON event channel (`DAOC_EVENTS=<fd>`), a prebuilt-server install path, `daoc-server.sh start --detach`, and `daoc status --json`. A SwiftUI app in `app/` bundles a standalone Python and the code root, spawns `daoc` per action with fd 3 as the event pipe, and renders progress, questions and the launcher. CI publishes prebuilt servers (keyed by server pin) and builds, signs and notarizes the app on each release tag.

**Tech Stack:** Python 3.9 stdlib (`daoc_cli`, must also run on 3.12), bash (`daoc-server.sh`, `build-release.sh`), Swift 5.10 language mode / SwiftUI / XCTest (SwiftPM package `app/`), GitHub Actions, `codesign`/`notarytool`/`hdiutil`.

**Spec:** `docs/superpowers/specs/2026-11-01-macos-one-click-app-design.md`

## Global Constraints

- `daoc_cli` stays Python 3.9 stdlib only and passes the suite on `/usr/bin/python3` (3.9) and on python-build-standalone 3.12.16 (`app/python.lock`). No walrus, no `match`, no 3.10+ typing syntax.
- The data-home variable is `DAOC_DATA`. Never `DAOC_HOME`: `daoc-server.sh:35` and `build-release.sh` read `DAOC_HOME` as the server folder and children inherit daoc's environment.
- Event mode is additive: with `DAOC_EVENTS` unset, stderr text, stdout and exit codes are byte-for-byte unchanged; every existing test keeps passing unedited unless a task says otherwise.
- Exit codes: 0 ok, 1 failure, 2 usage or refusal, 130 interrupted.
- The password is never on any argv daoc runs (existing `LoginTest.test_password_never_on_argv`).
- No git invocation on any path the app runs (CLT-less `/usr/bin/git` opens the CLT install dialog).
- macOS minimum 26 (`LSMinimumSystemVersion 26.0`); Apple Silicon only.
- Commit messages follow Conventional Commits (release-please reads them): `feat(scope): …`, `fix(scope): …`, `docs: …`, `ci: …`, `test: …`.
- Run Python tests from the repo root: `/usr/bin/python3 -m unittest discover -s tests`. Swift tests: `swift test --package-path app`.

## File map

| File | Responsibility |
|---|---|
| `daoc_cli/checkout.py` | Code root vs data home paths (`home`, `DAOC_DATA`) |
| `daoc_cli/events.py` (new) | Event channel: `on()`, `emit()`, `request()`, `close_on_exec()` |
| `daoc_cli/errors.py` | `say` emits `step`; `ask` asks the app; `interactive()` |
| `daoc_cli/cli.py` | `error` event; `status` group registered |
| `daoc_cli/proc.py` | `run(input=, new_session=)`, child stdin `/dev/null` in event mode; `execv` closes the channel |
| `daoc_cli/keychain.py` | `secret` event path; `saved()` |
| `daoc_cli/release.py` | `download` event; `fetch_verified` (moved from newclient) |
| `daoc_cli/client.py` | `download` event for curl downloads |
| `daoc_cli/status.py` (new) | `daoc status --json` |
| `daoc_cli/overview.py` | No git outside a git Checkout; data line |
| `daoc_cli/server.py` | Data-home build, `--from-source`, prebuilt install, `pack`, `start --detach` |
| `daoc_cli/updates.py` | Local server pins carry no `prebuilt` |
| `daoc_cli/pins.py` | `ship_field` |
| `daoc_cli/dev.py` | `pack-server`, `ship-prebuilt` |
| `daoc_cli/self_install.py` | Wrapper exports `DAOC_DATA` |
| `daoc_cli/client_runtime.py`, `newclient.py`, `e2e.py` | Data-home cwd/disk/evidence paths |
| `daoc` | Prefer `../python/bin/python3` (bundle) |
| `server/deploy/daoc-server.sh` | `start --detach` |
| `server/tools/build-release.sh` | `DAOC_SERVER_OUT` |
| `app/Package.swift`, `app/Sources/DaocKit/*` | Testable core: events, process runner, models |
| `app/Sources/OfflineDAoC/*` | SwiftUI app |
| `app/build-app.sh`, `app/sign-app.sh`, `app/Info.plist`, `app/python.lock` | Bundle assembly, signing, pins |
| `.github/workflows/tests.yml` | + bundled-Python job, + Swift job |
| `.github/workflows/server-prebuilt.yml` (new) | Build/publish prebuilt server, open pin PR |
| `.github/workflows/app.yml` (new) | Build, sign, notarize, upload DMG |
| `tests/test_events.py`, `tests/test_status.py`, `tests/test_server_script.py`, `tests/test_server_prebuilt.py` (new) | Python tests |

---

## Phase 1: `daoc_cli` seams

### Task 1: Data home (`Checkout.home`, `DAOC_DATA`)

**Files:**
- Modify: `daoc_cli/checkout.py:1-6` (docstring), `:67-86` (`__init__`), `:103-107` (`flavour_paths`)
- Modify: `daoc_cli/server.py:138-197` (`install` path split)
- Modify: `server/tools/build-release.sh:45`, `:222-227`
- Modify: `daoc_cli/client_runtime.py:200`, `:251`; `daoc_cli/newclient.py:259`; `daoc_cli/e2e.py:59`, `:482`
- Modify: `daoc_cli/overview.py:106-107`; `daoc_cli/self_install.py` (`wrapper_text`, `handle`)
- Modify: `tests/support.py` (drop inherited `DAOC_DATA`/`DAOC_EVENTS`)
- Test: `tests/test_cli.py` (`CheckoutTest`), `tests/test_server.py` (`InstallTest`), `tests/test_self_install.py`

**Interfaces:**
- Produces: `Checkout(root=None, home=None)`; attribute `home: Path` (resolved). `home` = argument, else `$DAOC_DATA` (resolved against cwd), else `root`. Under `home`: `server_dir`, `client_root`, `app_dir`, `new_client_root`, `new_client_project`, `godot_app`, `flavour_file`, `launcher_app`, `graphics_src`, `downloads`, `state`, `flavour_paths()`. Under `root`: `launcher_src`, `manifest`, `version`, `server/tools`.
- Produces: `build-release.sh` honours `DAOC_SERVER_OUT`; `server.install` sets it.
- Produces: `self_install.wrapper_text(root: Path, data: Optional[Path] = None) -> str`.

- [ ] **Step 1: Make tests ignore a developer's own variables**

In `tests/support.py`, after the `from daoc_cli import cli  # noqa: E402` line, add:

```python
# A developer's own data home or event channel must not leak into the tests;
# a test that needs one sets it for its run.
for _name in ("DAOC_DATA", "DAOC_EVENTS"):
    os.environ.pop(_name, None)
```

- [ ] **Step 2: Write the failing Checkout tests**

In `tests/test_cli.py`, `CheckoutTest.test_paths_derive_from_root`, add after `self.assertEqual(co.root, root)`:

```python
            self.assertEqual(co.home, root)
```

Add to `CheckoutTest`:

```python
    def test_installs_and_state_follow_the_data_home(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            os.environ.pop("DAOC_WINE_HOME", None)
            os.environ.pop("DAOC_WINEPREFIX", None)
            root = make_checkout(tmp).resolve()
            data = (Path(tmp) / "data").resolve()
            co = Checkout(root, home=data)
            self.assertEqual((co.root, co.home), (root, data))
            self.assertEqual(co.server_dir, data / "server/dist/daoc-server")
            self.assertEqual(co.client_root, data / "dist/OfflineDAoC")
            self.assertEqual(co.new_client_root, data / "dist/new-client")
            self.assertEqual(co.godot_app, data / "dist/godot/Godot_mono.app")
            self.assertEqual(co.wine_home, data / "dist/wine")
            self.assertEqual(co.prefix, data / "dist/prefix")
            self.assertEqual(co.launcher_app, data / "dist/DAoCLauncher.app")
            self.assertEqual(co.graphics_src, data / "upstream/graphics")
            self.assertEqual(co.downloads, data / "downloads")
            self.assertEqual(co.state, data / ".daoc")
            self.assertEqual(co.launcher_src, root / "client/DAoCLauncher.app")
            self.assertEqual(co.manifest["schema"], 2)

    def test_daoc_data_names_the_home_unless_one_is_given(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ):
            root = make_checkout(tmp).resolve()
            os.environ["DAOC_DATA"] = str(Path(tmp) / "data")
            self.assertEqual(Checkout(root).home, (Path(tmp) / "data").resolve())
            self.assertEqual(Checkout(root, home=root).home, root)
```

- [ ] **Step 3: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_cli.CheckoutTest -v`
Expected: FAIL with `AttributeError: 'Checkout' object has no attribute 'home'` / `TypeError: __init__() got an unexpected keyword argument 'home'`.

- [ ] **Step 4: Implement the split in `checkout.py`**

Replace the module docstring's sentence that says there is no `--home` / `DAOC_HOME` with:

```
Two roots. The code root holds daoc itself (daoc_cli/, manifest.json,
version.txt, client/DAoCLauncher.app, server/tools/). The data home holds what
daoc installs and records (dist/, server/dist/, downloads/, upstream/, .daoc/).
In a git Checkout both are the Checkout. OfflineDAoC.app keeps the code root
read-only inside its bundle and sets DAOC_DATA (not DAOC_HOME: daoc-server.sh
reads that as its own folder) to the data home; Checkout(home=...) overrides it.
```

Replace `Checkout.__init__` (`checkout.py:68-86`) with:

```python
    def __init__(self, root: Optional[Union[str, Path]] = None,
                 home: Optional[Union[str, Path]] = None) -> None:
        self.root = Path(root).resolve() if root is not None else ROOT
        if home is not None:
            self.home = Path(home).resolve()
        else:
            data = _env_path("DAOC_DATA")
            self.home = data.resolve() if data is not None else self.root
        self.server_dir = self.home / "server" / "dist" / "daoc-server"
        self.client_root = self.home / "dist" / "OfflineDAoC"
        self.app_dir = self.client_root / "runtime" / "client-opendaoc" / "app"
        self.new_client_root = self.home / "dist" / "new-client"
        self.new_client_project = self.new_client_root / "godot"
        self.godot_app = self.home / "dist" / "godot" / "Godot_mono.app"
        self.flavour_file = self.home / "dist" / ".wine-flavour"
        # The overrides resolve against the caller's cwd now; the recorded
        # flavour behind the defaults is read on first use of wine_home/prefix,
        # so a bad record fails only the commands that use Wine.
        self._wine_home_env = _env_path("DAOC_WINE_HOME")
        self._prefix_env = _env_path("DAOC_WINEPREFIX")
        self.launcher_src = self.root / "client" / "DAoCLauncher.app"
        self.launcher_app = self.home / "dist" / "DAoCLauncher.app"
        self.graphics_src = self.home / "upstream" / "graphics"
        self.downloads = self.home / "downloads"
        self.state = self.home / ".daoc"
```

In `flavour_paths`, replace `dist = self.root / "dist"` with `dist = self.home / "dist"`.

- [ ] **Step 5: Run the Checkout tests**

Run: `/usr/bin/python3 -m unittest tests.test_cli.CheckoutTest -v`
Expected: PASS.

- [ ] **Step 6: Write the failing server-install test**

In `tests/test_server.py` `InstallTest.setUp`, change the `build-release.sh` stub and record its output folder. Replace the `build_env = …` line and the `"build-release.sh": (…)` entry with:

```python
        build_env = Path(self.tmp.name) / "stubs" / "build.env"
        self.build_out = Path(self.tmp.name) / "stubs" / "build.out"
```

and

```python
            "build-release.sh": (f'm=$DAOC_NAVMESH_SRC/world/navmesh-manifest.sha256; [ -f "$m" ] && m=present\n'
                                 f'echo "$PWD|$DAOC_SOURCE_REPO|$DAOC_GAME_VERSION|$m" >> {build_env}\n'
                                 f'echo "$DAOC_SERVER_OUT" >> {self.build_out}'),
```

Add to `InstallTest`:

```python
    def test_a_data_home_holds_the_clone_and_the_install(self):
        data = Path(os.path.realpath(self.tmp.name)) / "data"
        src = data / "upstream" / "server"
        (src / ".git").mkdir(parents=True)
        code, _, err = run_cli(["server", "install"], self.root, env=dict(self.env, DAOC_DATA=str(data)))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.build_env.read_text().strip(), f"{self.root}|{src}|0.35|present")
        self.assertEqual(self.build_out.read_text().strip(), str(data / "server" / "dist" / "daoc-server"))
        self.assertEqual((data / "server" / "dist" / "daoc-server" / "config" / "edition").read_text(),
                         "sluaghbinder\n")
```

- [ ] **Step 7: Run it to verify it fails**

Run: `/usr/bin/python3 -m unittest tests.test_server.InstallTest -v`
Expected: the new test FAILS (the clone path is under the code root and `build.out` is empty); the others PASS.

- [ ] **Step 8: Split code and data in `server.install`**

In `daoc_cli/server.py` `install`, replace the line `root = Path(os.path.realpath(checkout.root))` and every later use of `root` in that function:

```python
    # Resolve symlinks: MSBuild must see one path (the old script's `cd "$(pwd -P)"`).
    code = Path(os.path.realpath(checkout.root))
    home = Path(os.path.realpath(checkout.home))
    progress = "--progress" if verbose else "--quiet"
    pin = pin if pin is not None else pins.effective(checkout, "server", version)
    url, ref = pin["upstream"], pin["ref"]
    navmesh_ref = pin.get("navmesh_ref") or ref
    src = home / "upstream" / "server"
```

```python
    (home / "downloads").mkdir(parents=True, exist_ok=True)
    (home / "upstream").mkdir(parents=True, exist_ok=True)
```

```python
    proc.run([code / "server" / "tools" / "setup-dotnet.sh"], cwd=code, verbose=verbose)
```

```python
        env = dict(os.environ, DAOC_SOURCE_REPO=str(src), DAOC_GAME_VERSION=version,
                   DAOC_NAVMESH_SRC=navmesh_src,
                   DAOC_SERVER_OUT=os.path.realpath(checkout.server_dir))
        build = [str(code / "server" / "tools" / "build-release.sh")]
```

```python
        proc.run(build, cwd=code, env=env, verbose=True)
```

- [ ] **Step 9: Let `build-release.sh` write into the data home**

Replace `build-release.sh:45`:

```bash
# The install folder: `daoc server install` sets DAOC_SERVER_OUT to its data home's server folder.
OUT="${DAOC_SERVER_OUT:-$HERE/dist/daoc-server}"
```

Replace lines 222 and 226 (the zip's folder follows OUT):

```bash
zipfile="$(dirname "$OUT")/daoc-server-$VERSION-macos-arm64.zip"
```

```bash
(cd "$(dirname "$OUT")" && zip -ryq "$zipfile" daoc-server -x "daoc-server/navmesh/*" \
```

- [ ] **Step 10: Move the remaining data paths**

- `client_runtime.py:200` and `:251`: `cwd=checkout.root` → `cwd=checkout.home`.
- `newclient.py:259`: `shutil.disk_usage(checkout.root)` → `shutil.disk_usage(checkout.home)` (create it first: insert `checkout.home.mkdir(parents=True, exist_ok=True)` on the line above).
- `e2e.py:59`: `checkout.root / "evidence"` → `checkout.home / "evidence"`; `e2e.py:482`: `checkout.root / ".e2e.lock"` → `checkout.home / ".e2e.lock"`.
- `overview.py` `show`: replace `lines = [f"daoc checkout {checkout.root}", ""]` with:

```python
    lines = [f"daoc checkout {checkout.root}"]
    if checkout.home != checkout.root:
        lines.append(f"data {checkout.home}")
    lines.append("")
```

- [ ] **Step 11: Write the failing self-install test**

Add to `tests/test_self_install.py` `SelfInstallTest`:

```python
    def test_a_data_home_is_exported_by_the_wrapper(self):
        data = self.tmp / "my data"
        code, _, err = self.install(env={"DAOC_DATA": str(data)})
        self.assertEqual(code, 0, err)
        self.assertIn(f"CHECKOUT={self.root}\nDAOC_DATA='{data}'\nexport DAOC_DATA\n",
                      self.wrapper.read_text())
        self.assertEqual(subprocess.run(["/bin/sh", "-n", str(self.wrapper)]).returncode, 0)
```

Run: `/usr/bin/python3 -m unittest tests.test_self_install -v`
Expected: the new test FAILS (no `DAOC_DATA` line).

- [ ] **Step 12: Export the data home in the wrapper**

In `daoc_cli/self_install.py`, add `from typing import Optional` to the imports and replace `wrapper_text` and the first lines of `handle`:

```python
def wrapper_text(root: Path, data: Optional[Path] = None) -> str:
    q = shlex.quote(str(root))
    export = f"DAOC_DATA={shlex.quote(str(data))}\nexport DAOC_DATA\n" if data is not None else ""
    return (
        "#!/bin/sh\n"
        f"{MARKER}\n"
        f"CHECKOUT={q}\n"
        f"{export}"
        'if [ ! -x "$CHECKOUT/daoc" ]; then\n'
        f"    echo {shlex.quote(f'daoc: checkout {root} is gone (moved or deleted); run ./daoc self-install from its new location')} >&2\n"
        "    exit 127\n"
        "fi\n"
        'exec "$CHECKOUT/daoc" "$@"\n'
    )
```

```python
def handle(args: argparse.Namespace, checkout) -> int:
    root = Path(os.path.realpath(str(checkout.root)))
    data = Path(os.path.realpath(str(checkout.home)))
    home = Path.home()
    bin_dir = home / ".local" / "bin"
    target = bin_dir / "daoc"
    if (target.exists() or target.is_symlink()) and (target.is_symlink() or not _ours(target)):
        raise DaocError(f"{target} exists and was not written by daoc self-install; "
                        "move it aside and re-run", code=2)
    atomic_write(target, wrapper_text(root, data if data != root else None), mode=0o755)
```

(the rest of `handle` is unchanged). Update the module docstring's first paragraph to add: "When the data home is not the Checkout (OfflineDAoC.app), the wrapper also exports DAOC_DATA."

- [ ] **Step 13: Run the full suite**

Run: `/usr/bin/python3 -m unittest discover -s tests`
Expected: `OK` (373 + 4 tests).

- [ ] **Step 14: Commit**

```bash
git add daoc_cli/checkout.py daoc_cli/server.py daoc_cli/client_runtime.py daoc_cli/newclient.py \
  daoc_cli/e2e.py daoc_cli/overview.py daoc_cli/self_install.py server/tools/build-release.sh \
  tests/support.py tests/test_cli.py tests/test_server.py tests/test_self_install.py
git commit -m "feat: a data home apart from the code root (DAOC_DATA)"
```

---

### Task 2: The launcher prefers a bundled Python

**Files:**
- Modify: `daoc` (lines 1-37)
- Test: `tests/test_cli.py` (`LauncherTest`)

**Interfaces:**
- Produces: `./daoc` runs `$(dirname "$root")/python/bin/python3` when executable, skipping the CLT check; otherwise unchanged.

- [ ] **Step 1: Write the failing test**

Add to `LauncherTest`:

```python
    def test_a_bundled_python_beside_the_code_root_needs_no_command_line_tools(self):
        python = self.tmp / "python" / "bin" / "python3"
        python.parent.mkdir(parents=True)
        marker = self.tmp / "bundled-python-ran"
        python.write_text(f'#!/bin/sh\ntouch {shlex.quote(str(marker))}\nexec /usr/bin/python3 "$@"\n')
        python.chmod(0o755)
        seen = self.probe(DAOC_XCODE_SELECT=str(self.stubs / "xcode-select-fails"))
        self.assertEqual(seen["package"], str(self.root / "daoc_cli"))
        self.assertTrue(marker.exists())
        self.assertEqual(stub_calls(self.stubs), [])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/usr/bin/python3 -m unittest tests.test_cli.LauncherTest -v`
Expected: the new test FAILS (exit 1, "the Xcode Command Line Tools are not installed").

- [ ] **Step 3: Implement**

In `daoc`, extend the header comment with:

```sh
# Inside OfflineDAoC.app the code root sits next to a standalone Python
# (Contents/Resources/daoc beside Contents/Resources/python): that Python runs
# daoc_cli and the Command Line Tools are neither checked nor needed.
```

Replace everything from the `xcode_select=` line to the end with:

```sh
bundled=$(dirname -- "$root")/python/bin/python3
if [ -x "$bundled" ]; then
  python=$bundled
else
  xcode_select=${DAOC_XCODE_SELECT:-/usr/bin/xcode-select}
  if ! clt=$("$xcode_select" -p 2>/dev/null) || [ -z "$clt" ] || [ ! -d "$clt" ]; then
    echo "daoc: the Xcode Command Line Tools are not installed; run: xcode-select --install" >&2
    exit 1
  fi
  python=/usr/bin/python3
fi

exec "$python" -I -c '
import runpy, sys
sys.path.insert(0, sys.argv.pop(1))
runpy.run_module("daoc_cli", run_name="__main__", alter_sys=True)
' "$root" "$@"
```

- [ ] **Step 4: Run the launcher tests**

Run: `/usr/bin/python3 -m unittest tests.test_cli.LauncherTest -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daoc tests/test_cli.py
git commit -m "feat: ./daoc runs a bundled Python beside its code root"
```

---

### Task 3: Event channel, `say`/`ask`/error events, `interactive()`

**Files:**
- Create: `daoc_cli/events.py`
- Modify: `daoc_cli/errors.py`, `daoc_cli/cli.py` (`main`), `daoc_cli/proc.py` (`run`, `execv`)
- Modify: `daoc_cli/server.py:242`, `:299`; `daoc_cli/client_runtime.py:124`; `daoc_cli/self_install.py:64`
- Test: `tests/test_events.py` (new)

**Interfaces:**
- Produces: `events.on() -> bool`; `events.emit(kind: str, **fields) -> None`; `events.request(kind: str, **fields) -> Optional[Dict[str, Any]]` (adds an incrementing `id`, reads one stdin JSON line; `None` on EOF, bad JSON or another id); `events.close_on_exec() -> None`; module counter `events._ids` (an `itertools.count`, patched in tests).
- Produces: `errors.interactive() -> bool`.
- Produces: `proc.run(argv, *, cwd=None, env=None, verbose=False, check=True, input: Optional[str] = None, new_session: bool = False)`.
- Event shapes: `{"t":"step","msg"}`, `{"t":"ask","id","question","default":false}` → answer `{"id","answer":bool}`, `{"t":"error","msg","code"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_events.py`:

```python
"""The OfflineDAoC app's event channel: DAOC_EVENTS=<fd> out, answers on stdin."""
import io
import itertools
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import cli, errors, events, proc, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError


@contextmanager
def channel():
    """DAOC_EVENTS pointing at a fresh pipe; .events holds what was written once the block ends."""
    r, w = os.pipe()
    ch = SimpleNamespace(events=[], env={"DAOC_EVENTS": str(w)})
    try:
        with mock.patch.dict(os.environ, ch.env):
            yield ch
    finally:
        os.close(w)
        with os.fdopen(r, encoding="utf-8") as f:
            ch.events = [json.loads(line) for line in f.read().splitlines()]


def group(handler):
    """cli.GROUPS plus a `t` group whose one parser runs handler."""
    def register(groups):
        groups.add_parser("t").set_defaults(func=handler)
    return mock.patch.object(cli, "GROUPS", cli.GROUPS + (("t", SimpleNamespace(register=register)),))


class EventTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_checkout(self.tmp.name)

    def test_say_is_a_step_event_and_keeps_its_stderr_line(self):
        def handler(args, checkout):
            errors.say("downloading Wine")
            return 0
        with channel() as ch, group(handler):
            code, out, err = run_cli(["t"], self.root)
        self.assertEqual((code, out, err), (0, "", "daoc: downloading Wine\n"))
        self.assertEqual(ch.events, [{"t": "step", "msg": "downloading Wine"}])

    def test_a_daoc_error_is_an_error_event_with_its_code(self):
        def handler(args, checkout):
            raise DaocError("refused", 2)
        with channel() as ch, group(handler):
            code, out, err = run_cli(["t"], self.root)
        self.assertEqual((code, out, err), (2, "", "daoc: refused\n"))
        self.assertEqual(ch.events, [{"t": "error", "msg": "refused", "code": 2}])

    def answer(self, line):
        err = io.StringIO()
        with channel() as ch, mock.patch.object(events, "_ids", itertools.count(1)), \
                mock.patch("sys.stdin", io.StringIO(line)), mock.patch("sys.stderr", err):
            result = errors.ask("Stop the server?")
        return result, ch.events, err.getvalue()

    def test_ask_round_trip(self):
        yes, sent, err = self.answer('{"id": 1, "answer": true}\n')
        self.assertTrue(yes)
        self.assertEqual(sent, [{"t": "ask", "id": 1, "question": "Stop the server?", "default": False}])
        self.assertEqual(err, "Stop the server? [y/N] ")
        self.assertFalse(self.answer('{"id": 1, "answer": false}\n')[0])
        self.assertFalse(self.answer("")[0])                           # the app went away
        self.assertFalse(self.answer('{"id": 2, "answer": true}\n')[0])  # another question's answer
        self.assertFalse(self.answer("yes\n")[0])                      # not JSON

    def test_a_refusal_off_a_terminal_becomes_a_question_for_the_app(self):
        co = Checkout(self.root)
        with channel() as ch, mock.patch.object(events, "_ids", itertools.count(1)), \
                mock.patch("sys.stdin", io.StringIO('{"id": 1, "answer": false}\n')), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch.object(server, "status", return_value=(True, "running (pid 7)")):
            with self.assertRaises(DaocError) as cm:
                server._stop_first(co)
        self.assertEqual(cm.exception.msg, "server update refused: the server is running")
        self.assertEqual(ch.events[0]["question"], "The server is running (pid 7). Stop it to update?")

    def test_children_cannot_read_the_answer_channel(self):
        r, w = os.pipe()
        os.write(w, b'{"id": 1, "answer": true}\n')
        os.close(w)
        saved = os.dup(0)
        try:
            os.dup2(r, 0)
            with channel():
                result = proc.run(["/bin/cat"])
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(r)
        self.assertEqual(result.stdout, "")

    def test_a_program_daoc_execs_does_not_inherit_the_channel(self):
        r, w = os.pipe()
        os.set_inheritable(w, True)
        try:
            with mock.patch.dict(os.environ, {"DAOC_EVENTS": str(w)}):
                events.close_on_exec()
            self.assertFalse(os.get_inheritable(w))
        finally:
            os.close(r)
            os.close(w)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_events -v`
Expected: FAIL with `ImportError: cannot import name 'events' from 'daoc_cli'`.

- [ ] **Step 3: Create `daoc_cli/events.py`**

```python
"""Machine-readable events for the OfflineDAoC app.

With DAOC_EVENTS=<fd> (a decimal file descriptor the app opened for this
process), daoc writes one JSON object per line to that fd, besides its
unchanged stderr text, and reads the app's answers to `ask` and `secret` as
JSON lines on stdin. The variable is read at every call. A write to a channel
the app has closed is dropped: the stderr text still says everything.

Events: {"t": "step", "msg"}, {"t": "download", "path", "bytes", "what"},
{"t": "ask", "id", "question", "default"}, {"t": "secret", "id", "what"},
{"t": "error", "msg", "code"}. The exit status is the result; there is no
"done" event.
"""
import itertools
import json
import os
import sys
from typing import Any, Dict, Optional

_ids = itertools.count(1)


def _fd() -> Optional[int]:
    value = os.environ.get("DAOC_EVENTS", "")
    return int(value) if value.isdigit() else None


def on() -> bool:
    """Whether the app is listening (DAOC_EVENTS names a file descriptor)."""
    return _fd() is not None


def emit(kind: str, **fields: Any) -> None:
    """Write one event; nothing when the app is not listening."""
    fd = _fd()
    if fd is None:
        return
    data = (json.dumps(dict(t=kind, **fields), ensure_ascii=False) + "\n").encode("utf-8")
    try:
        while data:
            data = data[os.write(fd, data):]
    except OSError:
        pass


def request(kind: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Emit a question with a fresh id and return the app's answer to it: the
    next stdin line as a JSON object carrying that id. None on EOF, on a line
    that is not a JSON object, or on an answer to another question."""
    ident = next(_ids)
    emit(kind, id=ident, **fields)
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        answer = json.loads(line)
    except ValueError:
        return None
    if not isinstance(answer, dict) or answer.get("id") != ident:
        return None
    return answer


def close_on_exec() -> None:
    """Keep the channel out of a program daoc execs: daoc-server.sh would hand
    it to the background server, which then holds the app's pipe open."""
    fd = _fd()
    if fd is None:
        return
    try:
        os.set_inheritable(fd, False)
    except OSError:
        pass
```

- [ ] **Step 4: Route `say`, `ask` and `interactive` through it**

Replace `daoc_cli/errors.py` below the docstring with:

```python
import sys

from daoc_cli import events


class DaocError(Exception):
    def __init__(self, msg: str, code: int = 1) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = code


def say(msg: str) -> None:
    print(f"daoc: {msg}", file=sys.stderr, flush=True)
    events.emit("step", msg=msg)


def interactive() -> bool:
    """Whether someone can answer a question: a terminal on stdin, or the
    OfflineDAoC app listening on DAOC_EVENTS."""
    return sys.stdin.isatty() or events.on()


def ask(question: str) -> bool:
    """A y/N question on the terminal, or to the app; anything but yes (or EOF) is no."""
    print(f"{question} [y/N] ", end="", file=sys.stderr, flush=True)
    if events.on():
        answer = events.request("ask", question=question, default=False)
        return bool(answer) and answer.get("answer") is True
    try:
        answer = input()
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")
```

Add to the module docstring: "With the app listening (DAOC_EVENTS), say() is also a `step` event and ask() asks the app; interactive() says whether anyone can answer."

- [ ] **Step 5: Emit the error event in `cli.main`**

In `daoc_cli/cli.py`, change `from daoc_cli.errors import DaocError, say` to `from daoc_cli.errors import DaocError` plus `from daoc_cli import events` (keep `say` in the import only if it is used elsewhere in the file; it is not). Replace the `except DaocError` branch in `main`:

```python
    except DaocError as e:
        print(f"daoc: {e.msg}", file=sys.stderr, flush=True)
        events.emit("error", msg=e.msg, code=e.code)
        return e.code
```

- [ ] **Step 6: `proc.run` input/new session, child stdin, and `execv`**

In `daoc_cli/proc.py`, add `from daoc_cli import events` to the imports. Replace `run`'s signature and the `subprocess.run` call:

```python
def run(
    argv: Sequence[StrPath],
    *,
    cwd: Optional[StrPath] = None,
    env: Optional[Mapping[str, str]] = None,
    verbose: bool = False,
    check: bool = True,
    input: Optional[str] = None,
    new_session: bool = False,
) -> "subprocess.CompletedProcess[str]":
```

Add to its docstring: "input is written to the child's stdin. new_session starts the child without a controlling terminal. With the app listening (DAOC_EVENTS) a child without input gets /dev/null as stdin, so it can never read the app's answers."

```python
    args = _argv(argv)
    name = Path(args[0]).name
    pipe = None if verbose else subprocess.PIPE
    kwargs: Dict[str, Any] = {"input": input} if input is not None else (
        {"stdin": subprocess.DEVNULL} if events.on() else {})
    try:
        result = subprocess.run(
            args, cwd=cwd, env=env, stdout=pipe, stderr=pipe, text=True, errors="replace",
            start_new_session=new_session, **kwargs
        )
```

Add `Any, Dict` to the `typing` import. In `execv`, insert `events.close_on_exec()` immediately before the `os.execv`/`os.execve` call.

- [ ] **Step 7: Replace the `isatty` checks with `interactive()`**

- `server.py`: change the import to `from daoc_cli.errors import DaocError, ask, interactive, say`; line 242 `if not sys.stdin.isatty():` → `if not interactive():`; line 299 likewise.
- `client_runtime.py:124`: `if not sys.stdin.isatty():` → `if not interactive():`, importing `interactive` from `daoc_cli.errors`.
- `self_install.py:64`: `if not sys.stdin.isatty():` → `if not interactive():`, importing `interactive` from `daoc_cli.errors`.
- Leave `keychain.py:44` (`unlock`) on `sys.stdin.isatty()`: `security unlock-keychain` prompts on a terminal itself. `keychain.py:78` changes in Task 4.
- Remove `import sys` from any of these modules where it is now unused (`grep -n "sys\." <file>`).

- [ ] **Step 8: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_events -v && /usr/bin/python3 -m unittest discover -s tests`
Expected: PASS / `OK`.

- [ ] **Step 9: Commit**

```bash
git add daoc_cli/events.py daoc_cli/errors.py daoc_cli/cli.py daoc_cli/proc.py daoc_cli/server.py \
  daoc_cli/client_runtime.py daoc_cli/self_install.py tests/test_events.py
git commit -m "feat: JSON event channel for the OfflineDAoC app (DAOC_EVENTS)"
```

---

### Task 4: The `secret` event for the Game account

**Files:**
- Modify: `daoc_cli/keychain.py` (`save_interactive`, docstring)
- Test: `tests/test_events.py` (new class), `tests/test_client_runtime.py` (`LoginTest` unchanged and must pass)

**Interfaces:**
- Consumes: `events.on/request`, `errors.interactive`, `proc.run(input=, new_session=)`.
- Produces: event `{"t":"secret","id":N,"what":"login"}` → answer `{"id":N,"account":str,"password":str}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_events.py` (add `import subprocess` and `from daoc_cli import keychain` to its imports):

```python
class SecretTest(unittest.TestCase):
    def login(self, answer):
        calls = []

        def run(argv, **kwargs):
            argv = [os.fspath(a) for a in argv]
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, "x\n", "")

        with channel() as ch, mock.patch.object(events, "_ids", itertools.count(1)), \
                mock.patch("sys.stdin", io.StringIO(json.dumps(dict(answer, id=1)) + "\n")), \
                mock.patch.object(keychain.proc, "run", run), mock.patch("sys.stderr", io.StringIO()):
            keychain.save_interactive()
        return calls, ch.events

    def test_the_app_login_keeps_the_password_off_argv(self):
        calls, sent = self.login({"account": "alice", "password": "s3 cret"})
        self.assertEqual(sent, [{"t": "secret", "id": 1, "what": "login"}])
        adds = [(argv, kw) for argv, kw in calls if argv[1] == "add-generic-password"]
        self.assertEqual(adds[0][0][-2:], ["-w", "alice"])
        argv, kw = adds[1]
        self.assertEqual(argv[-3:], ["-a", "login_password", "-w"])
        self.assertEqual((kw.get("input"), kw.get("new_session")), ("s3 cret\ns3 cret\n", True))
        self.assertTrue(all("s3 cret" not in argv for argv, _ in calls))

    def test_a_password_with_a_line_break_is_refused(self):
        with self.assertRaises(DaocError) as cm:
            self.login({"account": "alice", "password": "a\nb"})
        self.assertEqual(cm.exception.code, 2)

    def test_no_answer_saves_nothing(self):
        with self.assertRaises(DaocError) as cm:
            self.login({"account": "", "password": "pw"})
        self.assertEqual((cm.exception.code, cm.exception.msg), (2, "no account name given"))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_events.SecretTest -v`
Expected: FAIL (`daoc client login needs a terminal`).

- [ ] **Step 3: Implement**

In `daoc_cli/keychain.py`, change imports to:

```python
import sys
from typing import Optional, Tuple

from daoc_cli import events, proc
from daoc_cli.errors import DaocError, interactive, say
```

Add to the module docstring: "From the OfflineDAoC app (DAOC_EVENTS) the account and password come in the answer to a `secret` event. The password still goes to the bare `-w` prompt: run in a new session (no controlling terminal), security reads it and its confirmation from stdin, so it is never on argv."

Replace `save_interactive` with:

```python
def _from_app() -> Tuple[str, str]:
    """(account, password) from the app's answer to a `secret` event."""
    answer = events.request("secret", what="login") or {}
    account, password = answer.get("account"), answer.get("password")
    if not isinstance(account, str) or not account.strip():
        raise DaocError("no account name given", 2)
    if not isinstance(password, str) or not password:
        raise DaocError("no password given", 2)
    if "\n" in password or "\r" in password:
        raise DaocError("the password cannot contain a line break", 2)
    return account.strip(), password


def save_interactive() -> None:
    """Ask for the account name and password, on the terminal or from the app,
    and save (or replace) both."""
    if not interactive():
        raise DaocError("daoc client login needs a terminal", 2)
    password: Optional[str] = None
    if events.on():
        account, password = _from_app()
    else:
        try:
            print("Game account name: ", end="", file=sys.stderr, flush=True)
            account = input().strip()
        except EOFError:
            account = ""
    if not account:
        raise DaocError("no account name given", 2)
    # A locked keychain (SSH) refuses the write the same way it refuses a read.
    if _find(ACCOUNT).returncode == LOCKED:
        unlock()
    proc.run([SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT, "-w", account])
    add_password = [SECURITY, "add-generic-password", "-U", "-s", SERVICE, "-a", PASSWORD, "-w"]
    if password is None:
        # Bare -w last: security prompts for the password itself (no echo, not on argv).
        print("Game account password:", file=sys.stderr, flush=True)
        result = proc.run(add_password, verbose=True, check=False)
    else:
        result = proc.run(add_password, input=f"{password}\n{password}\n", new_session=True, check=False)
    if result.returncode != 0 or _find(PASSWORD).returncode != 0:
        raise DaocError("game account password not saved", 2)
```

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_events tests.test_client_runtime tests.test_server -v`
Expected: PASS (including `LoginTest.test_password_never_on_argv` and `PromptTest.test_keychain_save_interactive`).

- [ ] **Step 5: Commit**

```bash
git add daoc_cli/keychain.py tests/test_events.py
git commit -m "feat(client): the app saves the game account through a secret event"
```

---

### Task 5: `download` events

**Files:**
- Modify: `daoc_cli/release.py:27-38` (`download`), `daoc_cli/client.py:492-505` (`_download`)
- Test: `tests/test_events.py` (new class)

**Interfaces:**
- Produces: `{"t":"download","path":<file growing on disk>,"bytes":<Content-Length or null>,"what":<label>}` — `release.download` reports `<dest>.part` and `dest.name`; `client._download` reports the final path, `null` bytes and its `what` argument.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_events.py` (add `from pathlib import Path`, `from tests.support import path_stubs`, `from daoc_cli import client, release`, `from daoc_cli.files import sha256`):

```python
class DownloadEventTest(unittest.TestCase):
    def test_release_download_names_its_part_file_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.bin"
            src.write_bytes(b"x" * 1000)
            dest = Path(tmp) / "out.bin"
            with channel() as ch, mock.patch("sys.stderr", io.StringIO()):
                release.download(src.as_uri(), dest)
        self.assertEqual(ch.events[-1], {"t": "download", "path": str(dest) + ".part",
                                         "bytes": 1000, "what": "out.bin"})

    def test_a_curl_download_names_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            co = Checkout(make_checkout(tmp))
            co.downloads.mkdir(parents=True)
            stubs = path_stubs(tmp, {"curl": 'for a; do [ "$prev" = -o ] && printf data > "$a"; prev=$a; done'})
            want = sha256_bytes(b"data")
            with channel() as ch, mock.patch("sys.stderr", io.StringIO()), \
                    mock.patch.dict(os.environ, {"PATH": f"{stubs}:/usr/bin:/bin"}):
                client._download(co, "https://example.invalid/w.tar.xz", "w.tar.xz", want, "Wine", False)
        self.assertEqual(ch.events[-1], {"t": "download", "path": str(co.downloads / "w.tar.xz"),
                                         "bytes": None, "what": "Wine"})


def sha256_bytes(data):
    import hashlib
    return hashlib.sha256(data).hexdigest()
```

(Drop the unused `sha256` import if you added it.)

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_events.DownloadEventTest -v`
Expected: FAIL (the last event is a `step`).

- [ ] **Step 3: Implement**

`daoc_cli/release.py`: add `from daoc_cli import events` to the imports; replace the `with` block in `download`:

```python
        with urllib.request.urlopen(req) as r, tmp.open("wb") as f:
            length = r.headers.get("Content-Length") or ""
            events.emit("download", path=str(tmp), bytes=int(length) if length.isdigit() else None,
                        what=dest.name)
            shutil.copyfileobj(r, f, 1 << 20)
```

`daoc_cli/client.py` `_download`: add `from daoc_cli import events` (if `events` is not already imported) and insert after `say(f"downloading {what} ({name})")`:

```python
        events.emit("download", path=str(path), bytes=None, what=what)
```

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_events -v && /usr/bin/python3 -m unittest discover -s tests`
Expected: PASS / `OK`.

- [ ] **Step 5: Commit**

```bash
git add daoc_cli/release.py daoc_cli/client.py tests/test_events.py
git commit -m "feat: download events name the file growing on disk"
```

---

### Task 6: `daoc status --json`, `keychain.saved()`, no git outside a git Checkout

**Files:**
- Create: `daoc_cli/status.py`
- Modify: `daoc_cli/cli.py` (`GROUPS`), `daoc_cli/keychain.py` (`saved`), `daoc_cli/overview.py` (`_newer_release`)
- Test: `tests/test_status.py` (new), `tests/test_client_runtime.py` (`KeychainLockTest`), `tests/test_overview.py`

**Interfaces:**
- Produces: `status.snapshot(checkout) -> Dict[str, Any]` with keys `schema` (1), `version`, `home`, `game` `{name, version, edition}`, `client`, `switching_to` (game name or null), `installed` `{server, original_client, new_client}`, `wine` (or null), `server` `{running: bool|null, detail}`, `client_running` (`"original"|"new"|null`), `account_saved` (bool|null), `save` (edition or null).
- Produces: `keychain.saved() -> Optional[bool]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_status.py`:

```python
"""daoc status --json: the app's view of the install, offline and without git."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import keychain


class StatusJsonTest(unittest.TestCase):
    def test_a_fresh_data_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_checkout(tmp)
            data = Path(tmp).resolve() / "data"
            stubs = path_stubs(tmp, {"git": "exit 0"})
            with mock.patch.object(keychain, "saved", return_value=None):
                code, out, err = run_cli(["status", "--json"], root,
                                         env={"DAOC_DATA": str(data), "PATH": f"{stubs}:/usr/bin:/bin"})
            calls = stub_calls(stubs)
            default = json.loads((root / "manifest.json").read_text())["default"]["game"]
        self.assertEqual(code, 0, err)
        status = json.loads(out)
        self.assertEqual(status["schema"], 1)
        self.assertEqual(status["home"], str(data))
        self.assertEqual(status["game"]["name"], default)
        self.assertEqual(status["installed"], {"server": False, "original_client": False, "new_client": False})
        self.assertEqual(status["server"], {"running": False, "detail": "stopped"})
        self.assertIsNone(status["switching_to"])
        self.assertIsNone(status["client_running"])
        self.assertIsNone(status["account_saved"])
        self.assertIsNone(status["save"])
        self.assertEqual(calls, [])

    def test_status_prints_json_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli(["status"], make_checkout(tmp))
        self.assertEqual(code, 2)
        self.assertIn("daoc status needs --json", err)


if __name__ == "__main__":
    unittest.main()
```

Add to `tests/test_client_runtime.py` `KeychainLockTest`:

```python
    def test_saved_reads_no_secret(self):
        security = FakeSecurity(locked=False, items={"login_account": "acct"})
        with mock.patch.object(keychain.proc, "run", security):
            self.assertIs(keychain.saved(), True)
        self.assertNotIn("-w", security.calls[0])
        with mock.patch.object(keychain.proc, "run", FakeSecurity(locked=False, items={})):
            self.assertIs(keychain.saved(), False)
        with mock.patch.object(keychain.proc, "run", FakeSecurity(locked=True, items={})):
            self.assertIsNone(keychain.saved())
```

Add to `tests/test_overview.py` (import `path_stubs`, `stub_calls`, `make_checkout`, `run_cli` from `tests.support` if missing):

```python
class NoGitTest(unittest.TestCase):
    def test_the_overview_runs_no_git_outside_a_git_checkout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_checkout(tmp)
            stubs = path_stubs(tmp, {"git": "exit 0"})
            code, _, err = run_cli([], root, env={"PATH": f"{stubs}:/usr/bin:/bin"})
            calls = stub_calls(stubs)
        self.assertEqual(code, 0, err)
        self.assertEqual(calls, [])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_status tests.test_overview tests.test_client_runtime.KeychainLockTest -v`
Expected: FAIL (`invalid choice: 'status'`, no `keychain.saved`, git stub called).

- [ ] **Step 3: `keychain.saved`**

Add to `daoc_cli/keychain.py`:

```python
def saved() -> Optional[bool]:
    """Whether a Game account is saved, read without its secret (no -w): True,
    False, or None when the keychain is locked or security fails."""
    result = proc.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", ACCOUNT], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == NOT_FOUND:
        return False
    return None
```

- [ ] **Step 4: `daoc_cli/status.py`**

```python
"""`daoc status --json`: the overview as one JSON object, for the OfflineDAoC app.

Offline, read-only and quick enough to poll: no network, no git, no secret
read. Schema 1; a value daoc cannot tell is null. Hidden from help.
"""
import argparse
import json
from typing import Any, Dict

from daoc_cli import client_runtime, keychain, saves, selection, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

SCHEMA = 1


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser("status", help=argparse.SUPPRESS,
                          description="The overview as one JSON object, for the OfflineDAoC app.")
    p.add_argument("--json", action="store_true", help="print the JSON object")
    p.set_defaults(func=handle)


def _game(game: Any) -> Dict[str, str]:
    return {"name": game.name, "version": game.version, "edition": game.edition}


def snapshot(checkout: Checkout) -> Dict[str, Any]:
    try:
        sel = selection.load(checkout)
    except DaocError:
        sel = selection.fallback(checkout)
    running, detail = server.status(checkout)
    try:
        client_running = client_runtime.running_client(checkout)
    except DaocError:
        client_running = None
    try:
        wine = checkout.flavour
    except DaocError:
        wine = None
    try:
        save = saves.edition(checkout)
    except DaocError:
        save = None
    return {
        "schema": SCHEMA,
        "version": checkout.version,
        "home": str(checkout.home),
        "game": _game(sel.game),
        "client": sel.client,
        "switching_to": sel.switching_to.name if sel.switching_to else None,
        "installed": {
            "server": (checkout.server_dir / "daoc-server.sh").is_file(),
            "original_client": checkout.client_root.is_dir(),
            "new_client": checkout.new_client_root.is_dir(),
        },
        "wine": wine,
        "server": {"running": running, "detail": detail},
        "client_running": client_running,
        "account_saved": keychain.saved(),
        "save": save,
    }


def handle(args: argparse.Namespace, checkout: Checkout) -> int:
    if not args.json:
        raise DaocError("daoc status needs --json (run daoc for the overview)", 2)
    print(json.dumps(snapshot(checkout), indent=2))
    return 0
```

In `daoc_cli/cli.py`: add `status` to the `from daoc_cli import …` line and insert `("status", status),` in `GROUPS` between `("self-install", self_install),` and `("dev", dev),`.

- [ ] **Step 5: No git outside a git Checkout**

In `overview._newer_release`, insert as the first statement:

```python
    if not (checkout.root / ".git").exists():
        return None  # OfflineDAoC.app: no git, and /usr/bin/git without the CLT opens their installer
```

- [ ] **Step 6: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_status tests.test_overview tests.test_client_runtime -v && /usr/bin/python3 -m unittest discover -s tests`
Expected: PASS / `OK`.

- [ ] **Step 7: Commit**

```bash
git add daoc_cli/status.py daoc_cli/cli.py daoc_cli/keychain.py daoc_cli/overview.py \
  tests/test_status.py tests/test_client_runtime.py tests/test_overview.py
git commit -m "feat: daoc status --json for the OfflineDAoC app"
```

---

### Task 7: `daoc-server.sh start --detach`

**Files:**
- Modify: `server/deploy/daoc-server.sh` (header, `start`, usage)
- Modify: `daoc_cli/server.py:68-70` (`register`), `:93-97` (`_handle_script`)
- Test: `tests/test_server_script.py` (new)

**Interfaces:**
- Produces: `daoc-server.sh start --detach` → exit 0 once the admin socket exists and the log says `Server is now listening`; exit 1 with the log's last 25 lines when the server dies or is not ready after 180 s; exit 0 when already running. `daoc server start --detach` passes it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_script.py`:

```python
"""server/deploy/daoc-server.sh itself, against a fake CoreServer."""
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT

FAKE_SERVER = """\
import os, signal, socket, sys, time
if os.environ.get("FAKE_SERVER") == "die":
    print("fake server: boom", flush=True)
    sys.exit(3)
path = os.environ["DAOC_ADMIN_SOCKET"]
sock = socket.socket(socket.AF_UNIX)
sock.bind(path)
def stop(*_):
    os.unlink(path)
    sys.exit(0)
signal.signal(signal.SIGTERM, stop)
print("Server is now listening", flush=True)
while True:
    time.sleep(0.2)
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DetachTest(unittest.TestCase):
    def setUp(self):
        # Short path: a unix socket path must stay under 104 bytes.
        self.dir = Path(tempfile.mkdtemp(dir="/tmp", prefix="daocsrv."))
        self.addCleanup(shutil.rmtree, self.dir, True)
        shutil.copy2(ROOT / "server" / "deploy" / "daoc-server.sh", self.dir / "daoc-server.sh")
        core = self.dir / "bin" / "CoreServer"
        core.parent.mkdir()
        core.write_text(f"#!{sys.executable}\n{FAKE_SERVER}")
        core.chmod(0o755)
        (self.dir / "navmesh").mkdir()
        (self.dir / "navmesh" / "zone000.nav").write_bytes(b"")
        defaults = self.dir / "defaults"
        defaults.mkdir()
        (defaults / "world.sqlite").write_bytes(b"")
        (defaults / "serverconfig.xml").write_text(f"<Server><Port>{free_port()}</Port></Server>\n")
        for name in ("logconfig.xml", "invalidnames.txt"):
            (defaults / name).write_text("")
        admin = self.dir / "daoc-admin"
        admin.write_text("#!/bin/sh\necho ADMIN-SCREEN\n")
        admin.chmod(0o755)
        self.addCleanup(self.kill)

    def kill(self):
        pid_file = self.dir / "run" / "server.pid"
        if pid_file.is_file():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def sh(self, *args, **env):
        environ = {k: v for k, v in os.environ.items() if k != "DAOC_HOME"}
        environ.update(env)
        return subprocess.run([str(self.dir / "daoc-server.sh"), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=environ, timeout=60)

    def test_detach_returns_once_ready_without_the_admin_screen(self):
        result = self.sh("start", "--detach")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("ADMIN-SCREEN", result.stdout)
        self.assertTrue(self.sh("status").stdout.startswith("running (pid "))
        self.assertEqual(self.sh("stop").returncode, 0)

    def test_detach_on_a_running_server_exits_0(self):
        self.assertEqual(self.sh("start", "--detach").returncode, 0)
        again = self.sh("start", "--detach")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("already running", again.stdout)
        self.assertNotIn("ADMIN-SCREEN", again.stdout)

    def test_detach_reports_a_server_that_dies(self):
        result = self.sh("start", "--detach", FAKE_SERVER="die")
        self.assertEqual(result.returncode, 1)
        self.assertIn("fake server: boom", result.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_server_script -v`
Expected: FAIL — without a terminal `start --detach` falls into console mode and blocks until the 60 s timeout (`subprocess.TimeoutExpired`).

- [ ] **Step 3: Implement in `daoc-server.sh`**

In the header comment, after the `start --console` lines, add:

```bash
#   ./daoc-server.sh start --detach   start in the background, wait until it is ready, and return
#                                     (no admin screen; the OfflineDAoC app uses this)
```

Replace the beginning of `start()` (lines 57-65) with:

```bash
  local mode=${1:-}
  # --detach: background start, wait until ready, return (the OfflineDAoC app).
  # --console, or no terminal (init system, redirect): run the raw server console in the foreground.
  local console=false detach=false
  if [[ $mode == --detach ]]; then
    detach=true
  elif [[ $mode == --console || ! -t 0 || ! -t 1 ]]; then
    console=true
  fi

  if running_pid >/dev/null; then
    if $detach; then echo "already running (pid $(running_pid))"; exit 0; fi
    $console && die "already running (pid $(running_pid))"
    exec "$DAOC_HOME/daoc-admin"   # already running: just open the admin screen
  fi
```

Replace the two lines after the wait loop (`echo` and `exec "$DAOC_HOME/daoc-admin"`, lines 114-115) with:

```bash
  echo
  if $detach; then
    if [[ -S $DAOC_ADMIN_SOCKET ]] && grep -q "Server is now listening" "$log"; then
      echo "Server running (pid $pid)"
      exit 0
    fi
    echo "The server is not ready after 180 s. Last lines of $log:" >&2
    tail -n 25 "$log" >&2
    exit 1
  fi
  exec "$DAOC_HOME/daoc-admin"
```

Replace the usage line: `*) echo "usage: $0 start [--console|--detach] | stop | status"; exit 2 ;;`

- [ ] **Step 4: Pass `--detach` through `daoc server start`**

In `server.register`, replace the `start` parser lines:

```python
    a = actions.add_parser("start", help="start the server (daoc-server.sh start)")
    how = a.add_mutually_exclusive_group()
    how.add_argument("--console", action="store_true", help="run in the foreground with its console")
    how.add_argument("--detach", action="store_true",
                     help="start in the background, wait until it is ready, and return (no admin screen)")
    a.set_defaults(func=_handle_script)
```

In `_handle_script`, replace the `if getattr(args, "console", False):` block with:

```python
    for flag in ("console", "detach"):
        if getattr(args, flag, False):
            argv.append(f"--{flag}")
```

- [ ] **Step 5: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_server_script tests.test_server -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add server/deploy/daoc-server.sh daoc_cli/server.py tests/test_server_script.py
git commit -m "feat(server): start --detach returns once the server is ready"
```

---

### Task 8: Prebuilt groundwork: `--from-source`, Local pins without `prebuilt`, shared `fetch_verified`

**Files:**
- Modify: `daoc_cli/server.py` (`register` install parser, `_handle_install`, `install`)
- Modify: `daoc_cli/updates.py:211-212`
- Modify: `daoc_cli/release.py` (add `fetch_verified`), `daoc_cli/newclient.py:222-230`, `:245`, `:322`
- Test: `tests/test_server.py` (`InstallTest`), `tests/test_updates_check.py`

**Interfaces:**
- Produces: `server.install(checkout, version, verbose=False, pin=None, from_source=False)`; `daoc server install [--from-source]`.
- Produces: `release.fetch_verified(url: str, dest: Path, size: Optional[int], want: str, fetch_url: Downloader) -> None` (body moved unchanged from `newclient._fetch_verified`).
- Produces: `updates.resolve_latest(checkout, "server", v)` never contains `prebuilt`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_server.py` `InstallTest.setUp`, after `tools.mkdir(parents=True)`, add:

```python
        (self.root / "server" / "vendor").mkdir()   # a git Checkout has the build sources
```

Add `import shutil` to the file's imports and add to `InstallTest`:

```python
    def test_building_from_source_needs_a_checkout_with_the_build_sources(self):
        shutil.rmtree(self.root / "server" / "vendor")
        code, _, err = run_cli(["server", "install"], self.root, env=self.env)
        self.assertEqual(code, 2)
        self.assertIn("needs a git checkout of daoc-macos", err)
        self.assertEqual(stub_calls(self.stubs), [])
```

In `tests/test_updates_check.py` add (adapt the import line to the file's existing imports: `updates`, `Checkout`, `make_checkout`, `mock`, `tempfile`):

```python
class LocalServerPinTest(unittest.TestCase):
    def test_the_latest_server_pin_never_carries_a_prebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_checkout(tmp)
            manifest = json.loads((root / "manifest.json").read_text())
            manifest["versions"]["0.37"]["server"]["prebuilt"] = {"url": "https://x/y", "bytes": 1, "sha256": "0" * 64}
            (root / "manifest.json").write_text(json.dumps(manifest))
            with mock.patch.object(updates, "_head_sha", return_value="a" * 40), \
                    mock.patch.object(updates, "fork_version", return_value="0.37"):
                latest = updates.resolve_latest(Checkout(root), "server", "0.37")
        self.assertEqual(latest["ref"], "a" * 40)
        self.assertNotIn("prebuilt", latest)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_server.InstallTest tests.test_updates_check -v`
Expected: the two new tests FAIL.

- [ ] **Step 3: Implement `--from-source` and the refusal**

`server.register`, the `install` parser:

```python
    a = actions.add_parser("install", help="install the server for the selected game version")
    a.add_argument("-v", "--verbose", action="store_true",
                   help="show git progress and the build's warnings and tool output")
    a.add_argument("--from-source", action="store_true",
                   help="build it from the server repo even when a prebuilt server is pinned")
    a.set_defaults(func=_handle_install)
```

`_handle_install`: `install(checkout, game.version, verbose=args.verbose, from_source=args.from_source)`.

`install`: new signature and a guard before step 1:

```python
def install(checkout: Checkout, version: str, verbose: bool = False,
            pin: Optional[Dict[str, Any]] = None, from_source: bool = False) -> None:
    """Install the Server of game version from pin (default: its effective
    server pin): its prebuilt tarball when the pin has one, else a build from
    source (from_source forces the build)."""
    code = Path(os.path.realpath(checkout.root))
    if not (code / "server" / "vendor").is_dir():
        raise DaocError("building the server from source needs a git checkout of daoc-macos "
                        f"(this daoc, {code}, has no server/vendor)", 2)
```

(Keep the rest of the build as Task 1 left it; drop its now-duplicate `code = …` line.)

- [ ] **Step 4: Strip `prebuilt` from the latest server pin**

`updates.py:211-212`:

```python
        # Every other field (branch, navmesh_ref) stays the Shipped pin's: only the commit
        # moves. The Shipped prebuilt was built from the Shipped commit, so it does not come along.
        return dict({k: v for k, v in shipped.items() if k != "prebuilt"}, ref=sha)
```

- [ ] **Step 5: Move `fetch_verified` into `release.py`**

Append to `daoc_cli/release.py`:

```python
def fetch_verified(url: str, dest: Path, size: Optional[int], want: str,
                   fetch_url: Downloader) -> None:
    """dest, fetched with fetch_url unless it is already there with size and
    sha256 want; a download that fails the hash is deleted and refused."""
    if dest.is_file() and (size is None or dest.stat().st_size == size) and sha256(dest) == want:
        return
    dest.unlink(missing_ok=True)
    fetch_url(url, dest)
    if sha256(dest) != want:
        dest.unlink()
        raise DaocError(f"{dest.name} failed SHA-256 verification")
```

In `newclient.py`, delete `_fetch_verified` and replace both calls (`:245`, `:322`) `_fetch_verified(` → `release.fetch_verified(`.

- [ ] **Step 6: Run the tests**

Run: `/usr/bin/python3 -m unittest discover -s tests`
Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add daoc_cli/server.py daoc_cli/updates.py daoc_cli/release.py daoc_cli/newclient.py \
  tests/test_server.py tests/test_updates_check.py
git commit -m "feat(server): --from-source, and Local pins never carry a prebuilt"
```

---

### Task 9: Prebuilt server install and `server.pack`

**Files:**
- Modify: `daoc_cli/server.py` (constants, `install` branch, `_install_prebuilt`, `_extract_prebuilt`, `prebuilt_name`, `pack`, module docstring)
- Test: `tests/test_server_prebuilt.py` (new), `tests/test_server.py` (`InstallTest`)

**Interfaces:**
- Consumes: `release.fetch_verified`, `release.download`, `release.plain_name`, `pins.forget_installed/record_installed/installed`.
- Produces: `server.PREBUILT_ROOT = "daoc-server"`, `server.USER_DIRS = ("config", "data", "logs", "run")`, `server.prebuilt_name(version: str, ref: str) -> str` (`daoc-server-<version>-<ref12>-osx-arm64.tar.xz`), `server.pack(checkout, version: str, ref: str, out_dir: Path) -> Path`.
- Manifest field: `versions.<v>.server.prebuilt = {"url": str, "bytes": int, "sha256": str}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_server_prebuilt.py`:

```python
"""The prebuilt server: pack, install, and the refusals that keep a save safe."""
import io
import json
import os
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import make_checkout, path_stubs, run_cli, stub_calls

from daoc_cli import pins, release, server
from daoc_cli.checkout import Checkout
from daoc_cli.files import sha256


class PrebuiltTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = make_checkout(self.tmp)
        self.co = Checkout(self.root)
        self.pin = pins.shipped(self.co, "server", "0.35")
        self.ref = self.pin["ref"]
        self.stubs = path_stubs(self.tmp, {"git": "exit 1", "cmake": "exit 1"})

    # A Server install as a build leaves it, packed by server.pack.
    def built_tarball(self, ref=None):
        build = Checkout(self.root, home=self.tmp / "builder")
        sd = build.server_dir
        (sd / "bin").mkdir(parents=True)
        (sd / "bin" / "CoreServer").write_text("#!/bin/sh\n")
        os.symlink("../config", sd / "bin" / "config")
        (sd / "defaults").mkdir()
        (sd / "defaults" / "world.sqlite").write_bytes(b"world")
        (sd / "navmesh").mkdir()
        (sd / "navmesh" / "zone000.nav").write_bytes(b"nav")
        (sd / "daoc-server.sh").write_text("#!/bin/sh\necho stopped\n")
        (sd / "daoc-server.sh").chmod(0o755)
        for name in server.USER_DIRS:
            (sd / name).mkdir()
            (sd / name / "builder.txt").write_text("the builder's own")
        pins.record_installed(build, "server", dict(self.pin, ref=ref or self.ref))
        return server.pack(build, "0.35", ref or self.ref, self.tmp / "out")

    def ship(self, tarball, sha=None):
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["versions"]["0.35"]["server"]["prebuilt"] = {
            "url": f"https://example.invalid/{tarball.name}",
            "bytes": tarball.stat().st_size, "sha256": sha or sha256(tarball)}
        path.write_text(json.dumps(manifest))

    def existing_install(self):
        sd = self.co.server_dir
        (sd / "bin").mkdir(parents=True)
        (sd / "bin" / "old.dll").write_text("old")
        (sd / "config").mkdir()
        (sd / "config" / "serverconfig.xml").write_text("mine")
        (sd / "data").mkdir()
        (sd / "data" / "opendaoc.sqlite3.db").write_text("my save")

    def install(self, tarball, *argv):
        def fetch(url, dest):
            shutil.copyfile(tarball, dest)
        with mock.patch.object(release, "download", fetch):
            return run_cli(["server", "install", *argv], self.root,
                           env={"PATH": f"{self.stubs}:/usr/bin:/bin"})

    def test_pack_leaves_user_folders_out_and_keeps_links(self):
        tarball = self.built_tarball()
        self.assertEqual(tarball.name, f"daoc-server-0.35-{self.ref[:12]}-osx-arm64.tar.xz")
        with tarfile.open(tarball) as archive:
            members = {m.name: m for m in archive.getmembers()}
        self.assertTrue(members["daoc-server/bin/config"].issym())
        self.assertEqual(members["daoc-server/bin/config"].linkname, "../config")
        self.assertIn("daoc-server/navmesh/zone000.nav", members)
        self.assertIn("daoc-server/.daoc-pin.json", members)
        self.assertEqual([n for n in members if n.split("/")[1:2] and n.split("/")[1] in server.USER_DIRS], [])

    def test_pack_refuses_an_install_built_from_another_commit(self):
        self.built_tarball()
        build = Checkout(self.root, home=self.tmp / "builder")
        with self.assertRaises(server.DaocError):
            server.pack(build, "0.35", "f" * 40, self.tmp / "out")

    def test_installs_the_prebuilt_server_and_keeps_the_save(self):
        tarball = self.built_tarball()
        self.ship(tarball)
        self.existing_install()
        code, _, err = self.install(tarball)
        self.assertEqual(code, 0, err)
        sd = self.co.server_dir
        self.assertTrue((sd / "bin" / "CoreServer").is_file())
        self.assertFalse((sd / "bin" / "old.dll").exists())
        self.assertEqual(os.readlink(sd / "bin" / "config"), "../config")
        self.assertEqual((sd / "config" / "serverconfig.xml").read_text(), "mine")
        self.assertEqual((sd / "data" / "opendaoc.sqlite3.db").read_text(), "my save")
        self.assertEqual((sd / "config" / "edition").read_text(), "sluaghbinder\n")
        record = pins.installed(self.co, "server")
        self.assertEqual(record["ref"], self.ref)
        self.assertNotIn("prebuilt", record)
        self.assertEqual(stub_calls(self.stubs), [])

    def test_a_checksum_mismatch_changes_nothing(self):
        tarball = self.built_tarball()
        self.ship(tarball, sha="0" * 64)
        self.existing_install()
        code, _, err = self.install(tarball)
        self.assertEqual(code, 1)
        self.assertIn("failed SHA-256 verification", err)
        self.assertTrue((self.co.server_dir / "bin" / "old.dll").exists())

    def test_a_tarball_built_from_another_commit_is_refused(self):
        tarball = self.built_tarball(ref="f" * 40)
        self.ship(tarball)
        self.existing_install()
        code, _, err = self.install(tarball)
        self.assertEqual(code, 1)
        self.assertIn("built from ffffffffffff", err)
        self.assertTrue((self.co.server_dir / "bin" / "old.dll").exists())

    def adversarial(self, name, data=b"x", link=None):
        tarball = self.tmp / "bad.tar.xz"
        with tarfile.open(tarball, "w:xz") as archive:
            info = tarfile.TarInfo(name)
            if link is None:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                info.type, info.linkname = tarfile.SYMTYPE, link
                archive.addfile(info)
        return tarball

    def test_user_folders_escaping_paths_and_outside_links_are_refused(self):
        self.existing_install()
        for tarball, words in ((self.adversarial("daoc-server/data/opendaoc.sqlite3.db"), "holds data/"),
                               (self.adversarial("daoc-server/../evil"), "unexpected member"),
                               (self.adversarial("elsewhere/x"), "unexpected member"),
                               (self.adversarial("daoc-server/bin/x", link="../../../etc"), "points outside")):
            self.ship(tarball)
            code, _, err = self.install(tarball)
            self.assertEqual(code, 1, err)
            self.assertIn(words, err)
            self.assertEqual((self.co.server_dir / "data" / "opendaoc.sqlite3.db").read_text(), "my save")


if __name__ == "__main__":
    unittest.main()
```

In `tests/test_server.py` `InstallTest`, add:

```python
    def test_from_source_builds_even_with_a_prebuilt_pinned(self):
        path = self.root / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["versions"]["0.35"]["server"]["prebuilt"] = {"url": "https://x/y.tar.xz", "bytes": 1, "sha256": "0" * 64}
        path.write_text(json.dumps(manifest))
        code, _, err = run_cli(["server", "install", "--from-source"], self.root, env=self.env)
        self.assertEqual(code, 0, err)
        self.assertEqual([c[0] for c in stub_calls(self.stubs)][-1], "build-release.sh")
```

(add `import json` to `tests/test_server.py`).

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_server_prebuilt -v`
Expected: FAIL (`AttributeError: module 'daoc_cli.server' has no attribute 'USER_DIRS'`).

- [ ] **Step 3: Implement**

In `daoc_cli/server.py`: add `import json` and `from daoc_cli import release` to the imports. Update the module docstring's `install:` section to start with:

```
install:
  When the effective server pin has `prebuilt` (written by `daoc dev ship-prebuilt`),
  download that tarball, verify its size and SHA-256 and its .daoc-pin.json commit,
  and replace only the top-level entries it holds: config/ data/ logs/ run/ are the
  user's and never come from it. Otherwise (or with --from-source) build from source:
```

Add after `EDITION_FILE`:

```python
# The prebuilt server tarball (`daoc dev pack-server`): one root folder, the
# build's own files; never the user's folders.
PREBUILT_ROOT = "daoc-server"
USER_DIRS = ("config", "data", "logs", "run")


def prebuilt_name(version: str, ref: str) -> str:
    return f"daoc-server-{version}-{ref[:12]}-osx-arm64.tar.xz"
```

In `install`, insert before the `code = …` guard added in Task 8:

```python
    pin = pin if pin is not None else pins.effective(checkout, "server", version)
    if pin.get("prebuilt") and not from_source:
        _install_prebuilt(checkout, pin)
        return
```

(and remove the later duplicate `pin = pin if pin is not None else …` line).

Add the helpers below `install`:

```python
def _install_prebuilt(checkout: Checkout, pin: Dict[str, Any]) -> None:
    prebuilt = pin["prebuilt"]
    name = release.plain_name(prebuilt["url"].rsplit("/", 1)[-1], "server.prebuilt url")
    cache = checkout.downloads / "server"
    cache.mkdir(parents=True, exist_ok=True)
    tarball = cache / name
    say(f"fetching the server ({int(prebuilt['bytes']) // 1024 ** 2} MB, built from {pin['ref'][:12]})")
    release.fetch_verified(prebuilt["url"], tarball, prebuilt.get("bytes"), prebuilt["sha256"],
                           release.download)
    if running(checkout) is not False:
        raise DaocError("the server is running; stop it first (daoc server stop)", 2)
    dest = checkout.server_dir
    stage = dest.parent / ".daoc-server.new"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    try:
        say("unpacking the server")
        _extract_prebuilt(tarball, stage)
        try:
            record = json.loads((stage / pins.INSTALLED).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        built = str(record.get("ref") or "")
        if built != pin["ref"]:
            raise DaocError(f"{name} was built from {built[:12] or 'an unknown commit'}, "
                            f"not the pinned {pin['ref'][:12]}")
        pins.forget_installed(checkout, "server")
        dest.mkdir(parents=True, exist_ok=True)
        for entry in sorted(stage.iterdir()):
            target = dest / entry.name
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or target.is_symlink():
                target.unlink()
            entry.rename(target)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    pins.record_installed(checkout, "server", {k: v for k, v in pin.items() if k != "prebuilt"})
    say("install-server: done; start it with daoc server start")


def _extract_prebuilt(tarball: Path, stage: Path) -> None:
    """Unpack the tarball's PREBUILT_ROOT folder into stage. Refused: a member
    outside that folder or with `..`, a link that points outside it, anything
    but files, folders and symlinks, and the user's folders."""
    base = os.path.realpath(stage)
    with tarfile.open(tarball) as archive:
        members = []
        for member in archive.getmembers():
            parts = Path(member.name).parts
            if member.name.startswith("/") or not parts or parts[0] != PREBUILT_ROOT or ".." in parts:
                raise DaocError(f"{tarball.name}: unexpected member {member.name!r}")
            if len(parts) == 1:
                continue
            rel = Path(*parts[1:])
            if rel.parts[0] in USER_DIRS:
                raise DaocError(f"{tarball.name} holds {rel.parts[0]}/, which is the user's")
            if not (member.isfile() or member.isdir() or member.issym()):
                raise DaocError(f"{tarball.name}: {member.name!r} is not a file, folder or symlink")
            if member.issym():
                target = os.path.normpath(os.path.join(base, str(rel.parent), member.linkname))
                if not target.startswith(base + os.sep):
                    raise DaocError(f"{tarball.name}: {member.name!r} points outside the server folder")
            member.name = str(rel)
            members.append(member)
        extra = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        archive.extractall(stage, members=members, **extra)


def pack(checkout: Checkout, version: str, ref: str, out_dir: Path) -> Path:
    """Pack the Server install, built from ref, as the prebuilt tarball in out_dir:
    root folder PREBUILT_ROOT, symlinks kept, the user's folders left out."""
    record = pins.installed(checkout, "server") or {}
    if record.get("ref") != ref:
        raise DaocError(f"the Server install was not built from {ref[:12]}; "
                        f"run daoc dev pack-server {version}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / prebuilt_name(version, ref)

    def keep(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        parts = Path(info.name).parts
        return None if len(parts) > 1 and parts[1] in USER_DIRS else info

    with tarfile.open(path, "w:xz") as archive:
        archive.add(checkout.server_dir, arcname=PREBUILT_ROOT, filter=keep)
    return path
```

- [ ] **Step 4: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_server_prebuilt tests.test_server -v && /usr/bin/python3 -m unittest discover -s tests`
Expected: PASS / `OK`.

- [ ] **Step 5: Commit**

```bash
git add daoc_cli/server.py tests/test_server_prebuilt.py tests/test_server.py
git commit -m "feat(server): install a pinned prebuilt server without a build toolchain"
```

---

### Task 10: `daoc dev pack-server` and `daoc dev ship-prebuilt`

**Files:**
- Modify: `daoc_cli/pins.py` (`_read_manifest`, `ship` uses it, `ship_field`)
- Modify: `daoc_cli/dev.py` (two actions, docstring)
- Test: `tests/test_dev.py`

**Interfaces:**
- Consumes: `server.install(..., pin=, from_source=True)`, `server.pack`, `server.prebuilt_name`.
- Produces: `pins.ship_field(checkout, group: str, version: str, key: str, value: Any) -> None`.
- CLI: `daoc dev pack-server VERSION [--out DIR]` prints the tarball path on stdout; `daoc dev ship-prebuilt VERSION TARBALL URL`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_dev.py` (import `hashlib`, `json`, `tempfile`, `Path`, and `from daoc_cli import pins, server` if missing):

```python
class ShipPrebuiltTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = make_checkout(self.tmp)
        self.ref = pins.shipped(Checkout(self.root), "server", "0.37")["ref"]

    def test_writes_url_size_and_hash(self):
        tarball = self.tmp / server.prebuilt_name("0.37", self.ref)
        tarball.write_bytes(b"tarball")
        url = ("https://github.com/trozzelle/OfflineDAoC-macOS/releases/download/"
               f"server-0.37-{self.ref[:12]}/{tarball.name}")
        code, out, err = run_cli(["dev", "ship-prebuilt", "0.37", str(tarball), url], self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(out, f"shipped server@0.37 prebuilt {tarball.name}\nnow commit manifest.json\n")
        entry = json.loads((self.root / "manifest.json").read_text())["versions"]["0.37"]["server"]
        self.assertEqual(entry["prebuilt"], {"url": url, "bytes": 7,
                                             "sha256": hashlib.sha256(b"tarball").hexdigest()})
        self.assertEqual(entry["ref"], self.ref)

    def test_refuses_a_tarball_of_another_commit_or_a_mismatched_url(self):
        other = self.tmp / server.prebuilt_name("0.37", "f" * 40)
        other.write_bytes(b"x")
        self.assertEqual(run_cli(["dev", "ship-prebuilt", "0.37", str(other),
                                  f"https://x/{other.name}"], self.root)[0], 2)
        right = self.tmp / server.prebuilt_name("0.37", self.ref)
        right.write_bytes(b"x")
        self.assertEqual(run_cli(["dev", "ship-prebuilt", "0.37", str(right),
                                  "https://x/another-name.tar.xz"], self.root)[0], 2)
```

(add `import shutil` and `from daoc_cli.checkout import Checkout` as needed).

- [ ] **Step 2: Run them to verify they fail**

Run: `/usr/bin/python3 -m unittest tests.test_dev.ShipPrebuiltTest -v`
Expected: FAIL (`invalid choice: 'ship-prebuilt'`).

- [ ] **Step 3: `pins.ship_field`**

In `daoc_cli/pins.py`, factor the manifest read out of `ship` and add `ship_field`:

```python
def _read_manifest(checkout: Checkout) -> Tuple[Path, str, Dict[str, Any]]:
    path = checkout.root / "manifest.json"
    try:
        text = path.read_text(encoding="utf-8")
        return path, text, json.loads(text)
    except FileNotFoundError:
        raise DaocError(f"{path} is missing") from None
    except (OSError, ValueError) as e:
        raise DaocError(f"cannot read {path}: {e}") from None


def ship_field(checkout: Checkout, group: str, version: str, key: str, value: Any) -> None:
    """Set one field of a game version's Shipped pin in manifest.json, keeping
    the layout, the key order and the entry's note."""
    path, text, manifest = _read_manifest(checkout)
    holder = (manifest.get("versions") or {}).get(version) or {}
    entry = holder.get(group)
    if not isinstance(entry, dict):
        raise DaocError(f"manifest.json has no {label(group, version)} pin", 2)
    holder[group] = _merge(entry, dict({k: v for k, v in entry.items() if k != "note"}, **{key: value}))
    atomic_write(path, _dump(manifest) + ("\n" if text.endswith("\n") else ""))
    checkout.__dict__.pop("manifest", None)
```

In `ship`, replace its `path = …` / `try … except` block with `path, text, manifest = _read_manifest(checkout)`.

- [ ] **Step 4: The two `dev` actions**

In `daoc_cli/dev.py`: imports `from daoc_cli import e2e, edition_sql, games, pins, server` and `from daoc_cli.files import sha256`. Add to `register` before `edition-sql`:

```python
    a = actions.add_parser(
        "pack-server", help="build a game version's Shipped server pin and pack the prebuilt tarball",
        description="Build the Shipped server pin of VERSION from source into the data home "
                    "(DAOC_DATA), then pack it as the prebuilt tarball; prints its path.",
    )
    a.add_argument("game_version", metavar="VERSION", help="game version, e.g. 0.37")
    a.add_argument("--out", type=Path, default=Path("dist"), help="folder for the tarball (default: dist)")
    a.set_defaults(func=_pack_server)
    a = actions.add_parser(
        "ship-prebuilt", help="write a prebuilt server tarball's url, size and hash into manifest.json",
        description="Write versions.VERSION.server.prebuilt for a tarball made by pack-server "
                    "from that version's Shipped server pin.",
    )
    a.add_argument("game_version", metavar="VERSION", help="game version, e.g. 0.37")
    a.add_argument("tarball", type=Path, help="the tarball pack-server wrote")
    a.add_argument("url", help="where the release serves it (https://…/<tarball name>)")
    a.set_defaults(func=_ship_prebuilt)
```

```python
def _known(checkout: Checkout, version: str) -> None:
    if version not in games.versions(checkout):
        raise DaocError(f"no game version {version} (expected one of: "
                        f"{', '.join(games.versions(checkout))})", 2)


def _pack_server(args: argparse.Namespace, checkout: Checkout) -> int:
    _known(checkout, args.game_version)
    pin = pins.shipped(checkout, "server", args.game_version)
    server.install(checkout, args.game_version, pin=pin, from_source=True)
    print(server.pack(checkout, args.game_version, pin["ref"], args.out.resolve()))
    return 0


def _ship_prebuilt(args: argparse.Namespace, checkout: Checkout) -> int:
    version, tarball, url = args.game_version, args.tarball, args.url
    _known(checkout, version)
    if pins.local(checkout, "server", version):
        raise DaocError(f"server@{version} has a Local pin; ship it first (daoc dev ship-pins)", 2)
    want = server.prebuilt_name(version, pins.shipped(checkout, "server", version)["ref"])
    if tarball.name != want:
        raise DaocError(f"{tarball.name} is not the Shipped server@{version}'s tarball ({want})", 2)
    if not url.startswith("https://") or not url.endswith("/" + tarball.name):
        raise DaocError(f"the url must be https and end with /{tarball.name}", 2)
    if not tarball.is_file():
        raise DaocError(f"{tarball} is missing", 2)
    pins.ship_field(checkout, "server", version, "prebuilt",
                    {"url": url, "bytes": tarball.stat().st_size, "sha256": sha256(tarball)})
    print(f"shipped server@{version} prebuilt {tarball.name}")
    print("now commit manifest.json")
    return 0
```

Extend the `dev.py` docstring: "pack-server builds a version's Shipped server pin and packs the prebuilt tarball; ship-prebuilt writes that tarball's url, size and hash into manifest.json (the server-prebuilt workflow runs both)."

- [ ] **Step 5: Run the tests**

Run: `/usr/bin/python3 -m unittest tests.test_dev -v && /usr/bin/python3 -m unittest discover -s tests`
Expected: PASS / `OK` (including the existing `ShipPinsTest`).

- [ ] **Step 6: Smoke the maintainer path on this Mac**

Run (builds the real 0.37 server, ~10 min):

```bash
DAOC_DATA="$(mktemp -d)" ./daoc dev pack-server 0.37 --out /tmp/daoc-prebuilt
```

Expected: last stdout line `/tmp/daoc-prebuilt/daoc-server-0.37-<ref12>-osx-arm64.tar.xz`. Then install it into a second scratch home through a throwaway manifest pin:

```bash
T=/tmp/daoc-prebuilt/$(ls /tmp/daoc-prebuilt); S=$(mktemp -d); mkdir "$S/co"
rsync -a --exclude .git --exclude downloads --exclude dist --exclude upstream --exclude server/dist ./ "$S/co/" && cd "$S/co"
./daoc dev ship-prebuilt 0.37 "$T" "https://example.invalid/$(basename "$T")"
mkdir -p "$S/data/downloads/server" && cp "$T" "$S/data/downloads/server/"
DAOC_DATA="$S/data" ./daoc game switch 0.37b && DAOC_DATA="$S/data" ./daoc server start --detach \
  && DAOC_DATA="$S/data" ./daoc admin status && DAOC_DATA="$S/data" ./daoc server stop
cd - && rm -rf "$S"
```

Expected: `game switch` prints `fetching the server` and `unpacking the server` (no clone, no build), the detached start returns `Server running (pid N)`, and `admin status` answers.

- [ ] **Step 7: Commit**

```bash
git add daoc_cli/pins.py daoc_cli/dev.py tests/test_dev.py
git commit -m "feat(dev): pack-server and ship-prebuilt for the prebuilt server"
```

---

## Phase 2: CI for the Python side

### Task 11: Bundled-Python test job and `app/python.lock`

**Files:**
- Create: `app/python.lock`
- Modify: `.github/workflows/tests.yml`

**Interfaces:**
- Produces: `app/python.lock`, sh-sourceable: `PYTHON_URL`, `PYTHON_SHA256` (used by Task 19's `build-app.sh` and here).

- [ ] **Step 1: Write `app/python.lock`**

```sh
# The standalone Python embedded in OfflineDAoC.app (app/build-app.sh) and used by
# the bundled-Python test job (.github/workflows/tests.yml). Move both lines together.
PYTHON_URL=https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-aarch64-apple-darwin-install_only_stripped.tar.gz
PYTHON_SHA256=353d5f1b4fd2715e7053f12f068435d5bbad16b91e057006b5d01e0925709a7e
```

- [ ] **Step 2: Verify the pin locally and run the suite on it**

```bash
. app/python.lock && curl -fsSL "$PYTHON_URL" -o /tmp/pbs.tar.gz \
  && echo "$PYTHON_SHA256  /tmp/pbs.tar.gz" | shasum -a 256 -c - \
  && rm -rf /tmp/pbs && mkdir /tmp/pbs && tar -xzf /tmp/pbs.tar.gz -C /tmp/pbs --strip-components 1 \
  && /tmp/pbs/bin/python3 -m unittest discover -s tests
```

Expected: `/tmp/pbs.tar.gz: OK` then `OK`.

- [ ] **Step 3: Add the jobs to `tests.yml`**

Append under `jobs:`:

```yaml
  unittest-bundled-python:
    # The interpreter OfflineDAoC.app ships (app/python.lock).
    if: github.event_name == 'push' || github.event.pull_request.head.repo.full_name != github.repository
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
      - name: Fetch the bundled Python
        run: |
          . app/python.lock
          curl -fsSL "$PYTHON_URL" -o "$RUNNER_TEMP/python.tar.gz"
          echo "$PYTHON_SHA256  $RUNNER_TEMP/python.tar.gz" | shasum -a 256 -c -
          mkdir "$RUNNER_TEMP/python"
          tar -xzf "$RUNNER_TEMP/python.tar.gz" -C "$RUNNER_TEMP/python" --strip-components 1
      - name: Unit tests
        run: '"$RUNNER_TEMP/python/bin/python3" -m unittest discover -s tests -v'

  swift:
    if: github.event_name == 'push' || github.event.pull_request.head.repo.full_name != github.repository
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
      - name: Swift tests
        run: swift test --package-path app
```

(The `swift` job goes green once Task 13 adds the package; commit it now regardless — the next push after Task 13 exercises it.)

- [ ] **Step 4: Commit**

```bash
git add app/python.lock .github/workflows/tests.yml
git commit -m "ci: run the suite on the bundled Python, and the app's Swift tests"
```

---

### Task 12: `server-prebuilt.yml`

**Files:**
- Create: `.github/workflows/server-prebuilt.yml`

**Interfaces:**
- Consumes: `daoc dev pack-server`, `daoc dev ship-prebuilt`; repo environment `main` with `RELEASE_APP_CLIENT_ID` (var) and `RELEASE_APP_PRIVATE_KEY` (secret), as `release-please.yml` uses.
- Produces: release `server-<version>-<ref12>` (prerelease) with the tarball; a PR `feat(server): prebuilt server for <version>`.

- [ ] **Step 1: Write the workflow**

```yaml
name: server-prebuilt

# Build a game version's Shipped server pin, publish it as a prebuilt tarball on
# the release server-<version>-<ref12>, and open a PR pinning it in manifest.json.
# A release tag's manifest cannot name a hash of something built from that tag,
# so the prebuilt is published first and pinned by an ordinary reviewed commit.
on:
  workflow_dispatch:
    inputs:
      version:
        description: "game version, e.g. 0.37"
        required: true

permissions: {}

jobs:
  prebuilt:
    runs-on: macos-latest
    environment: main
    steps:
      - uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1  # v3.2.0
        id: app-token
        with:
          client-id: ${{ vars.RELEASE_APP_CLIENT_ID }}
          private-key: ${{ secrets.RELEASE_APP_PRIVATE_KEY }}
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
        with:
          token: ${{ steps.app-token.outputs.token }}
      - name: Build tools
        run: brew list cmake >/dev/null 2>&1 || brew install cmake
      - name: Build and pack
        env:
          DAOC_DATA: ${{ runner.temp }}/daoc-data
          VERSION_INPUT: ${{ inputs.version }}
        run: |
          tarball=$(./daoc dev pack-server "$VERSION_INPUT" --out "$RUNNER_TEMP/out" | tail -n 1)
          echo "TARBALL=$tarball" >> "$GITHUB_ENV"
      - name: Publish
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
        run: |
          name=$(basename "$TARBALL")
          tag=${name#daoc-}; tag=${tag%-osx-arm64.tar.xz}     # server-<version>-<ref12>
          gh release view "$tag" >/dev/null 2>&1 ||
            gh release create "$tag" --prerelease --title "$tag" \
              --notes "Prebuilt macOS arm64 server, pinned by manifest.json. Not a daoc release."
          gh release upload "$tag" "$TARBALL" --clobber
          echo "URL=https://github.com/$GITHUB_REPOSITORY/releases/download/$tag/$name" >> "$GITHUB_ENV"
      - name: Open the pin PR
        env:
          GH_TOKEN: ${{ steps.app-token.outputs.token }}
          VERSION_INPUT: ${{ inputs.version }}
        run: |
          ./daoc dev ship-prebuilt "$VERSION_INPUT" "$TARBALL" "$URL"
          branch="prebuilt/server-$VERSION_INPUT-$(date -u +%Y%m%d%H%M%S)"
          git switch -c "$branch"
          git -c user.name="daoc-release[bot]" -c user.email="daoc-release[bot]@users.noreply.github.com" \
            commit -am "feat(server): prebuilt server for $VERSION_INPUT"
          git push origin "$branch"
          gh pr create --base main --head "$branch" --fill
```

- [ ] **Step 2: Validate the YAML locally**

Run: `ruby -ryaml -e 'YAML.load_file(".github/workflows/server-prebuilt.yml"); puts "yaml ok"'`
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/server-prebuilt.yml
git commit -m "ci: server-prebuilt publishes a pinned prebuilt server"
```

- [ ] **Step 4: After merge to main — run it for 0.37**

Run: `gh workflow run server-prebuilt.yml -f version=0.37`, wait for the PR, review that its diff adds only `versions.0.37.server.prebuilt`, merge it. Then `/usr/bin/python3 -m unittest discover -s tests` on main still passes (tests that build 0.37 from source stub `server.install` or pass `--from-source`; if any test now hits the prebuilt branch, give it `--from-source` or remove `prebuilt` from its copied manifest).

---

## Phase 3: The app (`app/`)

### Task 13: Swift package, events, answers

**Files:**
- Create: `app/Package.swift`, `app/Sources/DaocKit/Events.swift`, `app/Tests/DaocKitTests/EventTests.swift`, `app/.gitignore`

**Interfaces:**
- Produces: `DaocEvent` (`.step(String)`, `.download(path: String, bytes: Int64?, what: String)`, `.ask(id: Int, question: String, defaultAnswer: Bool)`, `.secret(id: Int, what: String)`, `.error(message: String, code: Int)`, `.unknown(String)`), `EventLineDecoder.feed(_ data: Data) -> [DaocEvent]`, `DaocAnswer.ask(id:answer:) -> Data`, `DaocAnswer.secret(id:account:password:) -> Data`.

- [ ] **Step 1: Package and ignore file**

`app/Package.swift`:

```swift
// swift-tools-version:5.10
import PackageDescription

// OfflineDAoC.app: DaocKit is the tested core (events, the daoc process, models);
// OfflineDAoC is the SwiftUI shell. app/build-app.sh turns the product into the bundle.
let package = Package(
    name: "OfflineDAoC",
    platforms: [.macOS(.v14)],
    targets: [
        .target(name: "DaocKit"),
        .executableTarget(name: "OfflineDAoC", dependencies: ["DaocKit"]),
        .testTarget(name: "DaocKitTests", dependencies: ["DaocKit"]),
    ]
)
```

`app/.gitignore`:

```
.build/
.cache/
dist/
```

Create `app/Sources/OfflineDAoC/Main.swift` with a placeholder-free minimal entry so the package builds (Task 16 replaces it):

```swift
@main
enum Main {
    static func main() {}
}
```

- [ ] **Step 2: Write the failing test**

`app/Tests/DaocKitTests/EventTests.swift`:

```swift
import XCTest
@testable import DaocKit

final class EventTests: XCTestCase {
    func testDecodesEveryEventAcrossChunkBoundaries() {
        let text = """
        {"t":"step","msg":"downloading Wine"}
        {"t":"download","path":"/d/x.part","bytes":1000,"what":"x"}
        {"t":"download","path":"/d/wine.tar.xz","bytes":null,"what":"Wine"}
        {"t":"ask","id":1,"question":"Stop?","default":false}
        {"t":"secret","id":2,"what":"login"}
        {"t":"error","msg":"refused","code":2}
        {"t":"later","x":1}
        not json

        """
        let data = Data(text.utf8)
        var decoder = EventLineDecoder()
        var events = decoder.feed(data.prefix(10))
        events += decoder.feed(data.dropFirst(10))
        XCTAssertEqual(events, [
            .step("downloading Wine"),
            .download(path: "/d/x.part", bytes: 1000, what: "x"),
            .download(path: "/d/wine.tar.xz", bytes: nil, what: "Wine"),
            .ask(id: 1, question: "Stop?", defaultAnswer: false),
            .secret(id: 2, what: "login"),
            .error(message: "refused", code: 2),
            .unknown("later"),
        ])
    }

    func testAnswersAreOneJSONLineTheCLIReads() throws {
        let ask = DaocAnswer.ask(id: 3, answer: true)
        XCTAssertEqual(ask.last, 0x0A)
        XCTAssertEqual(String(decoding: ask, as: UTF8.self), "{\"answer\":true,\"id\":3}\n")
        let secret = try JSONSerialization.jsonObject(
            with: DaocAnswer.secret(id: 4, account: "alice", password: "p\"w").dropLast()) as? [String: Any]
        XCTAssertEqual(secret?["id"] as? Int, 4)
        XCTAssertEqual(secret?["account"] as? String, "alice")
        XCTAssertEqual(secret?["password"] as? String, "p\"w")
    }
}
```

- [ ] **Step 3: Run it to verify it fails**

Run: `swift test --package-path app`
Expected: FAIL to compile (`cannot find 'EventLineDecoder' in scope`).

- [ ] **Step 4: Implement `Events.swift`**

```swift
import Foundation

/// One line daoc writes on its DAOC_EVENTS channel (see daoc_cli/events.py).
public enum DaocEvent: Equatable, Sendable {
    case step(String)
    case download(path: String, bytes: Int64?, what: String)
    case ask(id: Int, question: String, defaultAnswer: Bool)
    case secret(id: Int, what: String)
    case error(message: String, code: Int)
    case unknown(String)
}

extension DaocEvent: Decodable {
    private enum Key: String, CodingKey {
        case t, msg, path, bytes, what, id, question, code
        case defaultAnswer = "default"
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: Key.self)
        let kind = try c.decode(String.self, forKey: .t)
        switch kind {
        case "step":
            self = .step(try c.decode(String.self, forKey: .msg))
        case "download":
            self = .download(path: try c.decode(String.self, forKey: .path),
                             bytes: try c.decodeIfPresent(Int64.self, forKey: .bytes),
                             what: try c.decode(String.self, forKey: .what))
        case "ask":
            self = .ask(id: try c.decode(Int.self, forKey: .id),
                        question: try c.decode(String.self, forKey: .question),
                        defaultAnswer: try c.decodeIfPresent(Bool.self, forKey: .defaultAnswer) ?? false)
        case "secret":
            self = .secret(id: try c.decode(Int.self, forKey: .id), what: try c.decode(String.self, forKey: .what))
        case "error":
            self = .error(message: try c.decode(String.self, forKey: .msg), code: try c.decode(Int.self, forKey: .code))
        default:
            self = .unknown(kind)
        }
    }
}

/// Splits the channel's bytes into lines and decodes each. A line that is not an
/// event is dropped: the command's stderr log still has everything.
public struct EventLineDecoder {
    private var buffer = Data()

    public init() {}

    public mutating func feed(_ data: Data) -> [DaocEvent] {
        buffer.append(data)
        var events: [DaocEvent] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            let line = buffer[buffer.startIndex..<newline]
            buffer.removeSubrange(buffer.startIndex...newline)
            if let event = try? JSONDecoder().decode(DaocEvent.self, from: line) {
                events.append(event)
            }
        }
        return events
    }
}

/// Answers to `ask` and `secret`, one JSON line each, for the command's stdin.
public enum DaocAnswer {
    public static func ask(id: Int, answer: Bool) -> Data {
        line(["id": id, "answer": answer])
    }

    public static func secret(id: Int, account: String, password: String) -> Data {
        line(["id": id, "account": account, "password": password])
    }

    private static func line(_ object: [String: Any]) -> Data {
        var data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data()
        data.append(0x0A)
        return data
    }
}
```

- [ ] **Step 5: Run the tests**

Run: `swift test --package-path app`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add app/Package.swift app/.gitignore app/Sources app/Tests
git commit -m "feat(app): Swift package with the daoc event protocol"
```

---

### Task 14: `DaocProcess`: spawn with fd 3, answers, log, interrupt

**Files:**
- Create: `app/Sources/DaocKit/DaocProcess.swift`, `app/Tests/DaocKitTests/DaocProcessTests.swift`

**Interfaces:**
- Consumes: `DaocEvent`, `EventLineDecoder`.
- Produces: `DaocInvocation(launcher: URL, dataHome: URL, arguments: [String], logFile: URL)`; `DaocResult { status: Int32; stdout: Data; events: [DaocEvent]; errorMessage: String? }`; `DaocProcess(_:)`, `run(onEvent:) async throws -> DaocResult`, `answer(_ line: Data)`, `interrupt()`; `DaocProcessError`.
- Environment given to the child: inherited + `DAOC_DATA=<dataHome>`, `DAOC_EVENTS=3`.

- [ ] **Step 1: Write the failing tests**

```swift
import XCTest
@testable import DaocKit

final class DaocProcessTests: XCTestCase {
    private var dir: URL!

    override func setUpWithError() throws {
        dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: dir)
    }

    private func launcher(_ body: String) throws -> URL {
        let url = dir.appendingPathComponent("daoc")
        try ("#!/bin/sh\n" + body).write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        return url
    }

    private func invocation(_ launcher: URL, _ arguments: [String] = []) -> DaocInvocation {
        DaocInvocation(launcher: launcher, dataHome: dir.appendingPathComponent("data"),
                       arguments: arguments, logFile: dir.appendingPathComponent("logs/run.log"))
    }

    func testEventsAnswersStdoutLogAndStatus() async throws {
        let url = try launcher("""
        echo "args $*"
        echo "data $DAOC_DATA events $DAOC_EVENTS"
        echo 'to the log' >&2
        printf '{"t":"ask","id":1,"question":"Stop?","default":false}\\n' >&3
        read answer
        echo "answer $answer"
        printf '{"t":"error","msg":"refused","code":2}\\n' >&3
        exit 2
        """)
        let process = DaocProcess(invocation(url, ["server", "stop"]))
        let result = try await process.run { event in
            if case .ask(let id, _, _) = event { process.answer(DaocAnswer.ask(id: id, answer: true)) }
        }
        XCTAssertEqual(result.status, 2)
        XCTAssertEqual(result.errorMessage, "refused")
        XCTAssertEqual(result.events.first, .ask(id: 1, question: "Stop?", defaultAnswer: false))
        let out = String(decoding: result.stdout, as: UTF8.self)
        XCTAssertTrue(out.contains("args server stop\n"), out)
        XCTAssertTrue(out.contains("data \(dir.appendingPathComponent("data").path) events 3\n"), out)
        XCTAssertTrue(out.contains("answer {\"answer\":true,\"id\":1}\n"), out)
        XCTAssertEqual(try String(contentsOf: dir.appendingPathComponent("logs/run.log"), encoding: .utf8),
                       "to the log\n")
    }

    func testReturnsWhenTheCommandExitsThoughAChildStillHoldsThePipes() async throws {
        // daoc-server.sh start --detach leaves the server running; the app must not wait for it.
        let url = try launcher("sleep 20 &\necho started\n")
        let started = Date()
        let result = try await DaocProcess(invocation(url)).run { _ in }
        XCTAssertEqual(result.status, 0)
        XCTAssertEqual(String(decoding: result.stdout, as: UTF8.self), "started\n")
        XCTAssertLessThan(Date().timeIntervalSince(started), 10)
    }

    func testInterruptReachesTheCommand() async throws {
        let url = try launcher("trap 'exit 130' INT\nwhile :; do sleep 0.1; done\n")
        let process = DaocProcess(invocation(url))
        Task {
            try await Task.sleep(nanoseconds: 500_000_000)
            process.interrupt()
        }
        let result = try await process.run { _ in }
        XCTAssertEqual(result.status, 130)
    }
}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path app`
Expected: FAIL to compile (`cannot find 'DaocProcess' in scope`).

- [ ] **Step 3: Implement `DaocProcess.swift`**

```swift
import Darwin
import Foundation

public struct DaocInvocation: Sendable {
    public var launcher: URL
    public var dataHome: URL
    public var arguments: [String]
    public var logFile: URL

    public init(launcher: URL, dataHome: URL, arguments: [String], logFile: URL) {
        self.launcher = launcher
        self.dataHome = dataHome
        self.arguments = arguments
        self.logFile = logFile
    }
}

public struct DaocResult: Sendable {
    public let status: Int32
    public let stdout: Data
    public let events: [DaocEvent]

    /// The message of the last `error` event, when daoc sent one.
    public var errorMessage: String? {
        for case let .error(message, _) in events.reversed() { return message }
        return nil
    }
}

public enum DaocProcessError: Error, Equatable {
    case log(Int32), pipe(Int32), spawn(Int32)
}

/// One `daoc` command: events on fd 3 (DAOC_EVENTS=3), answers on stdin, stdout
/// captured, stderr appended to the log file. It runs in its own process group so
/// interrupt() reaches what it started. It is done when it exits: whatever it left
/// running (a detached server) may hold the pipes open, so they are drained once,
/// never read to EOF.
public final class DaocProcess: @unchecked Sendable {
    public let invocation: DaocInvocation
    private let queue = DispatchQueue(label: "daoc.process")
    private var pid: pid_t = 0
    private var stdinFD: Int32 = -1

    public init(_ invocation: DaocInvocation) {
        self.invocation = invocation
    }

    /// Runs the command; onEvent is called on a background queue, in order.
    public func run(onEvent: @escaping @Sendable (DaocEvent) -> Void) async throws -> DaocResult {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    try self.start(onEvent: onEvent) { continuation.resume(returning: $0) }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    /// Sends one answer line (DaocAnswer) to the command's stdin.
    public func answer(_ line: Data) {
        queue.async {
            guard self.stdinFD >= 0 else { return }
            line.withUnsafeBytes { buffer in _ = write(self.stdinFD, buffer.baseAddress, buffer.count) }
        }
    }

    /// SIGINT to the command's process group: daoc exits 130 through its own Ctrl-C path.
    public func interrupt() {
        queue.async { if self.pid > 0 { kill(-self.pid, SIGINT) } }
    }

    static func exitCode(_ status: Int32) -> Int32 {
        let signal = status & 0x7f
        return signal == 0 ? (status >> 8) & 0xff : 128 + signal
    }

    private func start(onEvent: @escaping @Sendable (DaocEvent) -> Void,
                       done: @escaping (DaocResult) -> Void) throws {
        try FileManager.default.createDirectory(at: invocation.logFile.deletingLastPathComponent(),
                                                withIntermediateDirectories: true)
        let logFD = open(invocation.logFile.path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0o644)
        guard logFD >= 0 else { throw DaocProcessError.log(errno) }
        var input: [Int32] = [-1, -1], output: [Int32] = [-1, -1], channel: [Int32] = [-1, -1]
        guard pipe(&input) == 0, pipe(&output) == 0, pipe(&channel) == 0 else {
            let error = errno
            for fd in input + output + channel + [logFD] where fd >= 0 { close(fd) }
            throw DaocProcessError.pipe(error)
        }

        var actions: posix_spawn_file_actions_t?
        posix_spawn_file_actions_init(&actions)
        defer { posix_spawn_file_actions_destroy(&actions) }
        posix_spawn_file_actions_adddup2(&actions, input[0], 0)
        posix_spawn_file_actions_adddup2(&actions, output[1], 1)
        posix_spawn_file_actions_adddup2(&actions, logFD, 2)
        posix_spawn_file_actions_adddup2(&actions, channel[1], 3)
        var attributes: posix_spawnattr_t?
        posix_spawnattr_init(&attributes)
        defer { posix_spawnattr_destroy(&attributes) }
        // Only fds 0-3 reach the child; it leads a new process group.
        posix_spawnattr_setflags(&attributes, Int16(POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_CLOEXEC_DEFAULT))
        posix_spawnattr_setpgroup(&attributes, 0)

        var environment = ProcessInfo.processInfo.environment
        environment["DAOC_DATA"] = invocation.dataHome.path
        environment["DAOC_EVENTS"] = "3"
        let argv = [invocation.launcher.path] + invocation.arguments
        let envp = environment.map { "\($0.key)=\($0.value)" }
        var child: pid_t = 0
        let rc = withCStrings(argv) { argvC in
            withCStrings(envp) { envC in
                posix_spawn(&child, invocation.launcher.path, &actions, &attributes, argvC, envC)
            }
        }
        for fd in [input[0], output[1], channel[1], logFD] { close(fd) }
        guard rc == 0 else {
            for fd in [input[1], output[0], channel[0]] { close(fd) }
            throw DaocProcessError.spawn(rc)
        }
        pid = child
        stdinFD = input[1]

        var decoder = EventLineDecoder()
        var events: [DaocEvent] = []
        var stdout = Data()
        let eventReader = Reader(fd: channel[0], queue: queue) { data in
            for event in decoder.feed(data) {
                events.append(event)
                onEvent(event)
            }
        }
        let outputReader = Reader(fd: output[0], queue: queue) { stdout.append($0) }
        Thread.detachNewThread { [queue] in
            var status: Int32 = 0
            while waitpid(child, &status, 0) < 0 && errno == EINTR {}
            queue.async {
                eventReader.pump()
                outputReader.pump()
                eventReader.finish()
                outputReader.finish()
                close(self.stdinFD)
                self.stdinFD = -1
                self.pid = 0
                done(DaocResult(status: Self.exitCode(status), stdout: stdout, events: events))
            }
        }
    }
}

/// A non-blocking pipe read end, pumped by a dispatch source on the process queue.
private final class Reader {
    private let fd: Int32
    private let source: DispatchSourceRead
    private let onData: (Data) -> Void
    private var open = true

    init(fd: Int32, queue: DispatchQueue, onData: @escaping (Data) -> Void) {
        self.fd = fd
        self.onData = onData
        _ = fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK)
        source = DispatchSource.makeReadSource(fileDescriptor: fd, queue: queue)
        source.setEventHandler { [unowned self] in self.pump() }
        source.setCancelHandler { close(fd) }
        source.resume()
    }

    func pump() {
        guard open else { return }
        var buffer = [UInt8](repeating: 0, count: 65536)
        while true {
            let n = read(fd, &buffer, buffer.count)
            if n > 0 {
                onData(Data(buffer[0..<n]))
                continue
            }
            if n < 0 && (errno == EAGAIN || errno == EINTR) { return }
            finish()  // EOF or a read error
            return
        }
    }

    func finish() {
        guard open else { return }
        open = false
        source.cancel()
    }
}

private func withCStrings<R>(_ strings: [String],
                             _ body: (UnsafePointer<UnsafeMutablePointer<CChar>?>) -> R) -> R {
    var pointers: [UnsafeMutablePointer<CChar>?] = strings.map { strdup($0) }
    pointers.append(nil)
    defer { pointers.forEach { free($0) } }
    return pointers.withUnsafeBufferPointer { body($0.baseAddress!) }
}
```

- [ ] **Step 4: Run the tests**

Run: `swift test --package-path app`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/Sources/DaocKit/DaocProcess.swift app/Tests/DaocKitTests/DaocProcessTests.swift
git commit -m "feat(app): run daoc with an event pipe, answers and a log"
```

---

### Task 15: Models: status, bots, Setup plan, release check, wrapper file

**Files:**
- Create: `app/Sources/DaocKit/Models.swift`, `app/Tests/DaocKitTests/ModelTests.swift`

**Interfaces:**
- Produces: `StatusSnapshot` (fields mirror Task 6 JSON in camelCase; `static func decode(_ data: Data) throws -> StatusSnapshot`), `Bot`, `Realm` (`.albion/.midgard/.hibernia`, `rawValue` = JSON realm, `adminName` = `alb/mid/hib`), `RealmCount`, `BotRoster.counts(_:) -> [RealmCount]`, `Population { enabled: Bool }`, `SetupChoice(game:newClient:arm64Wine:)`, `SetupPlan.commands(for:status:) -> [[String]]`, `SetupPlan.isComplete(_:) -> Bool`, `ReleaseCheck.isNewer(tag:than:) -> Bool`, `WrapperFile.dataFolder(fromWrapper:) -> String?`.

- [ ] **Step 1: Write the failing tests**

```swift
import XCTest
@testable import DaocKit

final class ModelTests: XCTestCase {
    private func status(server: Bool, original: Bool, game: String = "0.37b",
                        switching: String? = nil, account: Bool? = nil) throws -> StatusSnapshot {
        let json = """
        {"schema": 1, "version": "0.4.0", "home": "/h",
         "game": {"name": "\(game)", "version": "0.37", "edition": "sluaghbinder"},
         "client": "original", "switching_to": \(switching.map { "\"\($0)\"" } ?? "null"),
         "installed": {"server": \(server), "original_client": \(original), "new_client": false},
         "wine": "rosetta", "server": {"running": null, "detail": "x"},
         "client_running": null, "account_saved": \(account.map { "\($0)" } ?? "null"), "save": null}
        """
        return try StatusSnapshot.decode(Data(json.utf8))
    }

    func testStatusDecodesTheCLIsJSON() throws {
        let s = try status(server: true, original: false, account: true)
        XCTAssertEqual(s.game.name, "0.37b")
        XCTAssertTrue(s.installed.server)
        XCTAssertNil(s.server.running)
        XCTAssertEqual(s.accountSaved, true)
    }

    func testAFreshSetupSwitchesThenInstallsTheClients() {
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37b", newClient: true, arm64Wine: true), status: nil), [
            ["game", "switch", "0.37b"],
            ["client", "install", "--wine", "arm64"],
            ["client", "install", "--client", "new"],
        ])
    }

    func testAResumedSetupSkipsWhatIsDone() throws {
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37b"), status: try status(server: true, original: false)),
                       [["client", "install"]])
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37"), status: try status(server: true, original: true)),
                       [["game", "switch", "0.37"]])
        XCTAssertEqual(SetupPlan.commands(for: SetupChoice(game: "0.37b"),
                                          status: try status(server: true, original: true, switching: "0.37b")),
                       [["game", "switch", "0.37b"]])
    }

    func testSetupIsCompleteWithAServerAClientAndASavedAccount() throws {
        XCTAssertTrue(SetupPlan.isComplete(try status(server: true, original: true, account: true)))
        XCTAssertFalse(SetupPlan.isComplete(try status(server: true, original: true, account: nil)))
        XCTAssertFalse(SetupPlan.isComplete(try status(server: true, original: false, account: true)))
    }

    func testRealmCountsLeaveOutBotsBeingDeleted() throws {
        let json = """
        [{"id":1,"name":"Aldric","realm":"Albion","class":"Armsman","race":"Briton","level":12,"zone":"","activity":"","goal":"","online":true,"deleting":false},
         {"id":2,"name":"Siv","realm":"Midgard","class":"Healer","race":"Norseman","level":1,"zone":"","activity":"","goal":"","online":false,"deleting":true},
         {"id":3,"name":"Bran","realm":"Albion","class":"Cleric","race":"Briton","level":50,"zone":"","activity":"","goal":"","online":false,"deleting":false}]
        """
        let bots = try JSONDecoder().decode([Bot].self, from: Data(json.utf8))
        XCTAssertEqual(BotRoster.counts(bots), [
            RealmCount(realm: .albion, roster: 2, online: 1),
            RealmCount(realm: .midgard, roster: 0, online: 0),
            RealmCount(realm: .hibernia, roster: 0, online: 0),
        ])
    }

    func testReleaseCheck() {
        XCTAssertTrue(ReleaseCheck.isNewer(tag: "v0.5.0", than: "0.4.0"))
        XCTAssertTrue(ReleaseCheck.isNewer(tag: "v0.4.10", than: "0.4.9"))
        XCTAssertFalse(ReleaseCheck.isNewer(tag: "v0.4.0", than: "0.4.0"))
        XCTAssertFalse(ReleaseCheck.isNewer(tag: "v0.3.9", than: "0.4.0"))
    }

    func testWrapperFileNamesItsDataFolder() {
        let marker = WrapperFile.marker
        XCTAssertEqual(WrapperFile.dataFolder(fromWrapper: "#!/bin/sh\n\(marker)\nCHECKOUT='/a b/it'\"'\"'s'\nexec x\n"),
                       "/a b/it's")
        XCTAssertEqual(WrapperFile.dataFolder(fromWrapper: "#!/bin/sh\n\(marker)\nCHECKOUT=/app/Resources/daoc\nDAOC_DATA=/d\nexport DAOC_DATA\n"),
                       "/d")
        XCTAssertNil(WrapperFile.dataFolder(fromWrapper: "#!/bin/sh\nCHECKOUT=/x\n"))
    }
}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `swift test --package-path app`
Expected: FAIL to compile (`cannot find 'StatusSnapshot' in scope`).

- [ ] **Step 3: Implement `Models.swift`**

```swift
import Foundation

/// `daoc status --json` (daoc_cli/status.py, schema 1).
public struct StatusSnapshot: Decodable, Equatable, Sendable {
    public struct Game: Decodable, Equatable, Sendable {
        public let name: String
        public let version: String
        public let edition: String
    }

    public struct Installed: Decodable, Equatable, Sendable {
        public let server: Bool
        public let originalClient: Bool
        public let newClient: Bool
    }

    public struct Server: Decodable, Equatable, Sendable {
        public let running: Bool?
        public let detail: String
    }

    public let schema: Int
    public let version: String
    public let home: String
    public let game: Game
    public let client: String
    public let switchingTo: String?
    public let installed: Installed
    public let wine: String?
    public let server: Server
    public let clientRunning: String?
    public let accountSaved: Bool?
    public let save: String?

    public static func decode(_ data: Data) throws -> StatusSnapshot {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(StatusSnapshot.self, from: data)
    }
}

/// One entry of `daoc admin bots list --json`; the other keys are ignored.
public struct Bot: Decodable, Equatable, Sendable {
    public let name: String
    public let realm: String
    public let level: Int
    public let online: Bool
    public let deleting: Bool
}

/// `daoc admin population --json`; the other keys are ignored.
public struct Population: Decodable, Equatable, Sendable {
    public let enabled: Bool
}

public enum Realm: String, CaseIterable, Sendable {
    case albion = "Albion", midgard = "Midgard", hibernia = "Hibernia"

    /// The name `daoc-admin bots create --realm` takes.
    public var adminName: String {
        switch self {
        case .albion: return "alb"
        case .midgard: return "mid"
        case .hibernia: return "hib"
        }
    }
}

public struct RealmCount: Equatable, Sendable {
    public let realm: Realm
    public let roster: Int
    public let online: Int

    public init(realm: Realm, roster: Int, online: Int) {
        self.realm = realm
        self.roster = roster
        self.online = online
    }
}

public enum BotRoster {
    /// Roster and in-world counts per realm, every realm listed; bots queued for deletion left out.
    public static func counts(_ bots: [Bot]) -> [RealmCount] {
        let kept = bots.filter { !$0.deleting }
        return Realm.allCases.map { realm in
            let mine = kept.filter { $0.realm == realm.rawValue }
            return RealmCount(realm: realm, roster: mine.count, online: mine.filter(\.online).count)
        }
    }
}

public struct SetupChoice: Equatable, Sendable {
    public var game: String
    public var newClient: Bool
    public var arm64Wine: Bool

    public init(game: String = "0.37b", newClient: Bool = false, arm64Wine: Bool = false) {
        self.game = game
        self.newClient = newClient
        self.arm64Wine = arm64Wine
    }
}

public enum SetupPlan {
    /// The daoc commands Setup runs, in order, leaving out what status says is done.
    /// `game switch` on an empty data home installs the server, writes its edition and
    /// records the Selection, and installs no client.
    public static func commands(for choice: SetupChoice, status: StatusSnapshot?) -> [[String]] {
        var commands: [[String]] = []
        let installed = status?.installed
        if !(installed?.server ?? false) || status?.game.name != choice.game || status?.switchingTo != nil {
            commands.append(["game", "switch", choice.game])
        }
        if !(installed?.originalClient ?? false) {
            commands.append(["client", "install"] + (choice.arm64Wine ? ["--wine", "arm64"] : []))
        }
        if choice.newClient && !(installed?.newClient ?? false) {
            commands.append(["client", "install", "--client", "new"])
        }
        return commands
    }

    public static func isComplete(_ status: StatusSnapshot) -> Bool {
        status.installed.server && (status.installed.originalClient || status.installed.newClient)
            && status.accountSaved == true
    }
}

public enum ReleaseCheck {
    /// Whether a release tag (v0.5.0) is newer than version.txt's version (0.4.0).
    public static func isNewer(tag: String, than current: String) -> Bool {
        func parts(_ s: String) -> [Int] {
            s.trimmingCharacters(in: CharacterSet(charactersIn: "v")).split(separator: ".").map { Int($0) ?? 0 }
        }
        let a = parts(tag), b = parts(current)
        for i in 0..<max(a.count, b.count) {
            let x = i < a.count ? a[i] : 0, y = i < b.count ? b[i] : 0
            if x != y { return x > y }
        }
        return false
    }
}

/// The ~/.local/bin/daoc wrapper `daoc self-install` writes (daoc_cli/self_install.py).
public enum WrapperFile {
    public static let marker = "# daoc wrapper written by daoc self-install"

    /// The data folder a wrapper names: its DAOC_DATA, else its CHECKOUT; nil for any other file.
    public static func dataFolder(fromWrapper text: String) -> String? {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        guard lines.contains(marker) else { return nil }
        func value(_ key: String) -> String? {
            lines.first { $0.hasPrefix(key + "=") }.flatMap { unquote(String($0.dropFirst(key.count + 1))) }
        }
        return value("DAOC_DATA") ?? value("CHECKOUT")
    }

    /// Undoes Python's shlex.quote: 'a b', with '"'"' for a quote inside.
    static func unquote(_ s: String) -> String? {
        guard s.hasPrefix("'") else { return s.isEmpty ? nil : s }
        guard s.count >= 2, s.hasSuffix("'") else { return nil }
        return String(s.dropFirst().dropLast()).replacingOccurrences(of: "'\"'\"'", with: "'")
    }
}
```

- [ ] **Step 4: Run the tests**

Run: `swift test --package-path app`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add app/Sources/DaocKit/Models.swift app/Tests/DaocKitTests/ModelTests.swift
git commit -m "feat(app): status, bots, Setup plan and release models"
```

---

### Task 16: App shell: paths, model, root view, sheets, self-test, quit

**Files:**
- Replace: `app/Sources/OfflineDAoC/Main.swift`
- Create: `app/Sources/OfflineDAoC/AppPaths.swift`, `AppModel.swift`, `RootView.swift`, `Sheets.swift`, `RunProgressView.swift`, `SystemChecks.swift`, `SelfTest.swift`, `AppDelegate.swift`

**Interfaces:**
- Consumes: everything in DaocKit.
- Produces (used by Tasks 17-18): `AppModel.shared` (`@MainActor`), published `mode` (`.loading/.setup/.launcher`), `status`, `running: RunState?`, `pendingAsk`, `pendingSecret`, `failure`, `realms`, `population`, `notice`, `appUpdate`, `paths`; methods `start()`, `adopt(_:)`, `run(_:_:login:) async -> Bool`, `capture(_:) async -> Data?`, `refreshStatus()`, `refreshBots()`, `answer(_:_:)`, `answer(_:account:password:)`, `cancel(_:)`, `stop()`, `play()`, `createAccount(_:_:) async -> Bool`, `createBots(_:level:count:)`, `setPopulation(_:)`, `openAdminConsole()`, `showLogs()`, `checkForClientUpdates()`. Views `RunProgressView(run:)`, `CheckRow(_:ok:)`. `SystemChecks.isAppleSilicon/macOSMajor/rosettaInstalled/freeBytes()/installRosetta()/existingInstall()`.

- [ ] **Step 1: `AppPaths.swift`**

```swift
import Foundation

/// Where the bundled daoc lives and where it installs.
struct AppPaths {
    static let dataHomeKey = "dataHome"

    let resources: URL
    var dataHome: URL

    /// Contents/Resources/daoc/daoc: the repo's ./daoc launcher, next to Resources/python.
    var launcher: URL { resources.appendingPathComponent("daoc/daoc") }
    var logs: URL { dataHome.appendingPathComponent("logs/app", isDirectory: true) }
    var serverLogs: URL { dataHome.appendingPathComponent("server/dist/daoc-server/logs", isDirectory: true) }

    static func current() -> AppPaths {
        let resources = Bundle.main.resourceURL ?? URL(fileURLWithPath: CommandLine.arguments[0]).deletingLastPathComponent()
        let saved = UserDefaults.standard.string(forKey: dataHomeKey)
        return AppPaths(resources: resources, dataHome: saved.map { URL(fileURLWithPath: $0, isDirectory: true) } ?? defaultDataHome)
    }

    static var defaultDataHome: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("OfflineDAoC", isDirectory: true)
    }

    func logFile(for arguments: [String]) -> URL {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyyMMdd-HHmmss"
        let name = ([formatter.string(from: Date())] + arguments.prefix(2)).joined(separator: "-")
        return logs.appendingPathComponent(name + ".log")
    }
}
```

- [ ] **Step 2: `SystemChecks.swift`**

```swift
import AppKit
import DaocKit
import Foundation

enum SystemChecks {
    static var isAppleSilicon: Bool {
        var value: Int32 = 0
        var size = MemoryLayout<Int32>.size
        return sysctlbyname("hw.optional.arm64", &value, &size, nil, 0) == 0 && value == 1
    }

    static var macOSMajor: Int { ProcessInfo.processInfo.operatingSystemVersion.majorVersion }

    static var rosettaInstalled: Bool {
        FileManager.default.fileExists(atPath: "/Library/Apple/usr/libexec/oah/libRosettaRuntime")
    }

    static func freeBytes() -> Int64 {
        let values = try? FileManager.default.homeDirectoryForCurrentUser
            .resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey])
        return values?.volumeAvailableCapacityForImportantUsage ?? 0
    }

    /// macOS asks for an administrator password itself.
    @MainActor static func installRosetta() -> Bool {
        var error: NSDictionary?
        NSAppleScript(source: "do shell script \"/usr/sbin/softwareupdate --install-rosetta --agree-to-license\" with administrator privileges")?
            .executeAndReturnError(&error)
        return error == nil && rosettaInstalled
    }

    /// A data folder named by ~/.local/bin/daoc, when it holds an install.
    static func existingInstall() -> URL? {
        let wrapper = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".local/bin/daoc")
        guard let text = try? String(contentsOf: wrapper, encoding: .utf8),
              let path = WrapperFile.dataFolder(fromWrapper: text) else { return nil }
        let folder = URL(fileURLWithPath: path, isDirectory: true)
        let markers = ["server/dist/daoc-server", "dist", ".daoc"]
        return markers.contains { FileManager.default.fileExists(atPath: folder.appendingPathComponent($0).path) } ? folder : nil
    }
}
```

- [ ] **Step 3: `AppModel.swift`**

```swift
import AppKit
import DaocKit
import SwiftUI

struct DownloadState {
    var path: String
    var total: Int64?
    var what: String
    var done: Int64 = 0
}

struct RunState {
    var title: String
    var step = ""
    var download: DownloadState?
}

struct AskRequest: Identifiable {
    let id: Int
    let question: String
    let process: DaocProcess
}

struct SecretRequest: Identifiable {
    let id: Int
    let process: DaocProcess
}

struct Failure: Identifiable {
    let id = UUID()
    let title: String
    let message: String
    let log: URL
}

private struct LatestRelease: Decodable {
    let tagName: String
    let htmlUrl: String
}

/// The app's state, and every daoc command it runs.
@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    enum Mode { case loading, setup, launcher }

    @Published var mode: Mode = .loading
    @Published var status: StatusSnapshot?
    @Published var running: RunState?
    @Published var pendingAsk: AskRequest?
    @Published var pendingSecret: SecretRequest?
    @Published var failure: Failure?
    @Published var realms: [RealmCount] = []
    @Published var population: Bool?
    @Published var notice: String?
    @Published var appUpdate: URL?

    private(set) var paths = AppPaths.current()
    private var current: DaocProcess?
    private var timers: [Timer] = []

    func start() async {
        guard await capture(["--version"]) != nil else {
            failure = Failure(title: "OfflineDAoC is damaged",
                              message: "Its bundled daoc does not run. Download OfflineDAoC again.", log: paths.logs)
            return
        }
        await refreshStatus()
        mode = status.map(SetupPlan.isComplete) == true ? .launcher : .setup
        timers.append(Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { _ in
            Task { @MainActor in
                let model = AppModel.shared
                guard NSApp.windows.contains(where: { $0.isVisible && !$0.isMiniaturized }) else { return }
                await model.refreshStatus()
                await model.refreshBots()
            }
        })
        timers.append(Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
            Task { @MainActor in AppModel.shared.pollDownload() }
        })
        await checkAppRelease()
    }

    func adopt(_ folder: URL) {
        UserDefaults.standard.set(folder.path, forKey: AppPaths.dataHomeKey)
        paths.dataHome = folder
    }

    // MARK: Commands

    /// Runs a daoc command that changes something, shown as the current task.
    /// login answers a `secret` event without asking (Setup's account page).
    @discardableResult
    func run(_ title: String, _ arguments: [String], login: (account: String, password: String)? = nil) async -> Bool {
        guard current == nil else { return false }
        let log = paths.logFile(for: arguments)
        let process = DaocProcess(DaocInvocation(launcher: paths.launcher, dataHome: paths.dataHome,
                                                 arguments: arguments, logFile: log))
        current = process
        running = RunState(title: title)
        defer {
            current = nil
            running = nil
            pendingAsk = nil
            pendingSecret = nil
        }
        do {
            let result = try await process.run { event in
                Task { @MainActor in AppModel.shared.handle(event, from: process, login: login) }
            }
            await refreshStatus()
            if result.status == 0 { return true }
            if result.status != 130 {
                failure = Failure(title: "\(title) did not finish",
                                  message: result.errorMessage ?? Self.tail(of: log), log: log)
            }
        } catch {
            failure = Failure(title: "\(title) could not start", message: "\(error)", log: log)
        }
        return false
    }

    /// Runs a read-only daoc command quietly; its stdout when it succeeds.
    func capture(_ arguments: [String]) async -> Data? {
        let process = DaocProcess(DaocInvocation(launcher: paths.launcher, dataHome: paths.dataHome,
                                                 arguments: arguments, logFile: URL(fileURLWithPath: "/dev/null")))
        guard let result = try? await process.run(onEvent: { _ in }), result.status == 0 else { return nil }
        return result.stdout
    }

    private func handle(_ event: DaocEvent, from process: DaocProcess, login: (account: String, password: String)?) {
        switch event {
        case .step(let message):
            running?.step = message
        case .download(let path, let bytes, let what):
            running?.download = DownloadState(path: path, total: bytes, what: what)
        case .ask(let id, let question, _):
            pendingAsk = AskRequest(id: id, question: question, process: process)
        case .secret(let id, _):
            if let login {
                process.answer(DaocAnswer.secret(id: id, account: login.account, password: login.password))
            } else {
                pendingSecret = SecretRequest(id: id, process: process)
            }
        case .error, .unknown:
            break
        }
    }

    func answer(_ request: AskRequest, _ yes: Bool) {
        request.process.answer(DaocAnswer.ask(id: request.id, answer: yes))
        pendingAsk = nil
    }

    func answer(_ request: SecretRequest, account: String, password: String) {
        request.process.answer(DaocAnswer.secret(id: request.id, account: account, password: password))
        pendingSecret = nil
    }

    func cancel(_ request: SecretRequest) {
        request.process.interrupt()
        pendingSecret = nil
    }

    func stop() { current?.interrupt() }

    func pollDownload() {
        guard let path = running?.download?.path,
              let size = (try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? NSNumber else { return }
        running?.download?.done = size.int64Value
    }

    func refreshStatus() async {
        guard let data = await capture(["status", "--json"]), let snapshot = try? StatusSnapshot.decode(data) else { return }
        status = snapshot
    }

    func refreshBots() async {
        guard status?.server.running == true else {
            realms = []
            population = nil
            return
        }
        if let data = await capture(["admin", "bots", "list", "--json"]),
           let bots = try? JSONDecoder().decode([Bot].self, from: data) {
            realms = BotRoster.counts(bots)
        }
        if let data = await capture(["admin", "population", "--json"]),
           let value = try? JSONDecoder().decode(Population.self, from: data) {
            population = value.enabled
        }
    }

    // MARK: Actions

    func play() async {
        if status?.server.running != true {
            guard await run("Start the server", ["server", "start", "--detach"]) else { return }
        }
        await run("Start the game", ["client", "start"])
    }

    func createAccount(_ account: String, _ password: String) async -> Bool {
        if status?.server.running != true {
            guard await run("Start the server", ["server", "start", "--detach"]) else { return false }
        }
        // A rerun after a failed Keychain save finds the account already made.
        if await capture(["admin", "accounts", "show", account]) == nil {
            guard await run("Create the account", ["admin", "accounts", "create", account, password]) else { return false }
        }
        return await run("Save the account in your Keychain", ["client", "login"], login: (account, password))
    }

    func createBots(_ realm: Realm, level: Int, count: Int) async {
        await run("Create \(count) level \(level) \(realm.rawValue) bots",
                  ["admin", "bots", "create", "--realm", realm.adminName, "--level", "\(level)", "--count", "\(count)"])
        await refreshBots()
    }

    func setPopulation(_ on: Bool) async {
        await run(on ? "Turn the population on" : "Turn the population off", ["admin", "population", on ? "on" : "off"])
        await refreshBots()
    }

    func checkForClientUpdates() async {
        notice = await capture(["client", "update", "--check"]).map { String(decoding: $0, as: UTF8.self) }
            ?? "Could not check for updates (no network?)."
    }

    func openAdminConsole() {
        let file = paths.logs.appendingPathComponent("admin-console.command")
        let script = "#!/bin/sh\nexport DAOC_DATA=\(Self.shellQuote(paths.dataHome.path))\n"
            + "exec \(Self.shellQuote(paths.launcher.path)) server start\n"
        do {
            try FileManager.default.createDirectory(at: paths.logs, withIntermediateDirectories: true)
            try script.write(to: file, atomically: true, encoding: .utf8)
            try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: file.path)
            NSWorkspace.shared.open(file)
        } catch {
            failure = Failure(title: "Could not open the admin console", message: "\(error)", log: file)
        }
    }

    func showLogs() {
        let folder = FileManager.default.fileExists(atPath: paths.serverLogs.path) ? paths.serverLogs : paths.logs
        NSWorkspace.shared.open(folder)
    }

    private func checkAppRelease() async {
        guard let url = URL(string: "https://api.github.com/repos/trozzelle/OfflineDAoC-macOS/releases/latest"),
              let (data, _) = try? await URLSession.shared.data(from: url) else { return }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        guard let release = try? decoder.decode(LatestRelease.self, from: data), let version = status?.version,
              ReleaseCheck.isNewer(tag: release.tagName, than: version) else { return }
        appUpdate = URL(string: release.htmlUrl)
    }

    static func shellQuote(_ s: String) -> String {
        "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    static func tail(of log: URL) -> String {
        let text = (try? String(contentsOf: log, encoding: .utf8)) ?? ""
        return text.split(separator: "\n").suffix(8).joined(separator: "\n")
    }
}
```

- [ ] **Step 4: Views shared by Setup and the launcher**

`RunProgressView.swift`:

```swift
import SwiftUI

struct RunProgressView: View {
    @EnvironmentObject var model: AppModel
    let run: RunState

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(run.title).font(.headline)
            Text(run.step).font(.callout).foregroundStyle(.secondary).lineLimit(2)
            if let download = run.download {
                if let total = download.total, total > 0 {
                    ProgressView(value: Double(min(download.done, total)), total: Double(total)) {
                        Text(download.what)
                    } currentValueLabel: {
                        Text("\(Self.size(download.done)) of \(Self.size(total))")
                    }
                } else {
                    ProgressView { Text(download.what) } currentValueLabel: { Text(Self.size(download.done)) }
                }
                Button("Stop") { model.stop() }
            } else {
                ProgressView().progressViewStyle(.linear)
            }
        }
    }

    static func size(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}

struct CheckRow: View {
    let text: String
    let ok: Bool

    init(_ text: String, ok: Bool) {
        self.text = text
        self.ok = ok
    }

    var body: some View {
        Label(text, systemImage: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
            .foregroundStyle(ok ? Color.green : Color.red)
    }
}
```

`Sheets.swift`:

```swift
import SwiftUI

struct AskSheet: View {
    @EnvironmentObject var model: AppModel
    let request: AskRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(request.question).fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                Button("No") { model.answer(request, false) }.keyboardShortcut(.cancelAction)
                Button("Yes") { model.answer(request, true) }.keyboardShortcut(.defaultAction)
            }
        }
        .padding(24)
        .frame(width: 420)
    }
}

struct SecretSheet: View {
    @EnvironmentObject var model: AppModel
    let request: SecretRequest
    @State private var account = ""
    @State private var password = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Game account").font(.headline)
            TextField("Account name", text: $account)
            SecureField("Password", text: $password)
            HStack {
                Spacer()
                Button("Cancel") { model.cancel(request) }.keyboardShortcut(.cancelAction)
                Button("Save") { model.answer(request, account: account, password: password) }
                    .keyboardShortcut(.defaultAction)
                    .disabled(account.isEmpty || password.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 360)
    }
}
```

`RootView.swift` (Setup and Launcher views come in Tasks 17-18; this task adds them as one-line stubs that Task 17/18 replace — create `SetupView.swift` with `struct SetupView: View { var body: some View { Text("Setup") } }` and `LauncherView.swift` with `struct LauncherView: View { var body: some View { Text("Launcher") } }` so the target compiles):

```swift
import AppKit
import SwiftUI

struct RootView: View {
    @EnvironmentObject var model: AppModel

    var body: some View {
        Group {
            switch model.mode {
            case .loading: ProgressView("Reading your install…")
            case .setup: SetupView()
            case .launcher: LauncherView()
            }
        }
        .frame(minWidth: 680, minHeight: 560)
        .sheet(item: $model.pendingAsk) { AskSheet(request: $0).environmentObject(model) }
        .sheet(item: $model.pendingSecret) { SecretSheet(request: $0).environmentObject(model) }
        .alert(item: $model.failure) { failure in
            Alert(title: Text(failure.title), message: Text(failure.message),
                  primaryButton: .default(Text("Show log")) {
                      NSWorkspace.shared.activateFileViewerSelecting([failure.log])
                  },
                  secondaryButton: .cancel(Text("OK")))
        }
        .alert("Updates", isPresented: Binding(get: { model.notice != nil }, set: { if !$0 { model.notice = nil } })) {
            Button("OK") {}
        } message: {
            Text(model.notice ?? "")
        }
        .task { await model.start() }
    }
}
```

- [ ] **Step 5: Entry point, self-test, quit handling**

`Main.swift`:

```swift
import AppKit
import SwiftUI

@main
enum Main {
    static func main() {
        if CommandLine.arguments.contains("--self-test") {
            exit(SelfTest.run())
        }
        OfflineDAoCApp.main()
    }
}

struct OfflineDAoCApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = AppModel.shared

    var body: some Scene {
        WindowGroup("OfflineDAoC") {
            RootView().environmentObject(model)
        }
        .commands {
            CommandGroup(after: .appSettings) {
                Button("Install daoc Command…") {
                    Task { await AppModel.shared.run("Install the daoc command", ["self-install"]) }
                }
            }
        }
    }
}
```

`SelfTest.swift`:

```swift
import DaocKit
import Foundation

/// `OfflineDAoC --self-test`: the bundled daoc runs under this app's signature
/// (CI runs it after signing): --version, and status --json on an empty data home.
enum SelfTest {
    static func run() -> Int32 {
        let paths = AppPaths.current()
        let data = FileManager.default.temporaryDirectory.appendingPathComponent("offlinedaoc-selftest-\(getpid())")
        defer { try? FileManager.default.removeItem(at: data) }
        for arguments in [["--version"], ["status", "--json"]] {
            let process = Process()
            process.executableURL = paths.launcher
            process.arguments = arguments
            process.environment = ProcessInfo.processInfo.environment.merging(["DAOC_DATA": data.path]) { $1 }
            let output = Pipe()
            process.standardOutput = output
            do {
                try process.run()
            } catch {
                print("self-test: cannot run \(paths.launcher.path): \(error)")
                return 1
            }
            let stdout = output.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let name = "daoc " + arguments.joined(separator: " ")
            guard process.terminationStatus == 0 else {
                print("self-test: \(name) exited \(process.terminationStatus)")
                return 1
            }
            if arguments.first == "status", (try? StatusSnapshot.decode(stdout)) == nil {
                print("self-test: \(name) printed no status")
                return 1
            }
            print("self-test: \(name) ok")
        }
        return 0
    }
}
```

`AppDelegate.swift`:

```swift
import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        let model = AppModel.shared
        if let run = model.running {
            guard run.download != nil else {
                _ = alert("Let it finish", "“\(run.title)” is changing your install. Quit when it is done.", ["OK"])
                return .terminateCancel
            }
            model.stop()  // a download resumes from its finished parts next time
        }
        guard model.status?.server.running == true else { return .terminateNow }
        switch alert("Stop the server?", "The server keeps running after OfflineDAoC quits unless you stop it.",
                     ["Stop the server", "Leave it running", "Cancel"]) {
        case .alertFirstButtonReturn:
            Task { @MainActor in
                _ = await model.capture(["server", "stop"])
                sender.reply(toApplicationShouldTerminate: true)
            }
            return .terminateLater
        case .alertSecondButtonReturn:
            return .terminateNow
        default:
            return .terminateCancel
        }
    }

    private func alert(_ title: String, _ text: String, _ buttons: [String]) -> NSApplication.ModalResponse {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = text
        buttons.forEach { alert.addButton(withTitle: $0) }
        return alert.runModal()
    }
}
```

- [ ] **Step 6: Build**

Run: `swift build --package-path app && swift test --package-path app`
Expected: build succeeds; 12 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add app/Sources/OfflineDAoC
git commit -m "feat(app): app model, sheets, self-test and quit handling"
```

---

### Task 17: Setup wizard

**Files:**
- Replace: `app/Sources/OfflineDAoC/SetupView.swift`

**Interfaces:**
- Consumes: `AppModel` (Task 16), `SetupPlan`, `SetupChoice`, `SystemChecks`, `RunProgressView`, `CheckRow`.

- [ ] **Step 1: Implement**

```swift
import DaocKit
import SwiftUI

struct SetupView: View {
    @EnvironmentObject var model: AppModel
    @State private var page: Page = .check
    @State private var choice = SetupChoice(arm64Wine: !SystemChecks.rosettaInstalled && SystemChecks.macOSMajor >= 27)
    @State private var rosetta = SystemChecks.rosettaInstalled
    @State private var account = ""
    @State private var password = ""
    @State private var installFailed = false

    enum Page { case check, choose, install, account, done }

    private static let baseBytes: Int64 = 8_000_000_000
    private static let newClientBytes: Int64 = 36_000_000_000

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            Text("Offline DAoC Setup").font(.largeTitle.bold())
            switch page {
            case .check: checkPage
            case .choose: choosePage
            case .install: installPage
            case .account: accountPage
            case .done: donePage
            }
            Spacer()
        }
        .padding(32)
    }

    private var rosettaOK: Bool { rosetta || SystemChecks.macOSMajor >= 27 }
    private var existing: URL? {
        SystemChecks.existingInstall().flatMap { $0.standardizedFileURL == model.paths.dataHome.standardizedFileURL ? nil : $0 }
    }

    private var checkPage: some View {
        let free = SystemChecks.freeBytes()
        let ready = SystemChecks.isAppleSilicon && SystemChecks.macOSMajor >= 26 && free >= Self.baseBytes && rosettaOK
        return VStack(alignment: .leading, spacing: 10) {
            CheckRow("A Mac with Apple Silicon", ok: SystemChecks.isAppleSilicon)
            CheckRow("macOS 26 or later", ok: SystemChecks.macOSMajor >= 26)
            CheckRow("8 GB free (\(RunProgressView.size(free)) free)", ok: free >= Self.baseBytes)
            CheckRow(rosetta ? "Rosetta 2"
                     : (SystemChecks.macOSMajor >= 27 ? "No Rosetta: the game will use the arm64 Wine"
                        : "Rosetta 2 is needed"), ok: rosettaOK)
            HStack {
                if !rosettaOK {
                    Button("Install Rosetta") {
                        rosetta = SystemChecks.installRosetta()
                        choice.arm64Wine = !rosetta && SystemChecks.macOSMajor >= 27
                    }
                }
                if let existing {
                    Button("Use my existing install") {
                        model.adopt(existing)
                        Task {
                            await model.refreshStatus()
                            if let status = model.status, SetupPlan.isComplete(status) { model.mode = .launcher }
                        }
                    }
                }
                Spacer()
                Button("Continue") { page = .choose }
                    .keyboardShortcut(.defaultAction)
                    .disabled(!ready)
            }
        }
    }

    private var choosePage: some View {
        let need = Self.baseBytes + (choice.newClient ? Self.newClientBytes : 0)
        return VStack(alignment: .leading, spacing: 12) {
            Picker("Game", selection: $choice.game) {
                Text("0.37b, with the Sluaghbinder").tag("0.37b")
                Text("0.37, classic classes only").tag("0.37")
            }
            .pickerStyle(.radioGroup)
            Toggle("Also install the new client (about 34 GB more)", isOn: $choice.newClient)
            if choice.arm64Wine {
                Text("The game runs on the arm64 Wine (no Rosetta).").foregroundStyle(.secondary)
            }
            HStack {
                Button("Back") { page = .check }
                Spacer()
                if SystemChecks.freeBytes() < need {
                    Text("Needs \(RunProgressView.size(need)) free").foregroundStyle(.red)
                }
                Button("Install") { page = .install }
                    .keyboardShortcut(.defaultAction)
                    .disabled(SystemChecks.freeBytes() < need)
            }
        }
    }

    private var installPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            if let run = model.running { RunProgressView(run: run) }
            if installFailed {
                HStack {
                    Text("Setup stopped. It continues where it stopped.").foregroundStyle(.secondary)
                    Spacer()
                    Button("Try again") {
                        installFailed = false
                        Task { await install() }
                    }
                }
            }
        }
        .task { await install() }
    }

    private func install() async {
        for command in SetupPlan.commands(for: choice, status: model.status) {
            guard await model.run(Self.title(command), command) else {
                installFailed = true
                return
            }
        }
        page = model.status?.accountSaved == true ? .done : .account
    }

    static func title(_ command: [String]) -> String {
        if command.first == "game" { return "Install the server for \(command[2])" }
        if command.contains("new") { return "Install the new client" }
        return "Install the game client and Wine"
    }

    private var accountPage: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Your game account lives on your own server. Pick any name and password.")
            TextField("Account name", text: $account).frame(maxWidth: 320)
            SecureField("Password", text: $password).frame(maxWidth: 320)
            HStack {
                Spacer()
                Button("Create account") {
                    Task { if await model.createAccount(account, password) { page = .done } }
                }
                .keyboardShortcut(.defaultAction)
                .disabled(account.isEmpty || password.isEmpty || model.running != nil)
            }
            if let run = model.running { RunProgressView(run: run) }
        }
    }

    private var donePage: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("The realm awaits.").font(.title2)
            Text("Make some bots in the Bots panel, then press Play.")
            Button("Open the launcher") { model.mode = .launcher }.keyboardShortcut(.defaultAction)
        }
    }
}
```

- [ ] **Step 2: Build**

Run: `swift build --package-path app`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add app/Sources/OfflineDAoC/SetupView.swift
git commit -m "feat(app): Setup wizard"
```

---

### Task 18: Launcher and Bots panel

**Files:**
- Replace: `app/Sources/OfflineDAoC/LauncherView.swift`
- Create: `app/Sources/OfflineDAoC/BotsPanel.swift`

**Interfaces:**
- Consumes: `AppModel` actions (Task 16), `Realm`, `RealmCount`, `SystemChecks.macOSMajor`.

- [ ] **Step 1: `BotsPanel.swift`**

```swift
import DaocKit
import SwiftUI

struct BotsPanel: View {
    @EnvironmentObject var model: AppModel
    @State private var count = 10

    private var rows: [RealmCount] {
        model.realms.isEmpty ? Realm.allCases.map { RealmCount(realm: $0, roster: 0, online: 0) } : model.realms
    }

    var body: some View {
        GroupBox("Bots") {
            VStack(alignment: .leading, spacing: 8) {
                Grid(alignment: .leading, horizontalSpacing: 16, verticalSpacing: 6) {
                    GridRow {
                        Text("Realm").bold()
                        Text("Roster").bold()
                        Text("In the world").bold()
                        Text("")
                        Text("")
                    }
                    ForEach(rows, id: \.realm) { row in
                        GridRow {
                            Text(row.realm.rawValue)
                            Text("\(row.roster)")
                            Text("\(row.online)")
                            Button("+ Lv.1") { Task { await model.createBots(row.realm, level: 1, count: count) } }
                            Button("+ Lv.50") { Task { await model.createBots(row.realm, level: 50, count: count) } }
                        }
                    }
                }
                HStack {
                    Stepper("Bots per click: \(count)", value: $count, in: 1...100)
                    Spacer()
                    Toggle("Population", isOn: Binding(get: { model.population ?? false },
                                                       set: { on in Task { await model.setPopulation(on) } }))
                        .disabled(model.population == nil)
                }
            }
        }
    }
}
```

- [ ] **Step 2: `LauncherView.swift`**

```swift
import DaocKit
import SwiftUI

struct LauncherView: View {
    @EnvironmentObject var model: AppModel
    @State private var game = "0.37b"

    private var busy: Bool { model.running != nil }
    private var serverRunning: Bool { model.status?.server.running == true }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                header
                HStack(spacing: 12) {
                    Button { Task { await model.play() } } label: {
                        Label("Play", systemImage: "play.fill").frame(minWidth: 120)
                    }
                    .controlSize(.large)
                    .keyboardShortcut(.defaultAction)
                    .disabled(busy)
                    Button("Stop the game") { Task { await model.run("Stop the game", ["client", "stop"]) } }
                        .disabled(busy || model.status?.clientRunning == nil)
                }
                if let run = model.running { RunProgressView(run: run) }
                GroupBox("Server") {
                    HStack {
                        Button("Start") { Task { await model.run("Start the server", ["server", "start", "--detach"]) } }
                            .disabled(busy || serverRunning)
                        Button("Stop") { Task { await model.run("Stop the server", ["server", "stop"]) } }
                            .disabled(busy || !serverRunning)
                        Button("Open admin console") { model.openAdminConsole() }
                        Button("Show logs") { model.showLogs() }
                        Spacer()
                    }
                }
                BotsPanel().disabled(busy || !serverRunning)
                settings
                updates
            }
            .padding(24)
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Offline DAoC").font(.largeTitle.bold())
            if let s = model.status {
                Text("Game \(s.game.name) · \(s.client) client · Wine: \(s.wine ?? "not installed")")
                    .foregroundStyle(.secondary)
                Label(s.server.running == true ? "Server running"
                      : (s.server.running == false ? "Server stopped" : "Server state unknown: \(s.server.detail)"),
                      systemImage: "circle.fill")
                    .foregroundStyle(s.server.running == true ? Color.green : Color.secondary)
            }
        }
    }

    private var settings: some View {
        GroupBox("Settings") {
            VStack(alignment: .leading) {
                HStack {
                    Picker("Game", selection: $game) {
                        Text("0.37b").tag("0.37b")
                        Text("0.37").tag("0.37")
                    }
                    .frame(width: 200)
                    Button("Switch") { Task { await model.run("Switch to \(game)", ["game", "switch", game]) } }
                        .disabled(busy || game == model.status?.game.name)
                }
                HStack {
                    Button("Add the new client (34 GB)") {
                        Task { await model.run("Install the new client", ["client", "install", "--client", "new"]) }
                    }
                    .disabled(busy || model.status?.installed.newClient == true)
                    let wine = model.status?.wine == "arm64" ? "rosetta" : "arm64"
                    Button(wine == "arm64" ? "Use the arm64 Wine" : "Use the Rosetta Wine") {
                        Task { await model.run("Switch to the \(wine) Wine", ["client", "install", "--wine", wine]) }
                    }
                    .disabled(busy || (wine == "arm64" && SystemChecks.macOSMajor < 27))
                    Button("Change account…") { Task { await model.run("Change the game account", ["client", "login"]) } }
                        .disabled(busy)
                }
            }
        }
        .onAppear { game = model.status?.game.name ?? "0.37b" }
    }

    private var updates: some View {
        GroupBox("Updates") {
            HStack {
                Button("Check for updates") { Task { await model.checkForClientUpdates() } }
                Button("Update the client") { Task { await model.run("Update the client", ["client", "update"]) } }
                    .disabled(busy)
                if let url = model.appUpdate { Link("A new OfflineDAoC is out", destination: url) }
                Spacer()
            }
        }
    }
}
```

- [ ] **Step 2b: Build**

Run: `swift build --package-path app && swift test --package-path app`
Expected: build succeeds; tests PASS.

- [ ] **Step 3: Commit**

```bash
git add app/Sources/OfflineDAoC/LauncherView.swift app/Sources/OfflineDAoC/BotsPanel.swift
git commit -m "feat(app): launcher with Play, server, bots, settings and updates"
```

---

### Task 19: Bundle, sign, notarize (`build-app.sh`, `sign-app.sh`, `app.yml`)

**Files:**
- Create: `app/Info.plist`, `app/build-app.sh`, `app/sign-app.sh`, `.github/workflows/app.yml`

**Interfaces:**
- Consumes: `app/python.lock`, the repo's code root files, `OfflineDAoC --self-test`.
- Produces: `app/build-app.sh [OUT_DIR]` → `<OUT_DIR>/OfflineDAoC.app` (default `app/dist`); `app/sign-app.sh APP IDENTITY [ENTITLEMENTS]`.

- [ ] **Step 1: `app/Info.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>OfflineDAoC</string>
  <key>CFBundleIdentifier</key><string>io.github.trozzelle.OfflineDAoC</string>
  <key>CFBundleName</key><string>OfflineDAoC</string>
  <key>CFBundleDisplayName</key><string>Offline DAoC</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>@VERSION@</string>
  <key>CFBundleVersion</key><string>@VERSION@</string>
  <key>LSMinimumSystemVersion</key><string>26.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.role-playing-games</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
```

- [ ] **Step 2: `app/build-app.sh`**

```bash
#!/bin/bash
# build-app.sh [OUT_DIR] - assemble OfflineDAoC.app (unsigned) in OUT_DIR (default app/dist).
#
# Contents/MacOS/OfflineDAoC     the SwiftUI shell (swift build -c release)
# Contents/Resources/python/     python-build-standalone (app/python.lock), trimmed
# Contents/Resources/daoc/       the code root: daoc, daoc_cli/, manifest.json, version.txt,
#                                client/DAoCLauncher.app, server/tools/setup-dotnet.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repo="$(cd "$here/.." && pwd -P)"
out="${1:-$here/dist}"
version="$(cat "$repo/version.txt")"
# shellcheck source=python.lock
. "$here/python.lock"

swift build -c release --arch arm64 --package-path "$here"
bin="$(swift build -c release --arch arm64 --package-path "$here" --show-bin-path)"

app="$out/OfflineDAoC.app"
rm -rf "$app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
cp "$bin/OfflineDAoC" "$app/Contents/MacOS/OfflineDAoC"
sed "s/@VERSION@/$version/g" "$here/Info.plist" > "$app/Contents/Info.plist"

code="$app/Contents/Resources/daoc"
mkdir -p "$code/client" "$code/server/tools"
cp "$repo/daoc" "$repo/manifest.json" "$repo/version.txt" "$code/"
rsync -a --exclude __pycache__ "$repo/daoc_cli" "$code/"
cp -R "$repo/client/DAoCLauncher.app" "$code/client/"
cp "$repo/server/tools/setup-dotnet.sh" "$code/server/tools/"

cache="$here/.cache"
mkdir -p "$cache"
tarball="$cache/$(basename "${PYTHON_URL//%2B/+}")"
[[ -f $tarball ]] || curl -fsSL "$PYTHON_URL" -o "$tarball"
echo "$PYTHON_SHA256  $tarball" | shasum -a 256 -c - >/dev/null
python="$app/Contents/Resources/python"
mkdir -p "$python"
tar -xzf "$tarball" -C "$python" --strip-components 1
# Nothing daoc_cli imports: tests, IDLE, Tk, pip.
rm -rf "$python"/lib/python3.*/test "$python"/lib/python3.*/idlelib "$python"/lib/python3.*/tkinter \
  "$python"/lib/python3.*/ensurepip "$python"/lib/python3.*/lib-dynload/_tkinter* \
  "$python"/lib/libtcl* "$python"/lib/libtk* "$python"/lib/tcl* "$python"/lib/tk* \
  "$python"/bin/idle3* "$python"/bin/pip*

# Smoke: the bundled launcher runs on the bundled Python.
DAOC_DATA="$(mktemp -d)" "$code/daoc" --version
echo "$app"
```

Run: `chmod +x app/build-app.sh`

- [ ] **Step 3: `app/sign-app.sh`**

```bash
#!/bin/bash
# sign-app.sh APP IDENTITY [ENTITLEMENTS] - Developer ID signature, hardened runtime,
# inside out: every Mach-O under Resources, the nested launcher bundle, then the app.
set -euo pipefail

app=$1
identity=$2
entitlements=${3:-}

sign() { codesign --force --options runtime --timestamp --sign "$identity" "$@"; }

find "$app/Contents/Resources" -type f -print0 | while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q 'Mach-O'; then sign "$f"; fi
done
sign "$app/Contents/Resources/daoc/client/DAoCLauncher.app"
if [[ -n $entitlements ]]; then
  sign --entitlements "$entitlements" "$app"
else
  sign "$app"
fi
codesign --verify --deep --strict "$app"
```

Run: `chmod +x app/sign-app.sh`

- [ ] **Step 4: Build and smoke locally (ad-hoc signature)**

```bash
app/build-app.sh /tmp/odaoc && app/sign-app.sh /tmp/odaoc/OfflineDAoC.app - \
  && /tmp/odaoc/OfflineDAoC.app/Contents/MacOS/OfflineDAoC --self-test
```

Expected: `daoc 0.4.0` from the build smoke, then `self-test: daoc --version ok` and `self-test: daoc status --json ok`. If the self-test fails with a code-signing or memory-protection error from Python, create `app/entitlements.plist` containing only `com.apple.security.cs.allow-unsigned-executable-memory` = true, rerun with it as the third argument, and pass it in `app.yml` Step 5 (this resolves the spec's open premise).

- [ ] **Step 5: `.github/workflows/app.yml`**

```yaml
name: app

# OfflineDAoC.app for each daoc release: build, Developer ID signature, notarization,
# Gatekeeper check, DMG on the release. release-please publishes releases with the
# release App's token (not GITHUB_TOKEN), so publishing starts this workflow; the
# server-<version>-<ref12> prereleases are skipped by the job's `if`.
on:
  release:
    types: [published]
  workflow_dispatch:

permissions:
  contents: write

jobs:
  app:
    if: github.event_name == 'workflow_dispatch' || startsWith(github.event.release.tag_name, 'v')
    runs-on: macos-latest
    environment: main
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262  # v4.4.0
      - name: Swift tests
        run: swift test --package-path app
      - name: Build
        run: app/build-app.sh "$RUNNER_TEMP/out"
      - name: Import the Developer ID certificate
        env:
          DEVELOPER_ID_P12: ${{ secrets.DEVELOPER_ID_P12 }}
          P12_PASSWORD: ${{ secrets.P12_PASSWORD }}
        run: |
          kc="$RUNNER_TEMP/build.keychain-db"
          security create-keychain -p "" "$kc"
          security set-keychain-settings -lut 21600 "$kc"
          security unlock-keychain -p "" "$kc"
          echo "$DEVELOPER_ID_P12" | base64 --decode > "$RUNNER_TEMP/cert.p12"
          security import "$RUNNER_TEMP/cert.p12" -k "$kc" -P "$P12_PASSWORD" -T /usr/bin/codesign
          security set-key-partition-list -S apple-tool:,apple: -s -k "" "$kc"
          security list-keychains -d user -s "$kc" $(security list-keychains -d user | tr -d '"')
          identity=$(security find-identity -v -p codesigning "$kc" | awk -F'"' '/Developer ID Application/ {print $2; exit}')
          echo "IDENTITY=$identity" >> "$GITHUB_ENV"
      - name: Sign
        run: app/sign-app.sh "$RUNNER_TEMP/out/OfflineDAoC.app" "$IDENTITY"
      - name: Self-test under the hardened runtime
        run: '"$RUNNER_TEMP/out/OfflineDAoC.app/Contents/MacOS/OfflineDAoC" --self-test'
      - name: DMG
        run: |
          version=$(cat version.txt)
          stage="$RUNNER_TEMP/dmg"
          mkdir "$stage"
          ditto "$RUNNER_TEMP/out/OfflineDAoC.app" "$stage/OfflineDAoC.app"
          ln -s /Applications "$stage/Applications"
          dmg="$RUNNER_TEMP/OfflineDAoC-$version.dmg"
          hdiutil create -volname "OfflineDAoC $version" -srcfolder "$stage" -ov -format UDZO "$dmg"
          codesign --sign "$IDENTITY" --timestamp "$dmg"
          echo "DMG=$dmg" >> "$GITHUB_ENV"
      - name: Notarize
        env:
          NOTARY_KEY_ID: ${{ secrets.NOTARY_KEY_ID }}
          NOTARY_ISSUER: ${{ secrets.NOTARY_ISSUER }}
          NOTARY_KEY_P8: ${{ secrets.NOTARY_KEY_P8 }}
        run: |
          echo "$NOTARY_KEY_P8" > "$RUNNER_TEMP/notary.p8"
          xcrun notarytool submit "$DMG" --key "$RUNNER_TEMP/notary.p8" --key-id "$NOTARY_KEY_ID" \
            --issuer "$NOTARY_ISSUER" --wait
          xcrun stapler staple "$DMG"
      - name: Gatekeeper check
        run: |
          mnt=$(mktemp -d)
          hdiutil attach -nobrowse -readonly -mountpoint "$mnt" "$DMG"
          spctl --assess --type execute -v "$mnt/OfflineDAoC.app"
          codesign --verify --deep --strict "$mnt/OfflineDAoC.app"
          hdiutil detach "$mnt"
      - name: Upload to the release
        if: github.event_name == 'release'
        env:
          GH_TOKEN: ${{ github.token }}
          TAG: ${{ github.event.release.tag_name }}
        run: gh release upload "$TAG" "$DMG" --clobber
```

- [ ] **Step 6: Commit**

```bash
git add app/Info.plist app/build-app.sh app/sign-app.sh .github/workflows/app.yml
git commit -m "ci(app): build, sign, notarize and publish OfflineDAoC.app"
```

---

## Phase 4: Docs and the end-to-end smoke

### Task 20: Documentation

**Files:**
- Modify: `README.md`, `docs/DESIGN.md`, `docs/DEVELOPMENT.md`, `docs/QUICK-COMMANDS.md`, `docs/PLAY.md`

- [ ] **Step 1: README**

Insert before `## Quick start`:

```markdown
## The app

Download `OfflineDAoC-<version>.dmg` from the
[latest release](https://github.com/trozzelle/OfflineDAoC-macOS/releases/latest), drag
OfflineDAoC into Applications and open it. Setup installs the server, the client and Wine
for 0.37b or 0.37 (the new client optional), creates your account, and then the window is
your launcher: Play, the server, bots per realm, and updates. Nothing to compile; no
Terminal, Command Line Tools or Homebrew. Installs live in
`~/Library/Application Support/OfflineDAoC`. "Install daoc Command…" in the app menu puts
the `daoc` command below on your PATH for the same install.

The rest of this page is the command-line way, from a git checkout.
```

Replace the first bullet of `## Requirements` with:

```markdown
- A Mac with Apple Silicon running macOS 26 or later, and Rosetta 2 (or, for
  `--wine arm64`, macOS 27 or later and no Rosetta). That is all the app needs; the
  command line from a git checkout also needs:
```

and indent nothing else: the Command Line Tools, cmake and internet-connection bullets stay as they are.

- [ ] **Step 2: DESIGN.md**

- Layout: add `├── app/                     # OfflineDAoC.app: SwiftPM package (DaocKit + SwiftUI), build/sign scripts, python.lock` and note `.github/workflows/{server-prebuilt,app}.yml`.
- Replace the "**The Checkout is the home.**" bullet with:

```markdown
- **Code root and data home.** The code root holds daoc itself (`daoc_cli/`, the manifest,
  `client/DAoCLauncher.app`, `server/tools/`); the data home holds the installs, clones,
  download caches and `.daoc/`. In a git Checkout both are the Checkout. OfflineDAoC.app
  keeps the code root read-only in its bundle and sets `DAOC_DATA` to
  `~/Library/Application Support/OfflineDAoC`. Not `DAOC_HOME`: `daoc-server.sh` and
  `build-release.sh` read that as the server folder, and children inherit daoc's environment.
```

- Add a section `## The OfflineDAoC app` after "### Conventions":

```markdown
## The OfflineDAoC app

`app/` is a SwiftUI shell over this CLI; it reimplements nothing. Each action spawns
`Contents/Resources/daoc/daoc …` (this repo's `./daoc`, which runs the bundled
python-build-standalone beside it) with `DAOC_DATA` and `DAOC_EVENTS=3`:

- **Events** (`daoc_cli/events.py`): JSON lines on fd 3 — `step` (every `say`), `download`
  (the file growing on disk, and its size when known), `ask` and `secret` (answered as JSON
  lines on stdin), `error`. The exit status is the result. `errors.interactive()` (a tty, or
  the app) decides between asking and refusing, so both modes share one logic. In event
  mode children get `/dev/null` as stdin, and `execv` closes the channel first.
- **State**: `daoc status --json` (hidden), offline and without git or secrets.
- **Server**: `daoc server start --detach` returns once the server is ready.
- **Secrets**: the password goes to `security add-generic-password -w` on stdin, in a new
  session (no controlling terminal), never on argv.
- **Prebuilt server**: `server-prebuilt.yml` runs `daoc dev pack-server <version>` and
  publishes `daoc-server-<version>-<ref12>-osx-arm64.tar.xz` on the release
  `server-<version>-<ref12>`; `daoc dev ship-prebuilt` pins its url, size and SHA-256 as
  `versions.<v>.server.prebuilt` in a PR. `daoc server install` uses it when the effective
  pin has one (a Local pin never does) and replaces only the top-level entries the tarball
  holds, after checking its `.daoc-pin.json` commit; `--from-source` builds instead.
- **Release**: `app.yml`, when a `v*` release is published, builds, signs (Developer ID,
  hardened runtime), self-tests, notarizes and staples the DMG and uploads it to the release.
```

- In "## Server install", add a line: "With a `prebuilt` pin, steps 1–3 are replaced by the tarball download described in [The OfflineDAoC app](#the-offlinedaoc-app)."

- [ ] **Step 3: DEVELOPMENT.md**

Append to `## Tests`:

```markdown
CI also runs the suite on the app's bundled Python (`app/python.lock`) and the app's Swift
tests: `swift test --package-path app`.
```

Add before `## Design and notes`:

```markdown
## The app

- Build and smoke: `app/build-app.sh /tmp/odaoc && app/sign-app.sh /tmp/odaoc/OfflineDAoC.app - && /tmp/odaoc/OfflineDAoC.app/Contents/MacOS/OfflineDAoC --self-test`.
- Releases: `app.yml` publishes the DMG on each release tag. Secrets in the `main`
  environment: `DEVELOPER_ID_P12` (base64), `P12_PASSWORD`, `NOTARY_KEY_ID`,
  `NOTARY_ISSUER`, `NOTARY_KEY_P8`.
- Prebuilt server: after a server pin moves, run
  `gh workflow run server-prebuilt.yml -f version=<version>` and merge its PR before the
  release, or the app falls back to a source build it cannot do.
- Manual pre-release check, on a clean macOS user account: download the DMG in Safari, open
  it through Gatekeeper, run Setup with the original client, Play into the world, create bots,
  quit with the server running.
```

- [ ] **Step 4: QUICK-COMMANDS.md**

Replace the `server install` and `server start` rows and add:

```markdown
| `daoc server install [--from-source] [--verbose]` | Install the server for the selected game version: the pinned prebuilt server, or a build from source |
| `daoc server start [--console \| --detach]` | Start the server (holds the terminal with the admin screen; `--detach` returns once it is ready) |
```

and under the maintainer section (or the table's end):

```markdown
| `daoc dev pack-server VERSION [--out DIR]` | Build the version's Shipped server pin and pack the prebuilt tarball |
| `daoc dev ship-prebuilt VERSION TARBALL URL` | Pin a prebuilt tarball's url, size and hash in manifest.json |
```

- [ ] **Step 5: PLAY.md**

At the top of the walkthrough, add: "Using the app? Setup and the launcher do everything below; this page is the command-line way."

- [ ] **Step 6: Commit**

```bash
git add README.md docs/DESIGN.md docs/DEVELOPMENT.md docs/QUICK-COMMANDS.md docs/PLAY.md
git commit -m "docs: the OfflineDAoC app, the data home and the prebuilt server"
```

### Task 21: End-to-end smoke of the real app

**Files:** none (verification only).

- [ ] **Step 1: Prerequisite** — Task 12 Step 4 merged (0.37 has a `prebuilt` pin), or use the throwaway pin from Task 10 Step 6 in a scratch copy of the repo for this run.

- [ ] **Step 2: Build and open with a scratch data home**

```bash
app/build-app.sh /tmp/odaoc && app/sign-app.sh /tmp/odaoc/OfflineDAoC.app -
defaults write io.github.trozzelle.OfflineDAoC dataHome "$(mktemp -d)/OfflineDAoC"
open /tmp/odaoc/OfflineDAoC.app
```

- [ ] **Step 3: Walk Setup** — Check page all green; choose 0.37b, new client off; Install shows "Install the server for 0.37b" with a download bar for the server tarball (no clone/build step), then the client and Wine downloads with progress; Account page creates an account; Done opens the launcher.

- [ ] **Step 4: Walk the launcher** — header shows `Game 0.37b · original client` and "Server running"; Bots: `+ Lv.1` on Albion with 10 → Albion roster becomes 10 and Population turns on; Play reaches the world; quit → "Stop the server?" → Stop → `daoc server status` with that `DAOC_DATA` prints `stopped`.

- [ ] **Step 5: Reset** — `defaults delete io.github.trozzelle.OfflineDAoC dataHome` and remove the scratch folder.
```
