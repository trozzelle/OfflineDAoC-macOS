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

from daoc_cli import client, client_runtime, files, newclient, proc, selection, server
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
    def __init__(self, checkout: Checkout, account: str, password: str,
                 client_name: str = "original") -> None:
        self.client = client_name
        # The new client cannot change port: its run keeps the server on 10300.
        self.game_port = client_runtime.NEW_PORT if client_name == "new" else GAME_PORT
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
            game = selection.load(self.co).game
            try:
                server.install(self.co, game.version)
            except DaocError as e:
                self.abort(f"server install failed: {e.msg}")
            # As `daoc server install`: the fresh save below starts as the selected edition.
            server.set_edition(self.co, game.edition)
        else:
            self.say("server already installed")

    # --- 2. Boot on alternate ports -----------------------------------------
    def server_boot(self) -> None:
        self.step(f"server boot (alternate ports {GAME_PORT}/{REGION_PORT})" if self.client == "original"
                  else f"server boot (port {self.game_port})")
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
            # As daoc-server.sh's first start: config/edition picks the world.
            edition = _read(self.server_dir / "config" / "edition").strip() or "classic"
            name = "world-sluaghbinder.sqlite" if edition == "sluaghbinder" else "world.sqlite"
            _copy(self.server_dir / "defaults" / name, world)
        text = _read(self.config)
        if self.client == "original" and "<Port>10300</Port>" in text:
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
            if LISTENING in _read(console) and _port_open(self.game_port):
                self.say(f"server is listening (console.out + port {self.game_port} OK)")
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
        if self.client == "new":
            if not (self.co.new_client_project / "project.godot").is_file():
                try:
                    newclient.install(self.co, selection.load(self.co).game)
                except DaocError as e:
                    self.abort(f"new client install failed: {e.msg}")
            else:
                self.say("new client already installed")
            return
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

    def client_launch_new(self) -> None:
        self.step("new client launch")
        server_log = self.server_dir / "logs" / "server.log"
        logging_on = re.compile(r"LoginRequestHandler.*User " + re.escape(self.account)
                                + r" logging on!")
        offset = files.size(server_log)
        client_runtime.kill(self.co)
        _launch_new(self.co, self.account, self.password)
        login_ok = False
        deadline = time.monotonic() + ATTEMPT_WINDOW
        while time.monotonic() < deadline:
            new = files.tail(server_log, offset)
            if "Wrong password" in new:
                self.fail("server rejected the login (Wrong password) — account/password mismatch")
                break
            if logging_on.search(new):
                show = self.admin("accounts", "show", self.account)
                (self.evidence / "account-show.txt").write_text(show + "\n")
                if re.search(r"last login [0-9]", show):
                    login_ok = True
                    break
            time.sleep(2)
        _copy(server_log, self.evidence / "server.log")
        _copy(client_runtime.NEW_LOG, self.evidence / "new-client.log")
        if not login_ok:
            self.fail(f"no 'User {self.account} logging on!' appeared in the server log "
                      f"within {ATTEMPT_WINDOW} s")
            return
        self.say(f"login observed; holding the new client for the {ALIVE_HOLD} s window")
        pids = client_runtime.new_pids(self.co)
        if not pids:
            self.fail("could not find the client process from this launch")
            return
        self.say(f"client pid: {pids[0]}")
        time.sleep(ALIVE_HOLD)
        if _alive(pids[0]):
            self.say(f"client process alive {ALIVE_HOLD} s after login — PASS")
        else:
            self.fail(f"client process died within {ALIVE_HOLD} s after login")

    def client_launch(self) -> None:
        if self.client == "new":
            self.client_launch_new()
            return
        self.step("client launch")
        server_log = self.server_dir / "logs" / "server.log"
        logging_on = re.compile(r"LoginRequestHandler.*User " + re.escape(self.account)
                                + r" logging on!")
        offset = files.size(server_log)
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
                new = files.tail(server_log, offset)
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


def _start_detached(argv: List[Path], cwd: Path, log: Path) -> None:
    """Start argv in the background the way the script's `( nohup … & )` did: a
    short-lived shell starts it and exits, so launchd adopts it and reaps it when
    it exits. A direct child of this process would linger as a zombie after it
    exits, and `daoc-server.sh stop` (kill -0) would keep counting it as running.
    stdin from /dev/null; stdout and stderr into log (truncated)."""
    subprocess.run(["/bin/sh", "-c", 'log=$1; shift; nohup "$@" </dev/null >"$log" 2>&1 &',
                    "sh", str(log), *(str(a) for a in argv)], cwd=str(cwd), check=True)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def _launch_new(checkout: Checkout, account: str, password: str) -> None:
    """Open the New client once (it logs in and stops at realm select). The
    password rides on its argv and is never printed."""
    classic = selection.load(checkout).game.edition == "classic"
    proc.run(client_runtime.new_launch_argv(checkout, account, password, classic), check=False)


def _launch(checkout: Checkout, account: str, password: str) -> None:
    """Open the Launcher for one attempt at character select. The password rides
    on the argv the Launcher requires and is never printed. LaunchServices drops
    the caller's environment, so the Checkout's wine and prefix (DAOC_WINE_HOME /
    DAOC_WINEPREFIX, resolved) ride on --env: game_pids and kill look for the
    client under the same wine. So do the settings that wine needs
    (client_runtime.wine_defaults); the caller's other knobs are not forwarded."""
    proc.run([client_runtime.OPEN, "-n", checkout.launcher_app,
              "--env", "DAOC_LAUNCHER_RETRIES=1",
              "--env", f"DAOC_WINE_HOME={checkout.wine_home}",
              "--env", f"DAOC_WINEPREFIX={checkout.prefix}",
              *client_runtime.forwarded_env(client_runtime.wine_defaults(checkout)),
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


def _read(path: Path) -> str:
    try:
        return path.read_text(errors="replace")
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


def run(checkout: Checkout, account: Optional[str] = None, password: Optional[str] = None,
        client_name: str = "original") -> int:
    """The acceptance run; 0 when every step passes, else 1 (2: the new client's
    port is taken)."""
    account = account or f"e2e{int(time.time())}"
    password = password or DEFAULT_PASSWORD
    if client_name == "new" and _port_open(client_runtime.NEW_PORT):
        # The new client cannot be moved off 10300, so the run needs it free.
        print(f"port {client_runtime.NEW_PORT} is in use (another server?); the new client only "
              "connects to it, so stop that server first", file=sys.stderr, flush=True)
        return 2
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
    r = _Run(checkout, account, password, client_name)
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
