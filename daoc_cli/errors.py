"""How daoc talks to the user on stderr.

DaocError is the one error type daoc raises on purpose. cli.main prints it as
`daoc: <msg>` on stderr and exits with its code: 1 for a failure, 2 for a usage
error or a refusal. say() prints a status line with the same prefix; ask() is
the y/N question. With the app listening (DAOC_EVENTS), say() is also a `step`
event and ask() asks the app; interactive() says whether anyone can answer.
"""
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
