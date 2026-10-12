"""`daoc admin …`: exec the Server install's daoc-admin with the arguments untouched.

No chdir: daoc-admin resolves its own directory.
"""
import argparse

from daoc_cli import proc, server
from daoc_cli.checkout import Checkout


def register(groups: "argparse._SubParsersAction") -> None:
    p = groups.add_parser("admin", help="manage the running server (daoc-admin passthrough)", add_help=False,
                          description="Runs <server>/daoc-admin with the given arguments.")
    p.set_defaults(func=handle)


def handle(args: argparse.Namespace, checkout: Checkout) -> int:
    path = server.tool(checkout, "daoc-admin")
    proc.execv([str(path), *(args.passthrough or [])])
