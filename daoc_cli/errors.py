"""The one error type daoc raises on purpose.

cli.main prints it as `daoc: <msg>` on stderr and exits with its code:
1 for a failure, 2 for a usage error or a refusal.
"""


class DaocError(Exception):
    def __init__(self, msg: str, code: int = 1) -> None:
        super().__init__(msg)
        self.msg = msg
        self.code = code
