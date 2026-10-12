"""`daoc dev e2e [account] [password]`: scripted end-to-end acceptance.

Flow: install server → boot on alternate ports → create an account →
install client → launch the client → verify the server log shows the login
reaching character select and the client process is still alive ≥120 s later.

Exits 0 only when every step passes. The server and client installs run
in-process when their outputs are missing (they are idempotent).

NOTE on ports: the user's own server may be running on 10300/10400; this test
moves its server instance to 20300/20400 and the client launch passes the
port explicitly.

CAUTION: never delete run/admin.sock or run/server.pid while a CoreServer from
this install is alive — shutdown needs the socket to wake a pending accept
(patch 010). Check lsof before touching run/. Nothing here removes run/.
"""
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional

from daoc_cli import client, client_runtime, proc, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError

DEFAULT_PASSWORD = "e2epass1"
GAME_PORT = 20300
REGION_PORT = 20400
ATTEMPTS = 10
ATTEMPT_WINDOW = 180  # seconds per launch attempt
BOOT_WAIT = 120  # seconds for the server to reach 'listening'
ALIVE_HOLD = 120  # seconds the client must outlive the login
LISTENING = "Server is now listening"
WINE_LOG = client_runtime.WINE_LOG
LS = "/bin/ls"


class _Failed(Exception):
    """A step failed and the run stops here (cleanup still runs)."""


