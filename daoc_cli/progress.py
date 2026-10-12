"""`daoc progress …`: exec the Server install's daoc-progress with the arguments untouched.

No chdir: daoc-progress resolves its own directory.
"""
import argparse

from daoc_cli import proc, server
from daoc_cli.checkout import Checkout


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser("progress", help="saved-progress tools (daoc-progress passthrough)", add_help=False,
                          description="Runs <server>/daoc-progress with the given arguments.")
    p.set_defaults(func=handle)


def handle(args: argparse.Namespace, checkout: Checkout) -> int:
    path = server.tool(checkout, "daoc-progress")
    proc.execv([str(path), *(args.passthrough or [])])
