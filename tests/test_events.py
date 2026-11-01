"""The OfflineDAoC app's event channel: DAOC_EVENTS=<fd> out, answers on stdin."""
import io
import itertools
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from tests.support import make_checkout, run_cli

from daoc_cli import cli, client, errors, events, proc, server
from daoc_cli.checkout import Checkout
from daoc_cli.errors import DaocError


@contextmanager
def channel():
    """DAOC_EVENTS pointing at a fresh pipe; .events holds what was written once the block ends."""
    r, w = os.pipe()
    ch = SimpleNamespace(events=[], env={"DAOC_EVENTS": str(w)})
    try:
        with mock.patch.dict(os.environ, ch.env):
            yield ch
    finally:
        os.close(w)
        with os.fdopen(r, encoding="utf-8") as f:
            ch.events = [json.loads(line) for line in f.read().splitlines()]


def group(handler):
    """cli.GROUPS plus a `t` group whose one parser runs handler."""
    def register(groups):
        groups.add_parser("t").set_defaults(func=handler)
    return mock.patch.object(cli, "GROUPS", cli.GROUPS + (("t", SimpleNamespace(register=register)),))


class EventTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = make_checkout(self.tmp.name)

    def test_say_is_a_step_event_and_keeps_its_stderr_line(self):
        def handler(args, checkout):
            errors.say("downloading Wine")
            return 0
        with channel() as ch, group(handler):
            code, out, err = run_cli(["t"], self.root)
        self.assertEqual((code, out, err), (0, "", "daoc: downloading Wine\n"))
        self.assertEqual(ch.events, [{"t": "step", "msg": "downloading Wine"}])

    def test_a_daoc_error_is_an_error_event_with_its_code(self):
        def handler(args, checkout):
            raise DaocError("refused", 2)
        with channel() as ch, group(handler):
            code, out, err = run_cli(["t"], self.root)
        self.assertEqual((code, out, err), (2, "", "daoc: refused\n"))
        self.assertEqual(ch.events, [{"t": "error", "msg": "refused", "code": 2}])

    def answer(self, line):
        err = io.StringIO()
        with channel() as ch, mock.patch.object(events, "_ids", itertools.count(1)), \
                mock.patch("sys.stdin", io.StringIO(line)), mock.patch("sys.stderr", err):
            result = errors.ask("Stop the server?")
        return result, ch.events, err.getvalue()

    def test_ask_round_trip(self):
        yes, sent, err = self.answer('{"id": 1, "answer": true}\n')
        self.assertTrue(yes)
        self.assertEqual(sent, [{"t": "ask", "id": 1, "question": "Stop the server?", "default": False}])
        self.assertEqual(err, "Stop the server? [y/N] ")
        self.assertFalse(self.answer('{"id": 1, "answer": false}\n')[0])
        self.assertFalse(self.answer("")[0])                           # the app went away
        self.assertFalse(self.answer('{"id": 2, "answer": true}\n')[0])  # another question's answer
        self.assertFalse(self.answer("yes\n")[0])                      # not JSON

    def test_a_refusal_off_a_terminal_becomes_a_question_for_the_app(self):
        co = Checkout(self.root)
        with channel() as ch, mock.patch.object(events, "_ids", itertools.count(1)), \
                mock.patch("sys.stdin", io.StringIO('{"id": 1, "answer": false}\n')), \
                mock.patch("sys.stderr", io.StringIO()), \
                mock.patch.object(server, "status", return_value=(True, "running (pid 7)")):
            with self.assertRaises(DaocError) as cm:
                server._stop_first(co)
        self.assertEqual(cm.exception.msg, "server update refused: the server is running")
        self.assertEqual(ch.events[0]["question"], "The server is running (pid 7). Stop it to update?")

    def test_children_cannot_read_the_answer_channel(self):
        r, w = os.pipe()
        os.write(w, b'{"id": 1, "answer": true}\n')
        os.close(w)
        saved = os.dup(0)
        try:
            os.dup2(r, 0)
            with channel():
                result = proc.run(["/bin/cat"])
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(r)
        self.assertEqual(result.stdout, "")

    def test_wine_tools_cannot_read_the_answer_channel(self):
        r, w = os.pipe()
        os.write(w, b'{"id": 1, "answer": true}\n')
        os.close(w)
        saved = os.dup(0)
        try:
            os.dup2(r, 0)
            with channel():
                rc, output = client._wine_output(["/bin/cat"], {})
        finally:
            os.dup2(saved, 0)
            os.close(saved)
            os.close(r)
        self.assertEqual((rc, output), (0, ""))

    def test_a_program_daoc_execs_does_not_inherit_the_channel(self):
        r, w = os.pipe()
        os.set_inheritable(w, True)
        try:
            with mock.patch.dict(os.environ, {"DAOC_EVENTS": str(w)}):
                events.close_on_exec()
            self.assertFalse(os.get_inheritable(w))
        finally:
            os.close(r)
            os.close(w)


if __name__ == "__main__":
    unittest.main()
