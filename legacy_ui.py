"""Browse, compare, and search the New Testament in the terminal."""

import argparse
import re
import subprocess
import sys
import webbrowser
from typing import NamedTuple

try:
    import readline  # Enables line editing and history in interactive prompts.
except ImportError:
    pass

from asv_nt import asv
from booknamenum import booknames, booknamesfull, booknumsfix, booknumsfix2
from conc import conc
from nent_b import nent_b
from nestle import nestle
from ngnt import ngnt
from rcv_nt import rcv
from reftolink import ref2bh, ref2lxx, ref2lx, ref2rcv
from reftonum import books2num
from zv import zv


class Verse(NamedTuple):
    book: int
    chapter: int
    number: int

    def __str__(self):
        return f"{booknamesfull[self.book]} {self.chapter}:{self.number}"


class Passage(NamedTuple):
    start: Verse
    end: Verse


VERSIONS = {
    "ZV": zv,
    "RCV": rcv,
    "NENT": nent_b,
    "Conc": conc,
    "ASV": asv,
    "NGNT": ngnt,
    "Nestle": nestle,
}
DEFAULT_VERSIONS = tuple(VERSIONS)
VERSION_NAMES = {name.casefold(): name for name in VERSIONS}
VERSION_NAMES["nent_b"] = "NENT"
LINKS = {
    "re": ref2rcv,
    "rk": ref2rcv,
    "bh": ref2bh,
    "bhp": ref2bh,
    "lx": ref2lx,
    "lxx": ref2lxx,
}
BOOKS = tuple(booknumsfix.values())
CHAPTERS = {book: sorted(chapter for chapter in nent_b[book] if chapter) for book in BOOKS}
VERSE_NUMBERS = {
    (book, chapter): sorted(number for number in nent_b[book][chapter] if number)
    for book in BOOKS
    for chapter in CHAPTERS[book]
}


def book_key(name):
    return re.sub(r"[\s._-]+", "", name).casefold()


BOOK_ALIASES = {name: booknumsfix[number] for name, number in books2num.items()}
BOOK_ALIASES.update({
    book_key(name): book for names in (booknames, booknamesfull) for book, name in names.items()
})
BOOK_REFERENCE = re.compile(r"([1-3]?[ ._-]*[a-z][a-z ._-]*?)[ ._-]*([0-9].*)?", re.I)
VERSE_PAIR = r"([0-9]+)\s*[:._ -]\s*([0-9]+)"
RANGE = re.compile(r"([0-9]+\s*[:._ ]\s*[0-9]+)\s*[-–—]\s*([0-9].*)")


def parse_book(name):
    key = book_key(name)
    if key in BOOK_ALIASES:
        return BOOK_ALIASES[key]
    matches = {book for alias, book in BOOK_ALIASES.items() if alias.startswith(key)}
    if len(key) >= 3 and len(matches) == 1:
        return matches.pop()
    raise ValueError(f"Unknown or ambiguous book {name!r}.")


def parse_verse(book, location, default_chapter=None):
    pair = re.fullmatch(VERSE_PAIR, location)
    if pair:
        chapter, number = map(int, pair.groups())
    elif re.fullmatch(r"[0-9]+", location):
        if default_chapter is not None or len(CHAPTERS[book]) == 1:
            chapter, number = default_chapter or CHAPTERS[book][0], int(location)
        else:
            chapter, number = int(location), 1
    else:
        raise ValueError("Use a reference like John 3:16.")
    verse = Verse(book, chapter, number)
    if number not in VERSE_NUMBERS.get((book, chapter), ()):
        raise ValueError(f"{verse} is outside the available verses.")
    return verse


def parse_passage(reference, current=None):
    reference = reference.strip()
    match = BOOK_REFERENCE.fullmatch(reference)
    if match:
        name, location = match.groups()
        book = parse_book(name)
        location = location or "1"
        default_chapter = None
    elif current is not None and reference[:1].isdigit():
        book, default_chapter = current.book, current.chapter
        location = reference
    else:
        raise ValueError("Use a reference like John 3:16.")

    bounds = RANGE.fullmatch(location)
    if bounds:
        first, last = bounds.groups()
        start = parse_verse(book, first, default_chapter)
        end = parse_verse(book, last, start.chapter)
        if end < start:
            raise ValueError("The end of the passage must follow its start.")
        return Passage(start, end)
    verse = parse_verse(book, location, default_chapter)
    return Passage(verse, verse)