class _Run:
    def __init__(self, checkout: Checkout, account: str, password: str) -> None:
        self.co = checkout
        self.account = account
        self.password = password
        self.server_dir = checkout.server_dir
        self.evidence = checkout.root / "evidence"
        self.config = self.server_dir / "config" / "serverconfig.xml"
        self.failed = False
        self.step_name = ""

    def step(self, name: str) -> None:
        self.step_name = name
        print(f"\n=== {name} ===", flush=True)

    def fail(self, msg: str) -> None:
        print(f"E2E FAILED at: {self.step_name} — {msg}", file=sys.stderr, flush=True)
        self.failed = True

    def abort(self, msg: str) -> None:
        self.fail(msg)
        raise _Failed

    def say(self, msg: str) -> None:
        print(msg, flush=True)

    # --- server helpers -----------------------------------------------------
    def server_script(self, action: str, quiet: bool) -> int:
        """daoc-server.sh <action> in the install; its exit code (127: cannot run)."""
        try:
            return proc.run([self.server_dir / "daoc-server.sh", action], cwd=self.server_dir,
                            verbose=not quiet, check=False).returncode
        except DaocError:
            return 127

    def admin(self, *args: str) -> str:
        """daoc-admin's stdout and stderr together, as the script's `2>&1` captured it."""
        try:
            result = proc.run([self.server_dir / "daoc-admin", *args], cwd=self.server_dir,
                              check=False)
        except DaocError as e:
            return e.msg
        return ((result.stdout or "") + (result.stderr or "")).rstrip("\n")

    # --- 1. Server installed? -----------------------------------------------
    def server_install(self) -> None:
        self.step("server install")
        if not os.access(self.server_dir / "bin" / "CoreServer", os.X_OK):
            try:
                server.install(self.co)
            except DaocError as e:
                self.abort(f"server install failed: {e.msg}")
        else:
            self.say("server already installed")

    # --- 2. Boot on alternate ports -----------------------------------------
    def server_boot(self) -> None:
        self.step(f"server boot (alternate ports {GAME_PORT}/{REGION_PORT})")
        self.server_script("stop", quiet=True)
        # A fresh install has no config/ until first start; seed it from defaults/ so
        # the port move below edits the file the server will actually read. The data/
        # world DB is likewise created here so the boot log is clean.
        for sub in ("config", "data"):
            (self.server_dir / sub).mkdir(parents=True, exist_ok=True)
        if not self.config.is_file():
            _copy(self.server_dir / "defaults" / "serverconfig.xml", self.config)
        world = self.server_dir / "data" / "opendaoc.sqlite3.db"
        if not world.is_file():
            _copy(self.server_dir / "defaults" / "world.sqlite", world)
        text = _read(self.config)
        if "<Port>10300</Port>" in text:
            # The original is kept as serverconfig.xml.bak; cleanup puts it back.
            try:
                shutil.copy2(self.config, self.config.with_name("serverconfig.xml.bak"))
                self.config.write_text(move_ports(text))
            except OSError as e:
                self.abort(f"port move failed: {e}")
            self.say(f"ports moved to {GAME_PORT}/{REGION_PORT}")
            if f"<Port>{GAME_PORT}</Port>" not in self.config.read_text(errors="replace"):
                self.abort("port move failed")
        # Boot detached: without a TTY the launcher script execs the console in the
        # foreground, so a child tied to this process dies with it. A new session
        # with output into logs/console.out (nohup semantics) keeps it independent.
        for sub in ("logs", "run"):
            (self.server_dir / sub).mkdir(parents=True, exist_ok=True)
        console = self.server_dir / "logs" / "console.out"
        try:
            _start_detached([self.server_dir / "daoc-server.sh", "start", "--console"],
                            self.server_dir, console)
        except OSError as e:
            self.abort(f"cannot start daoc-server.sh: {e.strerror or e}")
        for _ in range(BOOT_WAIT):
            if LISTENING in _read(console) and _port_open(GAME_PORT):
                self.say(f"server is listening (console.out + port {GAME_PORT} OK)")
                break
            time.sleep(1)
        if LISTENING not in _read(console):
            self.abort(f"server never reached 'listening' within {BOOT_WAIT} s")
        _copy(console, self.evidence / "server-boot.log")

    # --- 3. Account -----------------------------------------------------------
    def account_create(self) -> None:
        self.step("account creation")
        out = self.admin("accounts", "create", self.account, self.password)
        (self.evidence / "account.txt").write_text(out + "\n")
        if "player," in out:
            self.say(f"account '{self.account}' created")
        elif "already exists" in out:
            self.say(f"account '{self.account}' already exists — reusing it")
        else:
            self.abort(f"account creation failed: {out}")

    # --- 4. Client installed? -------------------------------------------------
    def client_install(self) -> None:
        self.step("client install")
        if not self.co.client_root.is_dir():
            try:
                client.install(self.co)
            except DaocError as e:
                self.fail(f"client install failed: {e.msg}")
        else:
            self.say("client already installed")
        if not (self.co.app_dir / "game.dll").is_file():
            self.abort("game.dll missing after client install")

    # --- 5. Launch the client (up to 10 attempts) -----------------------------
    def snapshot(self) -> str:
        """Process snapshot for the evidence bundle: pid + executable only (the
        command line carries the account password)."""
        lines = [time.strftime("%H:%M:%S")]
        for pid in client_runtime.game_pids(self.co):
            result = proc.run([client_runtime.PS, "-o", "pid=,comm=", "-p", str(pid)], check=False)
            lines += (result.stdout or "").splitlines()
        return "\n".join(lines) + "\n"

    def keep_attempt(self, attempt: int) -> None:
        _copy(WINE_LOG, self.evidence / f"wine-attempt-{attempt}.log")
        (self.evidence / f"pgrep-at-attempt-{attempt}.txt").write_text(self.snapshot())

    def client_launch(self) -> None:
        self.step("client launch")
        server_log = self.server_dir / "logs" / "server.log"
        logging_on = re.compile(r"LoginRequestHandler.*User " + re.escape(self.account)
                                + r" logging on!")
        offset = _size(server_log)
        # Observed: every "died" attempt crashed at the same GL-init point
        # (wined3d select_card_handler → err:seh:NtRaiseException, verified via the
        # per-attempt wine logs in evidence/). The crash is probabilistic at that
        # point — earlier runs succeeded on attempts 1, 2, 4 and 5 of 5; runs 9-10
        # burned 10 consecutive crashes before a success. A failed attempt never
        # opens a network connection (no "Incoming connection" for any "died"),
        # so relaunching is the only remedy; 10 attempts bounds the worst case.
        attempt = 0
        login_ok = False
        rejected = False
        while attempt < ATTEMPTS and not (login_ok or rejected):
            attempt += 1
            seen = False
            self.say(f"--- launch attempt {attempt}/{ATTEMPTS}")
            # Kill any orphaned wine client from a previous attempt, then wait for the
            # wineserver to actually exit (a fixed sleep can't tell a slow Rosetta
            # teardown from a fast one). Scoped to this Checkout's wine.
            client_runtime.kill(self.co)
            _truncate(WINE_LOG)
            _launch(self.co, self.account, self.password)
            deadline = time.monotonic() + ATTEMPT_WINDOW
            while time.monotonic() < deadline:
                # Strict, offset-windowed check on new bytes only:
                #  - pass = the server accepted the login for THIS account ("logging on!")
                #    and no rejection followed in the same window — the bare "logging on!"
                #    line is also written right before a "Wrong password!" rejection, so it
                #    alone is not proof;
                #  - fail = any "Wrong password" in the window.
                # World entry ("WorldInitRequestHandler … entering Region") can't be the
                # gate: a brand-new account has no character, and the automated launch
                # stops at character select.
                new = _tail(server_log, offset)
                if "Wrong password" in new:
                    self.fail("server rejected the login (Wrong password) — account/password mismatch")
                    rejected = True
                    break
                if logging_on.search(new):
                    # Authentication succeeded; confirm via the account record.
                    show = self.admin("accounts", "show", self.account)
                    (self.evidence / "account-show.txt").write_text(show + "\n")
                    if re.search(r"last login [0-9]", show):
                        login_ok = True
                        break
                # Crash detection: retry only after the client was actually seen running.
                # Wait for it to appear first: 'open' returns before wine starts, so an
                # immediate check would read "not running" during the spawn window. The
                # seen-flag makes "died" reproducible: only a client that was observed
                # running and then vanished counts as a crash.
                if client_runtime.game_pids(self.co):
                    seen = True
                elif seen:
                    self.say("client process died before login — relaunching")
                    # Keep this attempt's output: the truncation at the next attempt would
                    # otherwise destroy the only crash signature. A timestamped snapshot of
                    # what matched right before the death disambiguates a real client
                    # crash from a short-lived process matching the pattern.
                    self.keep_attempt(attempt)
                    seen = False
                    break
                time.sleep(2)
            if rejected:
                break
            # Deadline expiry without a "died": the client may have hung (no signature,
            # no login). Preserve this attempt's log and a process snapshot — the
            # truncation at the next attempt would otherwise destroy the hang's only record.
            if not login_ok and seen:
                self.keep_attempt(attempt)
                self.say(f"attempt {attempt}: {ATTEMPT_WINDOW} s window expired with the "
                         "client alive but no login — hang")
        _copy(server_log, self.evidence / "server.log")
        _copy(WINE_LOG, self.evidence / "wine.log")
        (self.evidence / "launch-attempts.txt").write_text(f"{attempt}\n")

        if not login_ok:
            self.fail(f"no 'User {self.account} logging on!' appeared in the server log "
                      f"after {ATTEMPTS} launch attempts")
            return
        self.say(f"login observed (attempt {attempt}); holding the client for the "
                 f"{ALIVE_HOLD} s window")
        # Liveness is judged by the exact pid of THIS launch only — no fallback to
        # "any game.dll process" (another install's client could satisfy that).
        pids = client_runtime.game_pids(self.co)
        if not pids:
            self.fail("could not find the client process from this launch")
            return
        self.say(f"client pid: {pids[0]}")
        time.sleep(ALIVE_HOLD)
        if _alive(pids[0]):
            self.say(f"client process alive {ALIVE_HOLD} s after login — PASS")
        else:
            self.fail(f"client process died within {ALIVE_HOLD} s after login")
        # A wine crash signature means the client is broken even if a process lingers.
        if "nodrv_CreateWindow" in _read(WINE_LOG):
            self.fail("wine log shows nodrv_CreateWindow (client window creation failed)")

    # --- 7. Clean shutdown ----------------------------------------------------
    def server_shutdown(self) -> None:
        self.step("server shutdown")
        if self.server_script("stop", quiet=False) != 0:
            self.fail("server did not stop cleanly")

    def cleanup(self) -> None:
        # Tear down any client this run launched: the Launcher's loop and the wine
        # tree under this install's prefix. Scoped to this Checkout so another
        # install's processes are never signalled.
        try:
            client_runtime.kill(self.co)
        except DaocError:
            pass
        if (self.server_dir / "daoc-server.sh").is_file():
            self.server_script("stop", quiet=True)
        # Restore the standard config so the install works as documented afterwards.
        backup = self.config.with_name("serverconfig.xml.bak")
        if backup.is_file():
            os.replace(backup, self.config)

    def evidence_listing(self) -> None:
        print(f"\n=== evidence bundle: {self.evidence.name}/ ===", flush=True)
        result = proc.run([LS, "-la", self.evidence], check=False)
        lines = (result.stdout or "").splitlines()[1:]
        if lines:
            print("\n".join(lines), flush=True)


