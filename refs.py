"""Canonical Protestant book IDs, reference syntax and ranked suggestions."""

import difflib
import re
from functools import lru_cache

BOOKS = """Genesis|Gen Gn
Exodus|Exo Ex
Leviticus|Lev Lv
Numbers|Num Nm
Deuteronomy|Deut Dt
Joshua|Josh Jos
Judges|Judg Jdg
Ruth|Ru
1 Samuel|1Sam 1Sa
2 Samuel|2Sam 2Sa
1 Kings|1Kgs 1Ki
2 Kings|2Kgs 2Ki
1 Chronicles|1Chron 1Chr 1Ch
2 Chronicles|2Chron 2Chr 2Ch
Ezra|Ezr
Nehemiah|Neh
Esther|Esth Est
Job|
Psalms|Ps Psa Psalm
Proverbs|Prov Pr
Ecclesiastes|Eccl Ecc
Song of Songs|SS SOS Song Canticles SongOfSolomon
Isaiah|Isa Is
Jeremiah|Jer
Lamentations|Lam
Ezekiel|Ezek Eze
Daniel|Dan
Hosea|Hos
Joel|
Amos|Am
Obadiah|Oba Ob
Jonah|Jon
Micah|Mic
Nahum|Nah
Habakkuk|Hab
Zephaniah|Zeph
Haggai|Hag
Zechariah|Zech
Malachi|Mal
Matthew|Matt Mt
Mark|Mk
Luke|Lk
John|Jn Jhn
Acts|Ac
Romans|Rom Ro
1 Corinthians|1Cor 1Co
2 Corinthians|2Cor 2Co
Galatians|Gal
Ephesians|Eph
Philippians|Phil Php
Colossians|Col
1 Thessalonians|1Thess 1Thes 1Th
2 Thessalonians|2Thess 2Thes 2Th
1 Timothy|1Tim 1Ti
2 Timothy|2Tim 2Ti
Titus|Tit
Philemon|Philem Phm
Hebrews|Heb
James|Jas
1 Peter|1Pet 1Pe
2 Peter|2Pet 2Pe
1 John|1Jn 1Jhn
2 John|2Jn 2Jhn
3 John|3Jn 3Jhn
Jude|Jud
Revelation|Rev Re""".splitlines()

SINGLE_CHAPTER_BOOKS = {31, 57, 63, 64, 65}


def key(name):
    return re.sub(r"[.\s_-]", "", name.casefold())


names = {}
aliases = {}
for i, line in enumerate(BOOKS, 1):
    name, short = line.split("|")
    names[i] = name
    for alias in [name, *short.split()]:
        aliases[key(alias)] = i


def choices(name):
    query = key(name)
    prefix = [i for alias, i in aliases.items() if alias.startswith(query)]
    fuzzy = [aliases[a] for a in difflib.get_close_matches(query, aliases, 8)]
    return list(dict.fromkeys(prefix + fuzzy))


@lru_cache(256)
def book(name):
    query = key(name)
    if query in aliases:
        return aliases[query]
    matches = {i for alias, i in aliases.items() if alias.startswith(query)}
    if len(matches) == 1 and query:
        return matches.pop()
    raise ValueError(
        f"Unknown or ambiguous book {name!r}. Suggestions: "
        + ", ".join(names[i] for i in choices(name)[:8])
    )


def loc(b, c, v):
    if not (0 <= c <= 999 and 0 <= v <= 999):
        raise ValueError("Chapter and verse must fit 0–999")
    return b * 1000000 + c * 1000 + v


def parts(k):
    return k // 1000000, k // 1000 % 1000, k % 1000


def label(k):
    b, c, v = parts(k)
    return f"{names[b]} {c}:{v}"


def scope_reference(value, k):
    b, c, _ = parts(k)
    chapter = names[b] if b in SINGLE_CHAPTER_BOOKS else f"{names[b]} {c}"
    shorthand = {".": names[b], "..": chapter}
    return ";".join(
        shorthand.get(part.strip(), part.strip()) for part in value.split(";")
    )


