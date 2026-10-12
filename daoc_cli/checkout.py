"""Every path daoc uses, derived from one Checkout root.

The Checkout is the home: the git checkout holding this package also
holds the manifest, the Server and Client installs and the download caches.
There is no --home / DAOC_HOME; tests pass an explicit root instead.
"""
import json
import os
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from daoc_cli.errors import DaocError

ROOT = Path(__file__).resolve().parents[1]

# Wine flavours `daoc client install --wine` installs side by side:
#   rosetta: athei/wine-build (manifest `wine`, x86_64 under Rosetta 2)
#   arm64:   Hadron's runtime (manifest `wine_arm64`, arm64 with FEX, no Rosetta)
FLAVOURS = ("rosetta", "arm64")
DEFAULT_FLAVOUR = "rosetta"
_DIRS = {"rosetta": ("wine", "prefix"), "arm64": ("wine-arm64", "prefix-arm64")}


def _env_path(name: str, default: Path) -> Path:
    """`${NAME:-default}`; a relative value resolves against the caller's cwd."""
    value = os.environ.get(name, "")
    return Path(os.path.abspath(value)) if value else default


class Checkout:
    def __init__(self, root: Optional[Union[str, Path]] = None) -> None:
        self.root = Path(root).resolve() if root is not None else ROOT
        self.server_dir = self.root / "server" / "dist" / "daoc-server"
        self.client_root = self.root / "dist" / "OfflineDAoC"
        self.app_dir = self.client_root / "runtime" / "client-opendaoc" / "app"
        self.flavour_file = self.root / "dist" / ".wine-flavour"
        wine_home, prefix = self.flavour_paths(self.flavour)
        self.wine_home = _env_path("DAOC_WINE_HOME", wine_home)
        self.prefix = _env_path("DAOC_WINEPREFIX", prefix)
        self.launcher_src = self.root / "client" / "DAoCLauncher.app"
        self.launcher_app = self.root / "dist" / "DAoCLauncher.app"
        self.graphics_src = self.root / "upstream" / "graphics"
        self.downloads = self.root / "downloads"
        self.state = self.root / ".daoc"

    @property
    def flavour(self) -> str:
        """The Wine flavour `daoc client install --wine` last completed
        (dist/.wine-flavour); rosetta when none is recorded."""
        try:
            value = self.flavour_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return DEFAULT_FLAVOUR
        except OSError as e:
            raise DaocError(f"cannot read {self.flavour_file}: {e}") from None
        if value not in FLAVOURS:
            raise DaocError(f"{self.flavour_file} names an unknown Wine flavour {value!r} "
                            f"(expected one of: {', '.join(FLAVOURS)})")
        return value

    def flavour_paths(self, flavour: str) -> Tuple[Path, Path]:
        """(wine home, prefix) a flavour installs into under dist/."""
        wine, prefix = _DIRS[flavour]
        dist = self.root / "dist"
        return dist / wine, dist / prefix

    @property
    def wine_is_arm64(self) -> bool:
        """wine_home is an arm64 Wine (Hadron's layout), judged by its files so a
        DAOC_WINE_HOME override is classified too."""
        return (self.wine_home / "lib" / "wine" / "aarch64-unix").is_dir()

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
