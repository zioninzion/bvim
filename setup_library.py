"""Interactive setup and installer for pinned thiagobodruk/bible editions."""

import hashlib
import re
import tempfile
import xml.etree.ElementTree as ET
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NamedTuple, Optional
from urllib.request import urlopen

import lexdata
import library
from refs import names

REVISION = "4c8b8a4a7bd75fee381e1b55523b152191d6a1a5"
UPSTREAM = f"https://raw.githubusercontent.com/thiagobodruk/bible/{REVISION}/xml"

# The collection uses stable Portuguese abbreviations in every language.
BOOK_IDS = dict(
    zip(
        """gn ex lv nm dt js jz rt 1sm 2sm 1rs 2rs 1cr 2cr ed ne et jó sl pv ec ct is jr
    lm ez dn os jl am ob jn mq na hc sf ag zc ml mt mc lc jo atos rm 1co 2co gl ef fp
    cl 1ts 2ts 1tm 2tm tt fm hb tg 1pe 2pe 1jo 2jo 3jo jd ap""".split(),
        names,
    )
)


class Translation(NamedTuple):
    title: str
    filename: str
    digest: str
    rights: str

    @property
    def url(self):
        return f"{UPSTREAM}/{self.filename}.xml"


TRANSLATIONS = {
    "ASV": Translation(
        "American Standard Version (1901)",
        "en_asv",
        "a37d7457c80821f7ec732bbb51ea76e1ebca5436dcb455cb1f0ea47402479d45",
        "Public domain · https://ebible.org/asv/",
    ),
    "WEB": Translation(
        "World English Bible (American Edition)",
        "en_web",
        "2573da0cf0e3e3ab5fa3c1d0a7a58c9a5c81641b123694a244dd3894c3878a0f",
        "Public domain · https://worldenglish.bible/",
    ),
    "BSB": Translation(
        "Berean Standard Bible",
        "en_bsb",
        "d2dc367f695134638a96aecbc17ae6c03bc74462e57534f2efddfa743c4f668e",
        "Public domain · https://berean.bible/licensing.htm",
    ),
    "KJV": Translation(
        "King James Version (Authorized Version)",
        "en_kjv",
        "4b8bef5a075697a0c674a228af85aa137cf18d8dcce4c38d2a0abbb46162be57",
        "Public domain outside the UK · UK Crown rights · https://ebible.org/eng-kjv2006/copr.htm",
    ),
    "DARBY": Translation(
        "Darby Translation (1890)",
        "en_darby",
        "1b007a0172cc1d91f981034d4408e1672da1ee3c3b040af97358f37f7f4e0655",
        "Public domain · https://ebible.org/engDBY/copyright.htm",
    ),
    "YLT": Translation(
        "Young's Literal Translation (1898)",
        "en_ylt98",
        "d73499cfd0264d8a5ed5dbec1870a08de986a399eccee18f18048007921fc065",
        "Public domain · https://ebible.org/engylt/copyright.htm",
    ),
}

DOWNLOAD_FILENAMES = {name: edition.filename for name, edition in TRANSLATIONS.items()}


def local_translations():
    """Read upstream catalog metadata without fetching any Bible text."""
    downloads = set(DOWNLOAD_FILENAMES.values())
    catalog = Path(__file__).with_name("translation_catalog.tsv")
    with catalog.open(encoding="utf-8") as rows:
        for line in rows:
            if line.startswith("#"):
                continue
            filename, title = line.rstrip("\n").split("\t", 1)
            if filename not in downloads:
                yield filename.split("_", 1)[1].upper(), title