def normalize_reference(s):
    """Expand a trailing chapter, verse, and optional end verse written with spaces."""
    match = re.fullmatch(
        r"([1-3]?\s*[A-Za-z][A-Za-z ._-]*?\s*)(\d+)\s+(\d+)(?:\s+(\d+))?", s.strip()
    )
    if match is None:
        return s.strip()
    book_name, chapter, verse, end = match.groups()
    return f"{book_name}{chapter}:{verse}" + (f"-{end}" if end else "")


def bounds(s):
    s = normalize_reference(s)
    pair = re.fullmatch(r"(.+?\d)\s*[-–—]\s*([1-3]?\s*[A-Za-z].+)", s.strip())
    if pair:
        first = bounds(pair[1])[0]
        last = bounds(pair[2])[1]
        if last < first:
            raise ValueError("Reversed passage")
        return first, last
    m = re.fullmatch(
        r"([1-3]?\s*[A-Za-z][A-Za-z ._-]*?)\s*(?:(\d+)(?:\s*[:.]\s*(\d+)(?:\s*[-–—]\s*(?:(\d+)\s*[:.]\s*)?(\d+))?|\s*[-–—]\s*(\d+))?)?",
        s.strip(),
    )
    if not m:
        raise ValueError(f"Invalid reference {s!r}. Try John 3:16-4:2.")
    name, c, v, ec, ev, short_end = m.groups()
    b = book(name)
    if c and v is None and b in SINGLE_CHAPTER_BOOKS:
        c, v, ev = "1", c, short_end
    elif short_end:
        raise ValueError(f"Specify a chapter and verse for {names[b]} ranges")
    first = loc(b, int(c or 0), int(v or 0))
    last = loc(b, int(ec or c or 999), int(ev or v or 999))
    if last < first:
        raise ValueError("Reversed passage")
    return first, last


def search_ranges(query):
    """Recognize reference lists while leaving bare words and FTS expressions alone."""
    query = query.strip()
    explicit = query.lower().startswith("ref:")
    if explicit:
        query = query[4:].strip()
    fields = re.split(r"([,;])", query)
    first = fields[0].strip()
    if not explicit:
        if not re.match(r"^[1-3]?\s*[A-Za-z][A-Za-z ._-]*?\s*\d", first):
            return None
        if not re.search(r"\d\s*[:.]\s*\d", first):
            try:
                bounds(first)
            except ValueError:
                return None
    ranges = [bounds(first)]
    for sep, field in zip(fields[1::2], fields[2::2]):
        field = field.strip()
        if re.match(r"^\d+(?:\s*[:.\-–—]|$)", field):
            b, c, v = parts(ranges[-1][1])
            relative_verse = (
                sep == "," and v != 999 and not re.search(r"[:.]", field.split("-")[0])
            )
            field = (
                f"{names[b]} {c}:{field}" if relative_verse else f"{names[b]} {field}"
            )
        ranges.append(bounds(field))
    return ranges


def launch_target(value):
    """Resolve one passage, or return a query for the search results browser."""
    try:
        return bounds(value), ""
    except ValueError:
        pass
    if value.lower().startswith("ref:"):
        return None, value
    query = value
    if not re.search("[,;]", value):
        # Accept adjacent complete references such as "Mat 3:5 1 Cor 14:26".
        refs = []
        start = 0
        for gap in re.finditer(r"(?<=\d)\s+(?=(?:[1-3]\s*)?[A-Za-z])", value):
            candidate = value[start : gap.start()]
            try:
                bounds(candidate)
            except ValueError:
                continue
            refs.append(candidate)
            start = gap.end()
        if refs:
            query = "; ".join([*refs, value[start:]])
    if "," in query or ";" in query:
        try:
            search_ranges("ref:" + query)
            return None, query if search_ranges(query) else "ref:" + query
        except ValueError:
            pass
    return None, value
