"""`daoc admin …` and `daoc progress …`: exec the Server install's daoc-admin or
daoc-progress with the arguments untouched.

No chdir: each tool resolves its own directory.
"""
import argparse

from daoc_cli import proc, server
from daoc_cli.checkout import Checkout


class Passthrough:
    """The group `name`, which execs <server>/`tool`."""

    def __init__(self, name: str, tool: str, help: str) -> None:
        self.name, self.tool, self.help = name, tool, help

    def register(self, groups: "argparse._SubParsersAction") -> None:
        p = groups.add_parser(self.name, help=self.help, add_help=False,
                              description=f"Runs <server>/{self.tool} with the given arguments.")
        p.set_defaults(func=self.handle)

    def handle(self, args: argparse.Namespace, checkout: Checkout) -> int:
        path = server.tool(checkout, self.tool)
        proc.execv([str(path), *(args.passthrough or [])])


admin = Passthrough("admin", "daoc-admin", "manage the running server (daoc-admin passthrough)")
progress = Passthrough("progress", "daoc-progress", "saved-progress tools (daoc-progress passthrough)")
