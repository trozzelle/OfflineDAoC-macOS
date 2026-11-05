"""Every path daoc uses, derived from a code root and a data home.

Two roots. The code root holds daoc itself (daoc_cli/, manifest.json,
version.txt, client/DAoCLauncher.app, server/tools/). The data home holds what
daoc installs and records (dist/, server/dist/, downloads/, upstream/, .daoc/).
In a git Checkout both are the Checkout. OfflineDAoC.app keeps the code root
read-only inside its bundle and sets DAOC_DATA (not DAOC_HOME: daoc-server.sh
reads that as its own folder) to the data home; Checkout(home=...) overrides it.
"""
import json
import os
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional, Tuple, Union

from daoc_cli.errors import DaocError

ROOT = Path(__file__).resolve().parents[1]


class Flavour(NamedTuple):
    """A Wine `daoc client install --wine` installs side by side with the others."""
    title: str                   # what install calls it
    wine_dir: str                # its Wine, under dist/
    prefix_dir: str              # its prefix, under dist/
    windows_user: Optional[str]  # the user its Wine creates; None: the macOS user name

    def prefix_user(self) -> str:
        return self.windows_user or os.environ.get("USER", "")


# Wine flavours `daoc client install --wine` installs side by side:
#   rosetta: athei/wine-build (manifest `wine`, x86_64 under Rosetta 2)
#   arm64:   Hadron's runtime (manifest `wine_arm64`, arm64 with FEX, no Rosetta)
FLAVOURS: Dict[str, Flavour] = {
    "rosetta": Flavour("CrossOver Wine (x87sidecar, Rosetta 2)", "wine", "prefix", "crossover"),
    "arm64": Flavour("arm64 Wine with FEX (Hadron, no Rosetta)", "wine-arm64", "prefix-arm64",
                     None),
}
DEFAULT_FLAVOUR = "rosetta"


def _env_path(name: str) -> Optional[Path]:
    """$NAME, or None when unset/empty; a relative value resolves against the caller's cwd."""
    value = os.environ.get(name, "")
    return Path(os.path.abspath(value)) if value else None


def wine_is_arm64(wine_home: Path) -> bool:
    """wine_home is an arm64 Wine (Hadron's layout), judged by its files so a
    DAOC_WINE_HOME override is classified too. The Launcher runs the same test."""
    return (wine_home / "lib" / "wine" / "aarch64-unix").is_dir()


def wine_env(wine_home: Path, prefix: Path) -> Dict[str, str]:
    """os.environ plus what running wine_home's wine/wineserver on prefix needs.
    prefix must be absolute: wine rejects a relative WINEPREFIX."""
    env = dict(os.environ, WINEPREFIX=str(prefix))
    if wine_is_arm64(wine_home):
        # Hadron's Wine opens FreeType and friends by name from its ext/lib.
        env["DYLD_FALLBACK_LIBRARY_PATH"] = str(wine_home / "ext" / "lib")
    return env


def _flavour_fix() -> str:
    return ("; rewrite it by installing the Wine you use: "
            + " or ".join(f"daoc client install --wine {f}" for f in FLAVOURS))


class Checkout:
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

    @property
    def flavour(self) -> str:
        """The Wine flavour `daoc client install --wine` last completed
        (dist/.wine-flavour); rosetta when none is recorded."""
        try:
            value = self.flavour_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return DEFAULT_FLAVOUR
        except OSError as e:
            raise DaocError(f"cannot read {self.flavour_file}: {e}{_flavour_fix()}") from None
        if value not in FLAVOURS:
            raise DaocError(f"{self.flavour_file} names an unknown Wine flavour {value!r} "
                            f"(expected one of: {', '.join(FLAVOURS)}){_flavour_fix()}")
        return value

    def flavour_paths(self, flavour: str) -> Tuple[Path, Path]:
        """(wine home, prefix) a flavour installs into under dist/."""
        f = FLAVOURS[flavour]
        dist = self.home / "dist"
        return dist / f.wine_dir, dist / f.prefix_dir

    @cached_property
    def wine_home(self) -> Path:
        """DAOC_WINE_HOME, else the recorded flavour's Wine."""
        return self._wine_home_env or self.flavour_paths(self.flavour)[0]

    @cached_property
    def prefix(self) -> Path:
        """DAOC_WINEPREFIX, else the recorded flavour's prefix."""
        return self._prefix_env or self.flavour_paths(self.flavour)[1]

    def assume_flavour(self, flavour: str) -> None:
        """wine_home/prefix as if the record named flavour (the overrides still
        win), without reading it: `daoc client install --wine` replacing a bad one."""
        wine_home, prefix = self.flavour_paths(flavour)
        self.wine_home = self._wine_home_env or wine_home
        self.prefix = self._prefix_env or prefix

    @cached_property
    def manifest(self) -> Dict[str, Any]:
        """manifest.json, parsed on first use."""
        path = self.root / "manifest.json"
        try:
            with path.open(encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise DaocError(f"{path} is missing") from None
        except (OSError, ValueError) as e:
            raise DaocError(f"cannot read {path}: {e}") from None

    @cached_property
    def version(self) -> str:
        """version.txt: the daoc release this Checkout is (release-please writes it)."""
        path = self.root / "version.txt"
        try:
            return path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            raise DaocError(f"{path} is missing") from None
        except (OSError, ValueError) as e:
            raise DaocError(f"cannot read {path}: {e}") from None
