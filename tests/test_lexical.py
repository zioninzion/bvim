import curses
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import lexdata
import lexical
import lexpane
import library
import study
import ui
from reader import State, interact
from refs import bounds
from test_reader import Screen

FIXTURES = Path(__file__).parent / "fixtures" / "lexical"
JOHN = bounds("Jn1:1")[0]
GEN = bounds("Gen1:1")[0]
ROM = bounds("Rom8:2")[0]


class LexicalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "library.db"
        self.file = self.path.with_suffix(".txt")
        self.db = library.connect(self.path)
        self.addCleanup(self.db.close)
        for source in ("macula-greek", "macula-hebrew", "macula-sblgnt"):
            self.ingest(source, FIXTURES / (source + ".tsv"))

    def ingest(self, source, path):
        return lexdata.ingest(
            self.db, path, source, lexdata.CATALOG[source], lambda line: None
        )

    def cli(self, *args):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = ui.run(self.db, ui.parser()[0].parse_args(args))
        return code, stream.getvalue()

    def translations(self):
        self.file.write_text(
            "Gen 1:1 example\nMark 1:1 example\nJohn 1:1 first second\nRomans 8:2 example"
        )
        for name in ("A", "B"):
            library.install(self.db, self.file, name)

    def test_attested_greek_and_morphology(self):
        words = lexical.verse(self.db, JOHN)
        self.assertEqual(len(words), 17)
        r = words[4]
        self.assertEqual(
            (r["token_id"], r["surface"], r["lemma"], r["strong"], r["morphology"]),
            ("n43001001005", "Λόγος", "λόγος", ["G3056"], "N-NSM"),
        )
        self.assertEqual(r["parsing"]["case"], "nominative")
        self.assertEqual(r["transliteration"], "logos")
        self.assertEqual(lexical.verse(self.db, ROM)[11]["surface"], "σε")
        row = json.loads(
            self.cli("lex", "John", "1.1", "--word", "5", "--format", "jsonl")[1]
        )
        self.assertEqual(row, r)
        self.assertIn("## John 1:1", self.cli("lex", "Jn1:1", "--format", "md")[1])
        with self.assertRaisesRegex(ValueError, "position"):
            self.cli("lex", "Jn1:1", "--word", "0")
        with self.assertRaisesRegex(ValueError, "No original"):
            self.cli("lex", "Rev1:1")
        with self.assertRaisesRegex(ValueError, "one verse"):
            self.cli("lex", "John", "1")

    def test_missing_corpus_identifies_active_library(self):
        self.cli("data", "remove", "macula-greek")
        self.cli("data", "remove", "macula-sblgnt")
        with self.assertRaises(ValueError) as error:
            self.cli("lex", "John", "1:1")
        self.assertIn(str(self.path.resolve()), str(error.exception))
        self.assertIn("bvim data install macula-greek", str(error.exception))

    def test_hebrew_morphemes_and_extended_keys(self):
        rows = lexical.verse(self.db, GEN)
        self.assertEqual(len(rows), 11)
        self.assertEqual(
            [(r["word_position"], r["strong"]) for r in rows[:2]],
            [(1, ["H871a"]), (1, ["H7225"])],
        )
        self.assertEqual(rows[1]["surface"], "רֵאשִׁ֖ית")
        self.assertEqual(rows[1]["transliteration"], "rēʾšiyṯ")
        self.assertEqual(rows[1]["parsing"]["state"], "absolute")
        self.assertTrue(
            any(not r["surface"] for r in lexical.verse(self.db, bounds("Gen 1:5")[0]))
        )
        self.assertTrue(
            any(
                r["morphology"] == "Sp3ms"
                for r in lexical.verse(self.db, bounds("Gen1:11")[0])
            )
        )
        self.assertFalse(lexical.occurrences(self.db, "H871", scope="Gen1:1"))

    def test_native_reader_commands(self):
        self.translations()
        self.file.write_text(
            'var strongsGreekDictionary = {"G3056":{"lemma":"λόγος","strongs_def":"fixture definition"}};'
        )
        self.ingest("strongs-greek", self.file)
        state = State(self.db, ["A"], "Gen1:1")
        with patch.object(curses, "curs_set"):
            screen = Screen(":lookup G3056\n\n\nq", (24, 80))
            interact(screen, state)
            self.assertEqual(state.k, JOHN)
            self.assertTrue(any("fixture definition" in line for line in screen.output))
            screen = Screen(":occ G3056\n\nq", (24, 80))
            interact(screen, state)
            self.assertEqual(state.k, JOHN)
        screen = Screen("oj\n\x1b\x1b", (24, 80))
        self.assertIsNone(lexpane.show(screen, self.db, JOHN, available=[JOHN]))
        self.assertTrue(any("Romans 8:2 absent" in line for line in screen.output))
        self.assertEqual(lexpane.fit_row("בְּ abc", 2), "בְּ ")
        self.assertEqual(self.cli("morph", "vqp3ms", "--count")[0], 1)

    def test_variants_and_multiple_mappings(self):
        rows = lexical.verse(self.db, bounds("Mk1:1")[0])
        self.assertEqual(
            [r["position"] for r in rows], list(range(1, 8)) + list(range(1, 6))
        )
        self.assertEqual(
            len(lexical.verse(self.db, bounds("Mk1:1")[0], "macula-sblgnt")), 5
        )
        alt = next(
            r
            for r in lexical.verse(self.db, bounds("Judg 9:41")[0])
            if "|" in r["raw_strong"]
        )
        self.assertEqual(set(alt["strong"]), {"H1886a", "H725"})
        compound = next(
            r
            for r in lexical.verse(self.db, bounds("Mk14:31")[0])
            if "+" in r["raw_strong"]
        )
        self.assertEqual(set(compound["strong"]), {"G1537", "G4053"})

    def test_counts_scope_surface_and_normalization(self):
        for term in ("λόγος", "λοΓος", "g03056"):
            self.assertEqual(
                lexical.occurrences(self.db, term, scope="John", count=True), (3, 1)
            )
        self.assertEqual(
            self.cli(
                "occurrences", "G3056", "--in", "NT", "--morph", "N-NSM", "--count"
            ),
            (0, "3 tokens in 1 verse\n"),
        )
        self.assertIn("John 1:1", self.cli("morph", "nominative", "--in", "John")[1])
        self.assertEqual(
            lexical.occurrences(
                self.db, "ראשית", field="normalized", scope="OT", count=True
            ),
            (1, 1),
        )
        self.assertEqual(
            lexical.occurrences(self.db, "Λόγος", field="surface", count=True), (3, 1)
        )
        self.assertEqual(
            lexical.occurrences(self.db, "λογος", field="surface", count=True), (0, 0)
        )
        self.assertEqual(
            self.cli("occurrences", "G3056", "--in", "OT", "--count")[0], 1
        )

    def test_dictionaries_and_atomic_updates(self):
        # Authored mock entry exercises the upstream JS envelope without redistributing the dictionary.
        self.file.write_text(
            'var strongsGreekDictionary = {"G3056":{"lemma":"λόγος","strongs_def":"test definition","translit":"logos"}};'
        )
        self.ingest("strongs-greek", self.file)
        self.assertIn("test definition", self.cli("lookup", "λόγος")[1])
        self.assertIn("test definition", self.cli("lookup", "G3056")[1])
        self.assertEqual(
            lexical.verse(self.db, JOHN)[4]["definitions"][0]["source"], "strongs-greek"
        )
        self.file.write_text('var strongsGreekDictionary = {"G2":{},"G2":{}}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.ingest("strongs-greek", self.file)
        self.assertTrue(lexical.definitions(self.db, "G3056"))
        self.cli("data", "remove", "strongs-greek")
        self.assertFalse(lexical.verse(self.db, JOHN)[4]["definitions"])
        self.ingest("macula-greek", FIXTURES / "macula-greek.tsv")
        self.assertEqual(len(lexical.verse(self.db, JOHN)), 17)
        rows = (FIXTURES / "macula-greek.tsv").read_text().splitlines()
        for bad in (
            rows[:2] + [rows[1]],
            [rows[0], rows[1].replace("MRK ", "BAD ")],
            [""],
        ):
            self.file.write_text("\n".join(bad))
            with self.assertRaises(ValueError):
                self.ingest("macula-greek", self.file)
            self.assertEqual(len(lexical.verse(self.db, JOHN)), 17)
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            lexdata.install(self.db, "macula-greek", self.file)

    def test_alignment_requires_version_and_source_evidence(self):
        self.translations()
        self.assertFalse(lexical.aligned(self.db, "A", JOHN, 1))
        digest = self.db.execute(
            "SELECT digest FROM editions WHERE name='A'"
        ).fetchone()[0]
        mapping = dict(
            source="macula-greek", digest=lexdata.CATALOG["macula-greek"].digest
        )
        ref = dict(
            version="A",
            ref="John 1:1",
            position=1,
            surface="first",
            edition_digest=digest,
            tokens=[dict(mapping, id="n43001001001"), dict(mapping, id="n43001001002")],
        )
        item = dict(
            term="case",
            kind="lexicon",
            body="Synthetic links for validation",
            references=[ref, dict(ref, position=2, surface="second")],
        )
        self.file.write_text(json.dumps(item))
        study.load(self.db, self.file, "links", "unit test", "test")
        self.assertEqual(len(lexical.aligned(self.db, "A", JOHN, 1)), 2)
        self.assertEqual(len(lexical.aligned(self.db, "A", JOHN, 2)), 2)
        self.assertFalse(lexical.aligned(self.db, "B", JOHN, 1))
        ref["edition_digest"] = "wrong"
        self.file.write_text(json.dumps(item))
        with self.assertRaisesRegex(ValueError, "digest"):
            study.load(self.db, self.file, "bad", "test", "test")
        ref["edition_digest"] = digest
        ref["tokens"][0]["id"] = "n45008002001"
        self.file.write_text(json.dumps(item))
        with self.assertRaisesRegex(ValueError, "token ID"):
            study.load(self.db, self.file, "bad", "test", "test")
        self.cli("remove-resource", "links")
        self.assertFalse(lexical.aligned(self.db, "A", JOHN, 1))

    def test_v3_migration_preserves_reader_assets(self):
        self.translations()
        self.db.execute("INSERT INTO marks VALUES('a','A',?)", (JOHN,))
        self.db.execute("INSERT INTO settings VALUES('history','[]')")
        self.db.execute("INSERT INTO resources VALUES('old','fixture','test')")
        self.db.execute(
            "INSERT INTO entries VALUES('old','test','dictionary','definition')"
        )
        self.db.commit()
        self.db.execute("PRAGMA foreign_keys=OFF")
        for (name,) in self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'lex_*'"
        ).fetchall():
            self.db.execute("DROP TABLE " + name)
        self.db.execute("PRAGMA user_version=3")
        self.db.close()
        db = library.connect(self.path)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertEqual(library.search_counts(db, ["A"], "first").hits, 1)
        self.assertEqual(db.execute("SELECT k FROM marks").fetchone()[0], JOHN)
        self.assertEqual(
            db.execute("SELECT value FROM settings WHERE key='history'").fetchone()[0],
            "[]",
        )
        self.assertEqual(study.lookup(db, "test")[0][0], "old")
        self.assertFalse(lexical.verse(db, JOHN))

    def test_pane_state_navigation_and_offline(self):
        self.translations()
        state = State(self.db, ["A", "B"], "John1:1")
        state.scope = "NT"
        state.set_hits(state.find("first"))
        before = (state.k, state.versions, state.hits[:], state.back[:], state.scope)
        with (
            patch.object(curses, "curs_set"),
            patch("urllib.request.urlopen", side_effect=AssertionError),
        ):
            for size in ((24, 100), (8, 33)):
                screen = Screen("Lwwww\n\x1bi/λογος\n?\x1b\x1bq", size)
                interact(screen, state)
                self.assertTrue(any("Λόγος" in s for s in screen.output))
                self.assertEqual(
                    (state.k, state.versions, state.hits, state.back, state.scope),
                    before,
                )
            screen = Screen("Loj\n\x0fq", (24, 80))
            interact(screen, state)
            self.assertEqual(state.k, JOHN)
            self.assertEqual(state.hits, before[2])
            self.assertEqual(state.forward[-1][1], ROM)
            screen = Screen("\t\x1b", (12, 60))
            lexpane.show(screen, self.db, bounds("Mk1:1")[0])
            self.assertTrue(any("macula-sblgnt" in s for s in screen.output))

    def test_lexical_token_and_concordance_navigation_shortcuts(self):
        screen = Screen("Ggg4ju\x12\n\x1b\x1b", (24, 100))
        lexpane.show(screen, self.db, JOHN)
        self.assertTrue(any("n43001001005" in line for line in screen.output))

        screen = Screen("oGggu\n", (24, 100))
        self.assertEqual(lexpane.show(screen, self.db, JOHN), ROM)

    def test_reader_and_concordance_share_scope(self):
        self.translations()
        state = State(self.db, ["A"], "John 1:1")
        keys = ":sc .\nLo:scope OT\n:sc ..\n:scope Rom 8:2\n\nq"
        screen = Screen(keys, (24, 100))
        with patch.object(curses, "curs_set"):
            interact(screen, state)
        for text in (
            "1/1  Scope John",
            "0/0  Scope OT",
            "1/1  Scope John 1",
            "1/1  Scope Rom 8:2",
        ):
            self.assertTrue(any(text in line for line in screen.output), text)
        self.assertEqual(state.k, ROM)
        self.assertEqual(state.scope, "Rom 8:2")

        screen = Screen("o:sc\nj\n", (24, 100))
        target = lexpane.show(
            screen, self.db, JOHN, scope=state.scope, set_scope=state.set_scope
        )
        self.assertEqual(target, ROM)
        self.assertIsNone(state.scope)
        self.assertTrue(any("1/2  Scope all books" in line for line in screen.output))


@unittest.skipUnless(
    os.environ.get("BVIM_LEX_FILES"),
    "set BVIM_LEX_FILES to a directory of pinned upstream files",
)
class FullResources(unittest.TestCase):
    def test_verified_offline_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = library.connect(Path(tmp) / "library.db")
            self.addCleanup(db.close)
            with patch("lexdata.urlopen", side_effect=AssertionError):
                for name, totals in lexdata.TOTALS.items():
                    self.assertEqual(
                        tuple(
                            lexdata.install(
                                db, name, Path(os.environ["BVIM_LEX_FILES"]) / name
                            ).values()
                        ),
                        totals,
                    )
                self.assertEqual(
                    lexical.occurrences(db, "G3056", source="macula-greek", count=True),
                    (331, 318),
                )
                self.assertTrue(
                    lexical.verse(db, GEN)[1]["definitions"][0]["definition"]
                )
                self.assertTrue(lexical.definitions(db, "G3056")[0]["definition"])
