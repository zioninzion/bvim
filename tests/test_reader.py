import curses
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import library
import study
from reader import State, interact
from refs import book, bounds, label

ROOT = Path(__file__).resolve().parents[1]


class Screen:
    def __init__(self, keys, size):
        self.keys = iter(keys)
        self.size = size
        self.output = []
        self.rows = {}
        self.paint = []

    def get_wch(self):
        return next(self.keys)

    def getmaxyx(self):
        return self.size

    def addnstr(self, y, x, line, n, attr):
        self.output.append(line[:n])
        self.rows[y] = (line[:n], attr)
        self.paint.append((y, x, line[:n], attr))

    def erase(self):
        self.rows.clear()

    def refresh(self):
        pass


class ReaderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "db"
        self.f = self.path.with_suffix(".txt")
        self.db = library.connect(self.path)
        self.addCleanup(self.db.close)
        self.f.write_bytes(
            "Gen. 1:1  λόγος [אב]  \r\nJohn 3:16 eternal life\nJohn 3:17 life and works\nJohn 4:1 faith works".encode()
        )
        library.install(self.db, self.f, "A")

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "ui.py"), *args],
            env=dict(os.environ, BVIM_DB=str(self.path)),
            capture_output=True,
            check=False,
        )

    def test_refs(self):
        for phrase in ("Jn3:16", "John 3:16", "jhn 3 : 16", "John 3 16"):
            self.assertEqual(bounds(phrase), (43003016, 43003016))
        self.assertEqual(bounds("1Co 14:26-15:1"), (46014026, 46015001))
        self.assertEqual(bounds("gen 3 2"), bounds("Gen 3:2"))
        self.assertEqual(bounds("gen 3 4 6"), bounds("Gen 3:4-6"))
        self.assertEqual(bounds("1 Cor. 14 1 4"), bounds("1Co 14:1-4"))
        self.assertEqual(book("S.S."), 22)
        with self.assertRaisesRegex(ValueError, "Suggestions"):
            bounds("Ju")
        for ref in ("Jn 3:4-1", "Jn 2:x", "1Cor2:1000"):
            with self.assertRaises(ValueError):
                bounds(ref)

    def test_dotted_references(self):
        self.assertEqual(bounds("1 Cor. 14.26-15.1"), bounds("1Co14:26-15:1"))
        self.assertEqual(
            self.cli("John", "3.16").stdout, self.cli("John", "3:16").stdout
        )
        state = State(self.db, ["A"], "John 4:1")
        with patch.object(curses, "curs_set"):
            interact(Screen(":3.16\nq", (12, 40)), state)
        self.assertEqual(label(state.k), "John 3:16")

    def test_centered_reader(self):
        for height, width in ((5, 12), (8, 40), (25, 80)):
            for ref in ("Gen. 1:1", "Jn 3:16", "Jn 3:17", "Jn 4:1"):
                state = State(self.db, ["A"], ref)
                screen = Screen("q", (height, width))
                with patch.object(curses, "curs_set"):
                    interact(screen, state)
                line, attr = screen.rows[height // 2]
                self.assertTrue(line.startswith(str(state.k % 1000) + " "))
                self.assertEqual(attr, curses.A_REVERSE)
                if width >= 40 and ref == "Jn 3:17":
                    self.assertIn("eternal life", screen.rows[height // 2 - 1][0])
                    self.assertEqual(
                        screen.rows[height // 2 + 1],
                        ("John · Chapter 4", curses.A_BOLD),
                    )

    def test_verse_number_gutter(self):
        from reader import verse_lines

        self.f.write_text(
            "John 1:9 alpha beta gamma\nJohn 1:10 alpha beta gamma\nJohn 1:100 alpha beta gamma"
        )
        library.install(self.db, self.f, "Gutter")
        state = State(self.db, ["Gutter"])
        for i, number in enumerate((9, 10, 100)):
            lines, _ = verse_lines(state, i, 16, True, False, False, False, False)
            self.assertEqual(lines, [f"{number:<3} alpha beta", "    gamma"])
        lines, _ = verse_lines(state, 0, 16, False, False, False, False, False)
        self.assertEqual(lines, ["alpha beta", "gamma"])

    def test_book_heading_and_toggle(self):
        state = State(self.db, ["A"], "John 3:16")
        for keys, shown in [("q", True), ("Hq", False)]:
            screen = Screen(keys, (13, 40))
            with patch.object(curses, "curs_set"):
                interact(screen, state)
            self.assertEqual(screen.rows.get(4) == ("JOHN", curses.A_BOLD), shown)
            self.assertEqual(screen.rows.get(5) == ("Chapter 3", curses.A_BOLD), shown)
            self.assertTrue(screen.rows[6][0].startswith("16 "))

    def test_atomic_replace(self):
        for bad in ("Gen 1:1 ok\nGn 1:1 duplicate", "wrong", "Jn 1:1  "):
            self.f.write_text(bad)
            with self.assertRaises(ValueError):
                library.install(self.db, self.f, "a", replace=True)
            self.assertEqual(len(library.search(self.db, ["A"], "life")), 2)
        self.f.write_text("Gen 1:3 replacement")
        _, warnings = library.install(self.db, self.f, "a", replace=True)
        self.assertTrue(warnings)
        self.assertFalse(library.search(self.db, ["A"], "life"))

    def test_cli_compare(self):
        self.assertEqual(self.cli("export", "A").stdout, self.f.read_bytes())
        self.f.write_text("John 3:16 Other\nJohn 3:18 extra")
        library.install(self.db, self.f, "B")
        self.assertEqual(self.cli("use", "B").returncode, 0)
        self.assertEqual(library.edition(self.db), "B")
        rows = [
            json.loads(l)
            for l in self.cli(
                "compare", "Jn3", "-V", "A,B", "--format", "jsonl"
            ).stdout.splitlines()
        ]
        self.assertEqual(
            [r["text"] for r in rows][-4:], ["life and works", None, None, "extra"]
        )
        self.assertEqual(self.cli("read", "John 8").returncode, 2)
        self.assertEqual(self.cli("search", "absent").returncode, 1)

    def test_index(self):
        for q, n in [
            ('"eternal life"', 1),
            ("life NOT eternal", 1),
            ("faith AND works", 1),
            ("life OR faith", 3),
            ("NEAR(life works, 2)", 1),
            ("wor*", 2),
        ]:
            self.assertEqual(len(library.search(self.db, ["A"], q, "Jn3;Jn4")), n)
        self.assertFalse(library.search(self.db, ["A"], "life", "OT"))
        with self.assertRaises(ValueError):
            library.search(self.db, ["A"], '"')

    def test_command_prompt_word_and_line_editing(self):
        state = State(self.db, ["A"])
        screen = Screen(":wrong command\x15Joh\twrong  \x173.16\nq", (15, 60))
        with patch.object(curses, "curs_set"):
            interact(screen, state)
        self.assertEqual(label(state.k), "John 3:16")

    def test_biblehub_shortcuts(self):
        self.f.write_text("Gen 1:1 first\nS.S. 2:3 second\n1 Cor 14:26 third")
        library.install(self.db, self.f, "Links")
        state = State(self.db, ["Links"])
        with (
            patch.object(curses, "curs_set"),
            patch("reader.webbrowser.open_new_tab") as browser,
        ):
            interact(Screen("xpjxjpq", (16, 60)), state)
        self.assertEqual(
            [c.args[0] for c in browser.call_args_list],
            [
                "https://biblehub.com/text/genesis/1-1.htm",
                "https://biblehub.com/parallel/genesis/1-1.htm",
                "https://biblehub.com/text/songs/2-3.htm",
                "https://biblehub.com/parallel/1_corinthians/14-26.htm",
            ],
        )

    def test_search_history(self):
        with patch.object(curses, "curs_set"):
            state = State(self.db, ["A"])
            interact(Screen("/life\n\n/\x15works\n\nq", (20, 80)), state)
            state = State(self.db, ["A"])
            screen = Screen("/\x10\x0e\x15draft\x1b/\x10\x0e\x1bq", (20, 80))
            interact(screen, state)
        prompts = [line.strip() for line in screen.output if line.startswith("/")]
        self.assertEqual(prompts[:3], ["/works", "/life", "/works"])
        self.assertEqual(prompts[-3:], ["/draft", "/works", "/draft"])
        self.assertEqual(state.search_history(), ["works", "life"])

    def test_search_submission_and_result_jump(self):
        for ending, expected in [("j\x1bq", "Genesis 1:1"), ("j\nq", "John 3:17")]:
            state = State(self.db, ["A"], "Gen1:1")
            with patch.object(curses, "curs_set"):
                interact(Screen("/\x15life\n" + ending, (18, 80)), state)
            self.assertEqual(label(state.k), expected)
            self.assertEqual(len(state.back), int(expected != "Genesis 1:1"))

    def test_reference_search(self):
        query = "John 3.17,16-17; Gen 1:1; John 4"
        rows = library.search(self.db, ["A"], query)
        self.assertEqual(
            [label(k) for k, _, _ in rows],
            ["John 3:17", "John 3:16", "Genesis 1:1", "John 4:1"],
        )
        self.assertEqual(library.search_counts(self.db, ["A"], query, "NT"), (3, 3))
        self.assertEqual(
            self.cli("search", query, "--limit", "1").stdout.decode().split(" [")[0],
            "John 3:17",
        )
        state = State(self.db, ["A"])
        with patch.object(curses, "curs_set"):
            interact(Screen("/" + query + "\nj\nq", (18, 80)), state)
        self.assertEqual(label(state.k), "John 3:16")
        with self.assertRaises(ValueError):
            library.search(self.db, ["A"], "John 3:16; unknown")
        self.assertEqual(len(library.search(self.db, ["A"], "ref: John")), 3)

    def test_bare_terminal_launch(self):
        import ui

        self.f.write_text(
            "Mat 3:5 first\nMat 3:6 second\nMat 3:7 third\n1 Cor 14:26 first"
        )
        library.install(self.db, self.f, "Launch")
        for args, mode, focus, anchor, hits in [
            (["mat", "3:5"], "NORMAL", "Matthew 3:5", None, 0),
            (["mat", "3", "5", "7"], "VISUAL", "Matthew 3:5", 2, 0),
            (["mat", "3:5-7"], "VISUAL", "Matthew 3:5", 2, 0),
            (
                ["mat", "3:5", "1", "Cor", "14:26"],
                "NORMAL · RESULTS",
                "Matthew 3:5",
                None,
                2,
            ),
            (["first"], "NORMAL · RESULTS", "Matthew 3:5", None, 2),
            (["unknown word"], "SEARCH", "Matthew 3:5", None, 0),
        ]:
            screen = Screen("qq" if mode.endswith("RESULTS") else "\x1bq", (20, 80))

            def drive(
                app, state, query, anchor=anchor, screen=screen, focus=focus, hits=hits
            ):
                self.assertEqual(state.anchor, anchor)
                app(screen, state, query)
                self.assertEqual(label(state.k), focus)
                self.assertEqual(len(state.hits), hits)

            with (
                patch.dict(os.environ, BVIM_DB=str(self.path)),
                patch.object(sys.stdin, "isatty", return_value=True),
                patch.object(sys.stdout, "isatty", return_value=True),
                patch.object(curses, "wrapper", side_effect=drive),
            ):
                self.assertEqual(ui.main([*args, "-V", "Launch"]), 0)
            self.assertTrue(screen.output[0].startswith(mode), screen.output[0])

    def test_modal(self):
        for size in ((5, 18), (24, 80)):
            state = State(self.db, ["A"])
            screen = Screen("2jmaG'a:Jn4\n\x0f\t/\x15absent\x1bgg/\x15life\n\nNq", size)
            with patch.object(curses, "curs_set"):
                interact(screen, state)
            self.assertEqual(label(state.k), "John 3:17")
            self.assertEqual(
                self.db.execute("SELECT k FROM marks").fetchone()[0], 43003017
            )
            self.assertEqual(state.back[-1][1], 43003016)

    def test_search_match_style(self):
        state = State(self.db, ["A"])
        screen = Screen('/"eternal life"\n\nq', (15, 13))
        with (
            patch.object(curses, "curs_set"),
            patch.object(curses, "has_colors", return_value=False),
        ):
            interact(screen, state)
        matched = [
            (y, x, text)
            for y, x, text, attr in screen.paint
            if attr & curses.A_UNDERLINE
        ]
        self.assertIn((7, 4, "eternal"), matched)
        self.assertIn((8, 4, "life"), matched)
        # The same phrase in the preview wraps below its reference line.
        self.assertIn((2, 4, "eternal"), matched)
        self.assertNotIn((8, 0, "life and"), matched)
        self.assertEqual(state.rows(("A",), state.k)[0][1], "eternal life")

    def test_full_search_totals(self):
        self.f.write_text(
            "".join(f"John 1:{n} sea of glass, sea of glass.\n" for n in range(1, 121))
        )
        library.install(self.db, self.f, "B")
        self.f.write_text("John 1:1 sea of glass")
        library.install(self.db, self.f, "C")
        state = State(self.db, ["B", "C"])
        phrase = '"sea of glass"'
        preview, counts = state.preview(phrase)
        self.assertEqual(len(preview), 101)
        self.assertEqual(counts, (241, 120))
        self.assertEqual(
            self.cli("search", phrase, "-V", "B,C", "--limit", "1", "--count").stdout,
            b"241 hits in 120 verses\n",
        )
        self.assertEqual(
            library.search_counts(self.db, ["B", "C"], phrase, "Jn1:2-3"), (4, 2)
        )
        self.assertEqual(state.preview("absent")[1], (0, 0))
        screen = Screen(
            [*("/" + phrase), "KEY_DOWN", "\n", "R", "j", "q", "q"], (15, 80)
        )
        with patch.object(curses, "curs_set"):
            interact(screen, state)
        for mode in ("SEARCH", "NORMAL · RESULTS"):
            self.assertTrue(
                any(
                    line.startswith(mode + "  241 hits in 120 verses")
                    for line in screen.output
                )
            )

    def test_word_position_across_verses(self):
        self.f.write_text(
            "John 1:1 aa bb cc dd ee\nJohn 1:2 only two\nJohn 2:1 one two three four five"
        )
        library.install(self.db, self.f, "B")
        state = State(self.db, ["B"])
        screen = Screen(["4", "w", "KEY_DOWN", "j", "2", "k", "q"], (15, 70))
        with patch.object(curses, "curs_set"):
            interact(screen, state)
        self.assertEqual(
            [
                line.split("   ")[0]
                for line in screen.output
                if line.startswith("Word ")
            ],
            ["Word 4: dd", "Word 2: two", "Word 4: four", "Word 4: four", "Word 4: dd"],
        )

    def test_selected_word_overlay(self):
        self.f.write_text("John 1:1 漢字 token tail token end")
        library.install(self.db, self.f, "B")
        state = State(self.db, ["B"])

        def render(keys, size):
            screen = Screen(keys + "q", size)
            with (
                patch.object(curses, "curs_set"),
                patch.object(curses, "has_colors", return_value=False),
            ):
                interact(screen, state)
            return screen

        screen = render("/token\n\nwwwwb", (15, 70))
        # Only the selected occurrence gets the word cursor. Both occurrences
        # retain their search underline. Columns are measured in terminal cells.
        selected = {
            (x, text)
            for y, x, text, attr in screen.paint
            if y == 7 and attr == curses.A_BOLD | curses.A_UNDERLINE
        }
        self.assertEqual(selected, {(9, "token"), (20, "token")})
        self.assertEqual(screen.rows[7], ("tail", curses.A_BOLD))
        screen = render("b", (9, 13))
        self.assertEqual(screen.rows[4], ("end", curses.A_BOLD))

    def test_fts_highlight_positions(self):
        from layout import columns, differences, display_wrap

        self.f.write_text("John 1:1 ⟦ literal ⟧ 漢字 café life café lives")
        library.install(self.db, self.f, "B")
        body = library.search(self.db, ["B"], '"cafe life" OR liv*', highlight=True)[0][
            2
        ]

        def marked(text):
            return [text[a:b] for a, b in getattr(text, "spans", ())]

        self.assertEqual(marked(body), ["café life", "lives"])
        self.assertTrue(body.startswith("⟦ literal ⟧"))
        pieces = list(display_wrap(body, 3))
        self.assertEqual(
            "".join(hit for piece in pieces for hit in marked(piece)), "cafélifelives"
        )
        self.assertEqual(
            marked(next(columns([("A", "one"), ("B", body)], 100))),
            ["café life", "lives"],
        )
        self.assertEqual(marked(differences("different", body)), ["café life", "lives"])

    def test_word_alignment(self):
        item = {
            "term": "term",
            "kind": "lexicon",
            "body": "synthetic definition",
            "references": [
                {
                    "version": "A",
                    "ref": "Gn1:1",
                    "position": 1,
                    "surface": "λόγος",
                    "morph": "N",
                }
            ],
        }
        self.f.write_text(json.dumps(item))
        study.load(self.db, self.f, "aligned", "synthetic", "test")
        self.assertEqual(study.annotations(self.db, "A", 1001001, 1)[0][-1], "λόγος")
        self.assertFalse(study.annotations(self.db, "A", 1001001, 2))
        item["references"][0]["position"] = 2
        self.f.write_text(json.dumps(item))
        with self.assertRaisesRegex(ValueError, "match"):
            study.load(self.db, self.f, "invalid", "synthetic", "test")
        self.assertFalse(
            self.db.execute("SELECT * FROM resources WHERE id='invalid'").fetchall()
        )

    def test_exact_ranking(self):
        self.f.write_text(
            "John 1:1 life before eternal\nJohn 1:2 with eternal life\nJohn 1:3 eternal life\nJohn 1:4 lifetimes\nJohn 1:5 lifa"
        )
        library.install(self.db, self.f, "Rank")
        state = State(self.db, ["Rank"])
        query = "eternal life"
        self.assertEqual([k % 1000 for k, _, _ in state.find(query)], [3, 2, 1])
        self.assertIn(
            b"John 1:3", self.cli("search", query, "-V", "Rank", "--limit", "1").stdout
        )
        self.assertEqual([k % 1000 for k, _, _ in state.find("lif*")], [1, 2, 3, 4, 5])
        self.assertEqual([k % 1000 for k, _, _ in state.find("lifa*")], [5])
        state.sort = "reference"
        self.assertEqual(state.find(query, 1)[0][0] % 1000, 1)
        self.assertIn(
            b"John 1:5",
            self.cli(
                "search", "lifa", "-V", "Rank", "--mode", "fuzzy", "--limit", "1"
            ).stdout,
        )

    def test_search_modes(self):
        for mode, query in [("fuzzy", "warks"), ("glob", "w?r*s"), ("regex", "w.rks")]:
            result = self.cli("search", query, "--mode", mode, "--in", "John 4")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b"John 4:1", result.stdout)
            count = self.cli(
                "search",
                query,
                "--mode",
                mode,
                "--count",
                "--in",
                "John 4",
                "--format",
                "jsonl",
            )
            self.assertEqual(json.loads(count.stdout), {"hits": 1, "verses": 1})
        self.assertEqual(self.cli("search", "[", "--mode", "regex").returncode, 2)

    def test_resource(self):
        self.f.write_text(
            json.dumps(
                {
                    "term": "λόγος",
                    "kind": "lexicon",
                    "body": "test",
                    "references": [{"version": "A", "ref": "Jn3:16", "morph": "N"}],
                }
            )
            + "\n"
        )
        study.load(self.db, self.f, "demo", "synthetic", "test")
        self.assertTrue(study.lookup(self.db, "λόγος"))
        self.assertFalse(study.lookup(self.db, "missing"))
        self.assertEqual(
            study.occurrences(self.db, "λόγος", "A", "John", "N"), [(43003016,)]
        )
        self.f.write_text("Gen 1:1 changed")
        with self.assertRaises(ValueError):
            library.install(self.db, self.f, "A", replace=True)


@unittest.skipUnless(
    os.getenv("RCV_FIXTURE"), "set RCV_FIXTURE to the private text file"
)
class RealImport(unittest.TestCase):
    def test_complete_file(self):
        f = Path(os.environ["RCV_FIXTURE"])
        self.assertEqual(f.stat().st_size, 4478035)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "library.db"
            db = library.connect(path)
            self.addCleanup(db.close)
            self.assertEqual(library.install(db, f, "RcV"), (31103, []))
            self.assertEqual(
                db.execute(
                    "SELECT count(distinct k/1000000),count(*) FROM verses"
                ).fetchone(),
                (66, 31103),
            )
            for ref in ("Gen1:1", "Rev22:21"):
                self.assertTrue(list(library.passage(db, "RcV", bounds(ref))))
            data = f.read_bytes()
            expected = []
            for line in data.decode().splitlines():
                ref, text = re.match(r"(.+? \d+:\d+) (.*)", line).groups()
                if re.search(r"\beternal\W+life\b", text, re.IGNORECASE):
                    expected.append(bounds(ref)[0])
            self.assertEqual(
                [k for k, _, _ in library.search(db, ["RcV"], '"eternal life"')],
                sorted(expected),
            )
            actual = subprocess.check_output(
                [sys.executable, str(ROOT / "ui.py"), "export", "RcV"],
                env=dict(os.environ, BVIM_DB=str(path)),
            )
            self.assertEqual(actual, data)


class LayoutTest(unittest.TestCase):
    def test_cells(self):
        from layout import columns, differences, width, wrap

        for n in (3, 7, 19, 60):
            lines = list(wrap("אב שָׁלוֹם 漢字漢字漢字", n))
            self.assertTrue(all(width(s) <= n for s in lines))
        self.assertIn("│", next(columns([("A", "שלום"), ("B", "words")], 80)))
        self.assertEqual(differences("one two", "one three"), "one [-two-] [+three+]")