def move_ports(text: str) -> str:
    """The script's sed: on each line, the first 10300/10400 port of each kind
    moves to 20300/20400."""
    subs = (("<Port>10300</Port>", f"<Port>{GAME_PORT}</Port>"),
            ("<RegionPort>10400</RegionPort>", f"<RegionPort>{REGION_PORT}</RegionPort>"),
            ("<UdpPort>10400</UdpPort>", f"<UdpPort>{REGION_PORT}</UdpPort>"))
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        for old, new in subs:
            line = line.replace(old, new, 1)
        lines[i] = line
    return "".join(lines)


def _ignore_sighup() -> None:
    signal.signal(signal.SIGHUP, signal.SIG_IGN)


def _start_detached(argv: List[Path], cwd: Path, log: Path) -> "subprocess.Popen[bytes]":
    """nohup argv in a new session, stdin from /dev/null and stdout+stderr into
    log (truncated), so it outlives this process and its terminal."""
    with log.open("wb") as out:
        return subprocess.Popen([str(a) for a in argv], cwd=str(cwd), stdin=subprocess.DEVNULL,
                                stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                preexec_fn=_ignore_sighup)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _launch(checkout: Checkout, account: str, password: str) -> None:
    """Open the Launcher for one attempt at character select. The password rides
    on the argv the Launcher requires and is never printed."""
    proc.run([client_runtime.OPEN, "-n", checkout.launcher_app,
              "--env", "DAOC_LAUNCHER_RETRIES=1",
              "--args", "wine", "game.dll", "127.0.0.1", str(GAME_PORT), "42", account, password],
             check=False)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return ""


