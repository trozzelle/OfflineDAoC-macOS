"""How daoc talks to the user on stderr.

DaocError is the one error type daoc raises on purpose. cli.main prints it as
`daoc: <msg>` on stderr and exits with its code: 1 for a failure, 2 for a usage
error or a refusal. say() prints a status line with the same prefix; ask() is
the y/N question.
"""
import sys


class DaocError(Exception):
    def __init__(self, msg: str, code: int = 1) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = code


def say(msg: str) -> None:
    print(f"daoc: {msg}", file=sys.stderr, flush=True)


def ask(question: str) -> bool:
    """A y/N question on the terminal; anything but y/yes (or EOF) is no."""
    try:
        print(f"{question} [y/N] ", end="", file=sys.stderr, flush=True)
        answer = input()
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")
