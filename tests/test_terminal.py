import fcntl
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

import library


class TerminalTest(unittest.TestCase):
    def test_pty_search_and_resume(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "db"
            db = library.connect(path)
            self.addCleanup(db.close)
            source = Path(d) / "sample"
            source.write_text("Gen. 1:1 start\nJohn 3:16 needle")
            library.install(db, source, "T")
            master, slave = pty.openpty()
            self.addCleanup(os.close, master)
            self.addCleanup(os.close, slave)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 12, 38, 0, 0))
            env = dict(os.environ, BVIM_DB=str(path), TERM="xterm-256color")
            env.pop("ESCDELAY", None)
            p = subprocess.Popen(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "ui.py"),
                    "tui",
                ],
                env=env,
                stdin=slave,
                stdout=slave,
                stderr=slave,
            )
            self.addCleanup(p.wait)
            self.addCleanup(p.kill)
            def wait_for(marker, timeout=5):
                output = b""
                deadline = time.monotonic() + timeout
                while marker not in output:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
                        self.fail(f"Timed out waiting for {marker!r}: {output[-500:]!r}")
                    output += os.read(master, 65536)
                return output

            wait_for(b"NORMAL")
            os.write(master, b"/")
            wait_for(b"SEARCH")
            started = time.monotonic()
            os.write(master, b"\x1b")
            wait_for(b"NORMAL")
            self.assertLess(time.monotonic() - started, 0.25, "Standalone Escape was delayed")

            os.write(master, b"\x1bOB")  # Down in xterm application cursor mode.
            wait_for(b"John 3:16")
            os.write(master, b"k")
            wait_for(b"Genesis 1:1")

            output = b""
            os.write(master, b"/wrong query\x15needle extra  \x17\r\rq")
            end = time.monotonic() + 4
            while p.poll() is None and time.monotonic() < end:
                if select.select([master], [], [], 0.1)[0]:
                    output += os.read(master, 65536)
            self.assertEqual(p.poll(), 0, repr(output[-2000:]))
            self.assertEqual(
                db.execute("SELECT value FROM settings WHERE key='last:T'").fetchone(),
                ("43003016",),
            )