def _tail(path: Path, offset: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def _truncate(path: Path) -> None:
    try:
        path.open("w").close()
    except OSError:
        pass


def _copy(src: Path, dest: Path) -> None:
    try:
        shutil.copyfile(src, dest)
    except OSError:
        pass


def _on_signal(signum: int, frame: object) -> None:
    raise SystemExit(128 + signum)


def run(checkout: Checkout, account: Optional[str] = None, password: Optional[str] = None) -> int:
    """The acceptance run; 0 when every step passes, else 1."""
    account = account or f"e2e{int(time.time())}"
    password = password or DEFAULT_PASSWORD
    lock = checkout.root / ".e2e.lock"
    # One run at a time: two concurrent runs would fight over the same wine
    # prefix, server ports, and logs.
    try:
        lock.mkdir()
    except FileExistsError:
        print(f"another e2e run is active (remove {lock} if that is stale)",
              file=sys.stderr, flush=True)
        return 1
    # A TERM or HUP still runs the cleanup below, as the script's EXIT trap did.
    previous = {s: signal.signal(s, _on_signal) for s in (signal.SIGTERM, signal.SIGHUP)}
    r = _Run(checkout, account, password)
    try:
        # Stale files from a previous run would be mistaken for this run's evidence
        # (the per-attempt wine logs in particular); start clean.
        shutil.rmtree(r.evidence, ignore_errors=True)
        r.evidence.mkdir(parents=True, exist_ok=True)
        try:
            r.server_install()
            r.server_boot()
            r.account_create()
            r.client_install()
            r.client_launch()
        except _Failed:
            return 1
        r.server_shutdown()
        r.evidence_listing()
        if r.failed:
            print("\nE2E: FAIL (see above)", flush=True)
            return 1
        print("\nE2E: PASS", flush=True)
        return 0
    finally:
        try:
            r.cleanup()
        finally:
            for s, handler in previous.items():
                signal.signal(s, handler)
            try:
                lock.rmdir()
            except OSError:
                pass