def passage_verses(passage):
    start, end = passage
    for chapter in CHAPTERS[start.book]:
        if start.chapter <= chapter <= end.chapter:
            for number in VERSE_NUMBERS[start.book, chapter]:
                verse = Verse(start.book, chapter, number)
                if start <= verse <= end:
                    yield verse


def move(verse, direction, unit):
    book, chapter, number = verse
    numbers = VERSE_NUMBERS[book, chapter]
    next_number = numbers.index(number) + direction
    if unit == "v" and 0 <= next_number < len(numbers):
        return Verse(book, chapter, numbers[next_number])

    chapters = CHAPTERS[book]
    next_chapter = chapters.index(chapter) + direction
    if unit == "b" or not 0 <= next_chapter < len(chapters):
        book = BOOKS[(BOOKS.index(book) + direction) % len(BOOKS)]
        chapters = CHAPTERS[book]
        next_chapter = 0 if direction == 1 else -1
    chapter = chapters[next_chapter]
    number = VERSE_NUMBERS[book, chapter][0 if direction == 1 else -1]
    return Verse(book, chapter, number)


def parse_versions(selection):
    versions = []
    for name in re.split(r"[\s,]+", selection.strip()):
        version = VERSION_NAMES.get(name.casefold())
        if not version:
            raise ValueError(f"Unknown translation {name!r}. Choose from {', '.join(VERSIONS)}.")
        if version not in versions:
            versions.append(version)
    return tuple(versions)


def verse_text(version, verse):
    book = verse.book if version == "NENT" else booknumsfix2[verse.book]
    return VERSIONS[version].get(book, {}).get(verse.chapter, {}).get(verse.number)


def compose_output(verse, versions=DEFAULT_VERSIONS):
    lines = [f"  {verse}"]
    for version in versions:
        body = verse_text(version, verse)
        if body or version != "ZV" or len(versions) == 1:
            lines.append(f"    {version:<6} {body or '<no verse>'}")
    return "\n".join(lines)


def print_passage(passage, versions):
    for verse in passage_verses(passage):
        print(compose_output(verse, versions), end="\n\n")


def print_search(query, versions, limit):
    query = query.strip().casefold()
    if not query:
        raise ValueError("Enter a word or phrase to search for.")
    count = 0
    for book in BOOKS:
        for chapter in CHAPTERS[book]:
            for number in VERSE_NUMBERS[book, chapter]:
                verse = Verse(book, chapter, number)
                matches = {
                    version: body for version in versions
                    if (body := verse_text(version, verse)) and query in body.casefold()
                }
                if matches:
                    count += 1
                    if count <= limit:
                        names = ", ".join(matches)
                        print(f"  {verse} [{names}] {next(iter(matches.values()))}")
    if count > limit:
        print(f"Showing {limit} of {count} matching verses.")
    elif not count:
        print("No matching verses.")


def open_link(command, verse, previous):
    reference = (booknumsfix2[verse.book] + 39, verse.chapter, verse.number)
    try:
        if command == "hb":
            links = [ref2rcv(*reference)]
            # Holy Bible may ignore a jump within a chapter until another chapter is opened.
            if previous and previous[:2] == verse[:2] and previous != verse:
                other_chapter = 4 if reference[:2] == (55, 3) else 3
                links.insert(0, ref2rcv(55, other_chapter, 2 if other_chapter == 4 else 16))
            for link in links:
                subprocess.run(["open", "-a", "Holy Bible", link], check=True)
        elif not webbrowser.open(LINKS[command](*reference)):
            print("Could not open a browser.")
    except (OSError, subprocess.CalledProcessError, webbrowser.Error) as error:
        print(f"Could not open the link ({error}).")


COMMON_HELP = """  Enter a reference like John 3:16 or John 3:16-4:2.
  search PHRASE searches the selected translations.
  versions LIST selects translations, e.g. versions NENT,NGNT.
  versions shows the current selection. q quits."""
READER_HELP = """  Enter repeats the current direction. f/r moves forward/backward.
  b/c/v changes the navigation unit and moves by book/chapter/verse.
  Enter a verse number or chapter:verse to jump within the current book.
  re/rk opens RCV, hb opens Holy Bible, bh/bhp opens Bible Hub,
  lx opens the lexicon, and lxx opens the Septuagint link.
  e returns to books."""