def verse_lines(data):
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError(f"Invalid Bible XML: {error}") from error
    if root.tag != "bible":
        raise ValueError("Expected a Bible XML document")
    seen = set()
    for book in root:
        book_id = BOOK_IDS.get(book.get("id"))
        if book.tag != "b" or book_id is None or book_id in seen or not len(book):
            raise ValueError(f"Invalid or duplicate book {book.get('id')!r}")
        seen.add(book_id)
        for chapter in book:
            chapter_number = chapter.get("n", "")
            if (
                chapter.tag != "c"
                or not chapter_number.isascii()
                or not chapter_number.isdecimal()
            ):
                raise ValueError(f"Invalid chapter in {names[book_id]}")
            for verse in chapter:
                number = verse.get("n", "")
                verse_text = verse.text or ""
                if (
                    verse.tag != "v"
                    or len(verse)
                    or not number.isascii()
                    or not number.isdecimal()
                    or not verse_text.strip()
                    or "\n" in verse_text
                    or "\r" in verse_text
                ):
                    raise ValueError(
                        f"Invalid verse in {names[book_id]} {chapter_number}"
                    )
                yield f"{names[book_id]} {chapter_number}:{number} {verse_text}\n"
    if seen != set(names):
        raise ValueError("Expected all 66 canonical books in the downloaded edition")


