"""Every path daoc uses, derived from one Checkout root.

The Checkout is the home: the git checkout holding this package also
holds the manifest, the Server and Client installs and the download caches.
There is no --home / DAOC_HOME; tests pass an explicit root instead.
"""
import json
import os
from functools import cached_property
from pathlib import Path
from typing import Any, Dict, Optional, Union

from daoc_cli.errors import DaocError

ROOT = Path(__file__).resolve().parents[1]


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
        self.wine_home = _env_path("DAOC_WINE_HOME", self.root / "dist" / "wine")
        self.prefix = _env_path("DAOC_WINEPREFIX", self.root / "dist" / "prefix")
        self.launcher_src = self.root / "client" / "DAoCLauncher.app"
        self.launcher_app = self.root / "dist" / "DAoCLauncher.app"
        self.graphics_src = self.root / "upstream" / "graphics"
        self.downloads = self.root / "downloads"
        self.state = self.root / ".daoc"

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