class Reader:
    def __init__(self, versions, search_limit):
        self.versions = versions
        self.search_limit = search_limit

    def common_command(self, entry, in_reader=False):
        parts = entry.split(maxsplit=1)
        if not parts:
            return False
        command = parts[0].casefold()
        argument = parts[1] if len(parts) == 2 else ""
        if command in {"help", "?"}:
            print(COMMON_HELP)
            if in_reader:
                print(READER_HELP)
        elif command == "versions":
            if argument:
                self.versions = parse_versions(argument)
            print(f"Selected translations: {', '.join(self.versions)}")
            print(f"Available translations: {', '.join(VERSIONS)}")
        elif command == "search":
            print_search(argument, self.versions, self.search_limit)
        else:
            return False
        return True

    def read(self, passage):
        direction = 1
        unit = "v"
        previous = None
        print(READER_HELP)
        print_passage(passage, self.versions)
        while True:
            entry = input("Reader (? for help): ").strip()
            command = entry.casefold()
            if command in {"e", "q"}:
                return command
            current = passage.start
            try:
                versions = self.versions
                if self.common_command(entry, in_reader=True):
                    if self.versions != versions:
                        print_passage(passage, self.versions)
                    continue
                if command in LINKS or command == "hb":
                    open_link(command, current, previous)
                    continue
                if command in {"", "f", "r", "b", "c", "v"}:
                    if command in {"f", "r"}:
                        direction = 1 if command == "f" else -1
                    elif command:
                        unit = command
                    edge = passage.end if direction == 1 else current
                    next_verse = move(edge, direction, unit)
                    passage = Passage(next_verse, next_verse)
                else:
                    passage = parse_passage(entry, current)
                previous = current
                print_passage(passage, self.versions)
            except ValueError as error:
                print(error)

    def browse(self):
        print_books()
        while True:
            entry = input("Book number or reference (? for help, q to quit): ").strip()
            if entry.casefold() == "q":
                return
            try:
                if not entry or entry.casefold() in {"b", "books"}:
                    print_books()
                    continue
                if self.common_command(entry):
                    continue
                if entry.isdecimal():
                    book = booknumsfix.get(int(entry))
                    if book is None:
                        raise ValueError(f"Choose a book from 1 to {len(BOOKS)}.")
                    passage = choose_verse(book)
                    if passage == "q":
                        return
                    if passage is None:
                        print_books()
                        continue
                else:
                    passage = parse_passage(entry)
                if self.read(passage) == "q":
                    return
                print_books()
            except ValueError as error:
                print(error)


def print_books():
    for number, book in booknumsfix.items():
        print(f"  {number:2}  {booknamesfull[book]}")


def choose_number(label, numbers):
    width = len(str(numbers[-1]))
    for start in range(0, len(numbers), 10):
        print("  " + " ".join(f"{number:{width}}" for number in numbers[start:start + 10]))
    while True:
        entry = input(f"{label} (b to go back, q to quit): ").strip().casefold()
        if entry in {"b", "q"}:
            return entry
        if not entry:
            return numbers[0]
        if entry.isdecimal() and int(entry) in numbers:
            return int(entry)
        print(f"Choose an available {label.lower()} number.")


def choose_verse(book):
    while True:
        print(f"\n  {booknamesfull[book]}")
        chapter = choose_number("Chapter", CHAPTERS[book])
        if chapter == "b":
            return None
        if chapter == "q":
            return "q"
        print(f"\n  {booknamesfull[book]} {chapter}")
        number = choose_number("Verse", VERSE_NUMBERS[book, chapter])
        if number == "q":
            return "q"
        if number != "b":
            verse = Verse(book, chapter, number)
            return Passage(verse, verse)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", nargs="*", help="verse or passage, e.g. John 3:16-18")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--print", dest="print_only", action="store_true", help="print the passage and exit")
    mode.add_argument("--search", metavar="PHRASE", help="search selected translations and exit")
    parser.add_argument("--versions", metavar="LIST", help="comma-separated translations to display or search")
    parser.add_argument("--limit", type=int, default=15, help="maximum search results to show (default: 15)")
    args = parser.parse_intermixed_args(argv)

    if args.limit < 1:
        parser.error("--limit must be a positive integer")
    if args.search is not None and args.reference:
        parser.error("--search does not take a reference")
    if args.print_only and not args.reference:
        parser.error("--print requires a reference")

    try:
        versions = parse_versions(args.versions) if args.versions is not None else DEFAULT_VERSIONS
        if args.search is not None:
            print_search(args.search, versions, args.limit)
            return 0
        passage = parse_passage(" ".join(args.reference)) if args.reference else None
    except ValueError as error:
        parser.error(str(error))

    if args.print_only:
        print_passage(passage, versions)
        return 0

    reader = Reader(versions, args.limit)
    try:
        if passage is None or reader.read(passage) != "q":
            reader.browse()
    except (EOFError, KeyboardInterrupt):
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
