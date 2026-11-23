"""Measure real import, first-process reads and keyboard tasks on a private file."""

import argparse
import curses
import json
import os
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import library
import study
from reader import State, interact
from refs import bounds, label


class Terminal:
    def __init__(self, keys):
        self.keys = iter(keys)
        self.mode = None
        self.transitions = 0

    def getmaxyx(self):
        return (24, 80)

    def erase(self):
        pass

    def refresh(self):
        pass

    def get_wch(self):
        return next(self.keys)

    def addnstr(self, y, x, line, n, attr):
        if y == 0:
            mode = line.split()[0]
            self.transitions += int(self.mode is not None and mode != self.mode)
            self.mode = mode


def timed(fn, *args):
    t = time.perf_counter()
    fn(*args)
    return (time.perf_counter() - t) * 1000


def lexical_benchmark():
    import lexical
    from lexpane import show

    for ref in ("John 1:1", "Gen 1:1"):
        k = bounds(ref)[0]
        command = [sys.executable, "ui.py", "lex", ref, "--format", "jsonl"]
        call = lambda: subprocess.run(command, stdout=subprocess.DEVNULL, check=True)
        process = [timed(call) for _ in range(6)]
        print(
            ref,
            "first / repeated fresh processes ms",
            round(process[0], 3),
            round(statistics.median(process[1:]), 3),
        )
        for name, fn in [
            ("verse", lambda db: lexical.verse(db, k)),
            (
                "lemma definitions",
                lambda db: lexical.definitions(
                    db, "λόγος" if ref.startswith("John") else "רֵאשִׁית"
                ),
            ),
            ("pane to first input", lambda db: show(Terminal("\x1b"), db, k)),
        ]:
            db = library.connect()
            try:
                first = timed(fn, db)
                warm = statistics.median(timed(fn, db) for _ in range(100))
                print(
                    ref,
                    name,
                    "new connection / warm median ms",
                    round(first, 3),
                    round(warm, 3),
                )
            finally:
                db.close()

        class MotionTerminal(Terminal):
            def __init__(self):
                super().__init__("jk" * 50 + "\x1b")
                self.frames = []

            def get_wch(self):
                self.frames.append(time.perf_counter())
                return super().get_wch()

        db = library.connect()
        try:
            term = MotionTerminal()
            show(term, db, k)
            deltas = [1000 * (b - a) for a, b in zip(term.frames, term.frames[1:])]
            print(ref, "token movement median ms", round(statistics.median(deltas), 3))
        finally:
            db.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("file", nargs="?")
    p.add_argument(
        "--lexical",
        action="store_true",
        help="benchmark installed resources in BVIM_DB",
    )
    p.add_argument("--legacy-modules", type=Path)
    args = p.parse_args()
    if args.lexical:
        lexical_benchmark()
        return
    if not args.file:
        p.error("supply a translation file or --lexical")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bvim.db"
        db = library.connect(path)
        print("Import ms", round(timed(lambda: library.install(db, args.file, "A")), 2))
        print(
            "Process peak RSS at end of import (platform units)",
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        )
        env = dict(os.environ, BVIM_DB=str(path))

        def call(argv):
            subprocess.run(
                [sys.executable, *argv], env=env, stdout=subprocess.DEVNULL, check=True
            )

        commands = [
            ["ui.py", "read", "Jn3:16"],
            ["ui.py", "search", '"eternal life"', "--in", "NT"],
        ]
        if args.legacy_modules:
            env["PYTHONPATH"] = str(args.legacy_modules)
            commands += [
                ["legacy_ui.py", "--print", "--versions", "RCV", "John 3:16"],
                ["legacy_ui.py", "--search", "eternal life", "--versions", "RCV"],
            ]
        for argv in commands:
            samples = [timed(call, argv) for _ in range(8)]
            print(
                argv,
                "first process / warm process median ms",
                round(samples[0], 2),
                round(statistics.median(samples[1:]), 2),
            )
        for name, fn in [
            ("passage", lambda: list(library.passage(db, "A", bounds("Jn3")))),
            ("search", lambda: library.search(db, ["A"], '"eternal life"')),
        ]:
            print(
                name,
                "warm median ms",
                round(statistics.median(timed(fn) for _ in range(50)), 3),
            )
        # Same source under local benchmark IDs isolates switching cost.
        for v in ("B", "C"):
            library.install(db, args.file, v)
        sample = Path(tmp) / "terms.jsonl"
        sample.write_text(
            json.dumps(
                {
                    "term": "demo",
                    "kind": "lexicon",
                    "body": "benchmark fixture",
                    "references": [
                        {"version": "A", "ref": ref} for ref in ("Jn3:16", "Rom5:8")
                    ],
                }
            )
        )
        study.load(db, sample, "fixture", "synthetic", "test")
        for task, start, keys in [
            ("reference", "Gen1:1", ":Jn3:16\n"),
            ("chapter", "Jn3:16", "l"),
            ("end", "Gen1:1", "G"),
            ("fifth hit", "Jn3:16", '/"eternal life"\n4j\n'),
            ("compare", "Jn1:1", ":versions A,B,C\n"),
            ("return", "Jn3:16", "l\x0f"),
            ("lexical occurrence and return", "Jn3:16", ":lookup demo\n\nj\n\x0f"),
            ("linked verse and return", "Jn3:16", "\n\nj\n\x0f"),
            ("copy selection", "Jn3:16", "vjy"),
            ("complete", "Gen1:1", ":Revelat\t22:21\n"),
        ]:
            samples = []
            for _ in range(5):
                with db:
                    db.execute("DELETE FROM settings WHERE key='search_history'")
                s = State(db, ["A"], start)
                term = Terminal(keys + "q")
                with (
                    patch.object(curses, "curs_set"),
                    patch("reader.shutil.which", return_value="pbcopy"),
                    patch("reader.subprocess.run"),
                ):
                    samples.append(timed(interact, term, s))
            print(
                task,
                len(keys),
                "keys",
                term.transitions,
                "mode changes",
                keys.count("\n"),
                "accepts",
                round(statistics.median(samples), 2),
                "ms",
                label(s.k),
                "back depth",
                len(s.back),
            )
        db.close()


if __name__ == "__main__":
    main()
