"""Machine-readable events for the OfflineDAoC app.

With DAOC_EVENTS=<fd> (a decimal file descriptor the app opened for this
process), daoc writes one JSON object per line to that fd, besides its
unchanged stderr text, and reads the app's answers to `ask` and `secret` as
JSON lines on stdin. The variable is read at every call. A write to a channel
the app has closed is dropped: the stderr text still says everything.

Events: {"t": "step", "msg"}, {"t": "download", "path", "bytes", "what"},
{"t": "ask", "id", "question", "default"}, {"t": "secret", "id", "what"},
{"t": "error", "msg", "code"}. The exit status is the result; there is no
"done" event.
"""
import itertools
import json
import os
import sys
from typing import Any, Dict, Optional

_ids = itertools.count(1)


def _fd() -> Optional[int]:
    value = os.environ.get("DAOC_EVENTS", "")
    return int(value) if value.isdigit() else None


def on() -> bool:
    """Whether the app is listening (DAOC_EVENTS names a file descriptor)."""
    return _fd() is not None


def emit(kind: str, **fields: Any) -> None:
    """Write one event; nothing when the app is not listening."""
    fd = _fd()
    if fd is None:
        return
    data = (json.dumps(dict(t=kind, **fields), ensure_ascii=False) + "\n").encode("utf-8")
    try:
        while data:
            data = data[os.write(fd, data):]
    except OSError:
        pass


def request(kind: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Emit a question with a fresh id and return the app's answer to it: the
    next stdin line as a JSON object carrying that id. None on EOF, on a line
    that is not a JSON object, or on an answer to another question."""
    ident = next(_ids)
    emit(kind, id=ident, **fields)
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        answer = json.loads(line)
    except ValueError:
        return None
    if not isinstance(answer, dict) or answer.get("id") != ident:
        return None
    return answer


def close_on_exec() -> None:
    """Keep the channel out of a program daoc execs: daoc-server.sh would hand
    it to the background server, which then holds the app's pipe open."""
    fd = _fd()
    if fd is None:
        return
    try:
        os.set_inheritable(fd, False)
    except OSError:
        pass