def install_translation(db, name, edition):
    with urlopen(edition.url, timeout=45) as response:
        data = response.read(8 * 1024 * 1024 + 1)
    if (
        len(data) > 8 * 1024 * 1024
        or hashlib.sha256(data).hexdigest() != edition.digest
    ):
        raise ValueError(f"Download integrity check failed for {name}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "verses.txt"
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.writelines(verse_lines(data))
        return library.install(
            db,
            path,
            name,
            source=edition.url,
            license=edition.rights,
            versification=f"thiagobodruk:{edition.filename}",
        )


class Selection(NamedTuple):
    name: str
    kind: str
    path: Optional[Path] = None


def selected_numbers(answer, available):
    items = re.sub(r"\s*-\s*", "-", answer).replace(",", " ").split()
    numbers = []
    for item in items:
        first, dash, last = item.partition("-")
        last = last if dash else first
        if first not in available or last not in available or int(first) > int(last):
            return []
        for number in range(int(first), int(last) + 1):
            if str(number) not in available:
                return []
            numbers.append(str(number))
    return list(dict.fromkeys(numbers))


def choose_local_files():
    query = input("Path, glob, or re:PATTERN (Enter to browse .txt files): ").strip()
    try:
        if query.startswith("re:"):
            if not query[3:]:
                print("Enter a regular expression after re:.")
                return []
            pattern = re.compile(query[3:])
            matches = pattern.search
        elif query:
            path = Path(query).expanduser()
            if path.is_file():
                return [path]
            if not any(char in query for char in "*?["):
                print(f"File not found: {path}")
                return []
            matches = lambda name: fnmatchcase(name, query)
        else:
            matches = lambda name: name.lower().endswith(".txt")
        files = sorted(
            (
                file
                for file in Path.cwd().iterdir()
                if file.is_file() and matches(file.name)
            ),
            key=lambda file: (file.name.casefold(), file.name),
        )
    except (OSError, re.error) as error:
        print(f"Could not select files: {error}")
        return []
    if not files:
        print("No matching files in the current directory.")
        return []
    if query:
        return files
    by_number = {str(index): file for index, file in enumerate(files, 1)}
    print("Text files in the current directory")
    for number, file in by_number.items():
        print(f"  {number}. {file.name}")
    while True:
        answer = input("File numbers or ranges (Enter to cancel): ").strip()
        if not answer:
            return []
        numbers = selected_numbers(answer, by_number)
        if numbers:
            return [by_number[number] for number in numbers]
        print("Choose listed file numbers or ascending ranges.")


def queue_local_imports(pending, installed):
    for path in choose_local_files():
        name = path.stem
        if not re.fullmatch(r"[\w.-]+", name):
            name = re.sub(r"[^\w.-]+", "_", name).strip("_")
        key = name.casefold(), False
        if not name:
            print(f"Could not derive a translation ID from {path.name}.")
        elif key[0] in installed or key in pending:
            print(
                f"Skipped {path.name}. Translation ID {name} is already installed or selected."
            )
        else:
            pending[key] = Selection(name, "local", path)


def install_selection(db, selection):
    name, kind, path = selection
    if kind == "resource":
        stats = lexdata.install(db, name, progress=lambda line: print(line, flush=True))
        detail = ", ".join(f"{count:,} {key}" for key, count in stats.items() if count)
        print(f"Installed {name} ({detail}).")
        return
    if kind == "local":
        license = (
            "© Crossway · User-supplied file"
            if name.upper() == "ESV"
            else "User supplied"
        )
        count, warnings = library.install(db, path, name, license=license)
    else:
        print(f"Downloading {name} …", flush=True)
        count, warnings = install_translation(db, name, TRANSLATIONS[name])
    print(
        f"Installed {name} with {count:,} verses and {len(warnings)} validation warnings."
    )


def run(db):
    """Offer explicitly selected installs. Return whether the user finished setup."""
    print("\nbvim library setup")
    print(
        "Catalog downloads use thiagobodruk/bible verse numbering, which can differ from print editions."
    )
    matching = None
    pending = {}
    local_catalog = tuple(local_translations())
    try:
        while True:
            installed_editions = {
                name.casefold() for (name,) in db.execute("SELECT name FROM editions")
            }
            installed_resources = {
                name for (name,) in db.execute("SELECT name FROM lex_sources")
            }
            choices = (
                [
                    (
                        name,
                        edition.title,
                        "translation",
                        name.casefold() in installed_editions,
                    )
                    for name, edition in TRANSLATIONS.items()
                ]
                + [
                    (name, resource.edition, "resource", name in installed_resources)
                    for name, resource in lexdata.CATALOG.items()
                ]
                + [
                    (name, title, "local", name.casefold() in installed_editions)
                    for name, title in local_catalog
                ]
            )
            visible = {
                str(index): choice
                for index, choice in enumerate(choices, 1)
                if (matching is None and choice[2] != "local")
                or (
                    matching is not None
                    and choice[0] in matching
                    and choice[2] != "resource"
                )
            }
            print("\nTranslations" if matching is None else "\nMatching translations")
            for index, (name, title, kind, installed) in visible.items():
                if kind == "resource" and index == str(len(TRANSLATIONS) + 1):
                    print("\nOptional offline study resources")
                suffix = (
                    " (installed)"
                    if installed
                    else " (selected)"
                    if (name.casefold(), kind == "resource") in pending
                    else " (local file required)"
                    if kind == "local"
                    else ""
                )
                print(f"  {index}. {name} · {title}{suffix}")
            print("  l. Select local verse-per-line files")
            if pending:
                print("Selected: " + ", ".join(item.name for item in pending.values()))
                print("  i. Install selections    c. Clear selections")
            ready = bool(installed_editions)
            enter_hint = (
                "Enter for main menu, "
                if matching is not None
                else "Enter to finish, "
                if ready and not pending
                else ""
            )
            answer = (
                input(
                    "Numbers or ranges (e.g. 1-3,5), translation name, l for local file, "
                    + enter_hint
                    + "or q to quit: "
                )
                .strip()
                .casefold()
            )
            if answer == "q":
                return False
            if not answer:
                if matching is not None:
                    matching = None
                elif pending:
                    print("Press i to install the selected items.")
                elif ready:
                    return True
                continue
            if answer == "i":
                if not pending:
                    print("Select items to install first.")
                for key, item in list(pending.items()):
                    try:
                        install_selection(db, item)
                    except (ValueError, OSError) as error:
                        print(f"Could not install {item.name}: {error}")
                    else:
                        del pending[key]
                matching = None
                continue
            if answer == "c":
                pending.clear()
                continue
            if answer == "l":
                queue_local_imports(pending, installed_editions)
                continue
            if re.fullmatch(r"[0-9,\s-]+", answer):
                numbers = selected_numbers(answer, visible)
                if not numbers:
                    print(
                        "Choose listed numbers or ascending ranges of listed numbers."
                    )
                    continue
                for number in numbers:
                    name, _, kind, installed = visible[number]
                    key = name.casefold(), kind == "resource"
                    if installed:
                        print(f"{name} is already installed.")
                    elif key in pending:
                        del pending[key]
                    elif kind == "local":
                        queue_local_imports(pending, installed_editions)
                    else:
                        pending[key] = Selection(name, kind)
                continue
            words = answer.split()
            matching = {
                name
                for name, title, kind, _ in choices
                if kind != "resource"
                if all(
                    word
                    in f"{name} {title} {DOWNLOAD_FILENAMES.get(name, '')}".casefold()
                    for word in words
                )
            }
            if not matching:
                print(f"No translation matches {answer!r}.")
                matching = None
    except EOFError:
        return False
