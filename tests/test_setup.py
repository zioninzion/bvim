import hashlib
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import library
import setup_library
import ui
from refs import bounds


class SetupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name)
        self.db = library.connect(self.path / "test.db")
        self.addCleanup(self.db.close)

    def test_download_preserves_xml_coordinates_and_checks_digest(self):
        xml = (
            "<bible>"
            + "".join(
                f'<b id="{book}"><c n="1"><v n="3">Verse &amp; text</v></c></b>'
                for book in setup_library.BOOK_IDS
            )
            + "</bible>"
        ).encode()
        definition = setup_library.TRANSLATIONS["ASV"]._replace(
            digest=hashlib.sha256(xml).hexdigest()
        )
        with patch("setup_library.urlopen", return_value=io.BytesIO(b"bad")):
            with self.assertRaisesRegex(ValueError, "integrity"):
                setup_library.install_translation(self.db, "ASV", definition)
        self.assertFalse(self.db.execute("SELECT name FROM editions").fetchone())
        with patch("setup_library.urlopen", return_value=io.BytesIO(xml)):
            count, _ = setup_library.install_translation(self.db, "ASV", definition)
        self.assertEqual(count, 66)
        self.assertEqual(
            list(library.passage(self.db, "ASV", bounds("Jude 3")))[0][1],
            "Verse & text",
        )
        self.assertEqual(
            self.db.execute("SELECT versification FROM editions").fetchone()[0],
            "thiagobodruk:en_asv",
        )

    def test_first_open_imports_local_file_and_launches_requested_verse(self):
        file = self.path / "local bible.txt"
        file.write_text("John 1:1 demo\n", encoding="utf-8")
        (self.path / "Other.txt").write_text("John 1:1 other\n", encoding="utf-8")
        args = ui.parser()[0].parse_args(["tui", "John", "1:1"])
        with (
            patch("ui.sys.stdin.isatty", return_value=True),
            redirect_stdout(io.StringIO()) as output,
            patch.object(output, "isatty", return_value=True),
            patch("builtins.input", side_effect=["l", "", "1-2", "i", ""]),
            patch("setup_library.Path.cwd", return_value=self.path),
            patch("setup_library.urlopen") as network,
            patch("reader.open_reader") as reader,
        ):
            ui.run(self.db, args)
            reader.assert_called_once_with(self.db, ["local_bible"], "John 1:1")
            self.assertEqual(library.edition(self.db, "Other"), "Other")
            self.assertIn("library setup", output.getvalue())
            self.assertIn("1. local bible.txt", output.getvalue())
            network.assert_not_called()
            with patch("setup_library.run") as setup:
                ui.run(self.db, args)
                setup.assert_not_called()

    def test_optional_resource_selection_and_cancel(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch(
                "builtins.input",
                side_effect=[str(len(setup_library.TRANSLATIONS) + 1), "i", "q"],
            ),
            patch(
                "setup_library.lexdata.install", return_value={"tokens": 3}
            ) as install,
        ):
            self.assertFalse(setup_library.run(self.db))
        install.assert_called_once()
        self.assertEqual(install.call_args.args, (self.db, "macula-greek"))
        self.assertIn("Installed macula-greek (3 tokens)", output.getvalue())

    def test_search_translations_by_abbreviation_or_name(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch(
                "builtins.input",
                side_effect=[
                    "wEb",
                    "2",
                    "American Standard Version",
                    "1",
                    "standard",
                    "",
                    "unlisted",
                    "i",
                    "q",
                ],
            ),
            patch("setup_library.install_translation", return_value=(1, [])) as install,
        ):
            self.assertFalse(setup_library.run(self.db))
        self.assertEqual(
            [call.args[1] for call in install.call_args_list], ["WEB", "ASV"]
        )
        web, _, asv, _, standard = output.getvalue().split("Matching translations")[1:]
        self.assertIn("2. WEB", web)
        self.assertNotIn("1. ASV", web)
        self.assertIn("1. ASV", asv)
        standard_matches = standard.split("\nTranslations")[0]
        self.assertIn("1. ASV", standard_matches)
        self.assertIn("3. BSB", standard_matches)
        self.assertNotIn("2. WEB", standard_matches)
        self.assertIn("No translation matches 'unlisted'", output.getvalue())

    def test_search_finds_king_james_version(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch(
                "builtins.input",
                side_effect=["kjv", "King James Version", "4", "i", "q"],
            ),
            patch("setup_library.install_translation", return_value=(1, [])) as install,
        ):
            self.assertFalse(setup_library.run(self.db))
        install.assert_called_once_with(
            self.db, "KJV", setup_library.TRANSLATIONS["KJV"]
        )
        self.assertEqual(output.getvalue().count("Matching translations"), 3)

    def test_search_finds_esv_for_local_import(self):
        file = self.path / "ESV.txt"
        file.write_text("John 1:1 sample\n", encoding="utf-8")
        output = io.StringIO()
        esv_index = next(
            index
            for index, (name, _) in enumerate(
                setup_library.local_translations(),
                len(setup_library.TRANSLATIONS)
                + len(setup_library.lexdata.CATALOG)
                + 1,
            )
            if name == "ESV"
        )
        with (
            redirect_stdout(output),
            patch(
                "builtins.input",
                side_effect=[
                    "NIV",
                    "",
                    "ESV",
                    "English Standard Version",
                    str(esv_index),
                    str(file),
                    "i",
                    "",
                ],
            ),
            patch("setup_library.urlopen") as network,
        ):
            self.assertTrue(setup_library.run(self.db))
        menu, niv, esv, esv_full, _ = output.getvalue().split("Matching translations")
        self.assertNotIn("English Standard Version", menu)
        self.assertNotIn("New International Version", menu)
        self.assertIn("ASV · American Standard Version", menu)
        self.assertIn("DARBY · Darby Translation", menu)
        self.assertIn("YLT · Young's Literal Translation", menu)
        self.assertIn("NIV · New International Version (local file required)", niv)
        for result in (esv, esv_full):
            self.assertIn(
                "ESV · English Standard Version (local file required)", result
            )
        self.assertEqual(library.edition(self.db), "ESV")
        network.assert_not_called()

    def test_local_globs_and_regex_queue_files_by_stem(self):
        for filename in ("KJV.txt", "RcV(3).txt", "WEB.vpl", "notes.md", "Darby.TXT"):
            (self.path / filename).write_text("John 1:1 sample\n", encoding="utf-8")
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch("setup_library.Path.cwd", return_value=self.path),
            patch(
                "builtins.input",
                side_effect=["l", "*.txt", "l", r"re:^(WEB|Darby)\.", "i", ""],
            ),
            patch("setup_library.urlopen") as network,
        ):
            self.assertTrue(setup_library.run(self.db))
        network.assert_not_called()
        self.assertIn("Selected: KJV, RcV_3, Darby, WEB", output.getvalue())
        self.assertEqual(
            {row[0] for row in self.db.execute("SELECT name FROM editions")},
            {"KJV", "RcV_3", "WEB", "Darby"},
        )

    def test_batch_selection_cancel_and_retry(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch("builtins.input", side_effect=["1,5,6", "5", "q"]),
            patch("setup_library.install_translation") as install,
        ):
            self.assertFalse(setup_library.run(self.db))
            install.assert_not_called()
        self.assertIn("Selected: ASV, YLT", output.getvalue())

        with (
            redirect_stdout(output),
            patch("builtins.input", side_effect=["1 6", "i", "i", "q"]),
            patch(
                "setup_library.install_translation",
                side_effect=[OSError("network unavailable"), (1, []), (1, [])],
            ) as install,
        ):
            self.assertFalse(setup_library.run(self.db))
            self.assertEqual(
                [call.args[1] for call in install.call_args_list], ["ASV", "YLT", "ASV"]
            )
        self.assertIn("Could not install ASV", output.getvalue())

    def test_select_inclusive_number_ranges(self):
        output = io.StringIO()
        with (
            redirect_stdout(output),
            patch("builtins.input", side_effect=["1,6-3", "1-11,5", "q"]),
            patch("setup_library.install_selection") as install,
        ):
            self.assertFalse(setup_library.run(self.db))
            install.assert_not_called()
        self.assertIn("Choose listed numbers or ascending ranges", output.getvalue())
        names = [*setup_library.TRANSLATIONS, *setup_library.lexdata.CATALOG]
        self.assertIn("Selected: " + ", ".join(names[:11]), output.getvalue())
