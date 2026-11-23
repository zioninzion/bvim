"""Pinned, checksummed source acquisition and transactional original-language import."""

import csv
import hashlib
import json
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple
from urllib.request import urlopen

from lexical import fold, number
from refs import loc


class Resource(NamedTuple):
    revision: str
    url: str
    digest: str
    license: str
    attribution: str
    edition: str


GREEK = "8423afe47b9e8f24b7772e808af45c7159a6fe7e"
HEBREW = "47db250bd55d0d8577f2a94fba114ef16c35b23c"
STRONGS = "0acd2f251c2d35ff8db2dece4e0593979d3ac223"
CATALOG = {
    "macula-greek": Resource(
        GREEK,
        f"https://raw.githubusercontent.com/Clear-Bible/macula-greek/{GREEK}/Nestle1904/tsv/macula-greek-Nestle1904.tsv",
        "c7cf33b8273c0f549e3582d1610603c86210c18e1f245bb80a69281622385fa5",
        "CC BY 4.0",
        "MACULA Greek Linguistic Datasets, Biblica and contributors; Nestle 1904",
        "Nestle 1904",
    ),
    "macula-sblgnt": Resource(
        GREEK,
        f"https://raw.githubusercontent.com/Clear-Bible/macula-greek/{GREEK}/SBLGNT/tsv/macula-greek-SBLGNT.tsv",
        "7f71504fdee8659bdd9f85342e4103d645864c2851b8205915bb298f0c004cc5",
        "CC BY 4.0",
        "MACULA Greek Linguistic Datasets, Biblica and contributors; SBL Greek New Testament © 2010 Society of Biblical Literature and Logos Bible Software",
        "SBLGNT",
    ),
    "macula-hebrew": Resource(
        HEBREW,
        f"https://media.githubusercontent.com/media/Clear-Bible/macula-hebrew/{HEBREW}/WLC/tsv/macula-hebrew.tsv",
        "965cb0599beed2fe31283b615bcc369178141c0e718a66d97518d94309cfc124",
        "CC BY 4.0 (linguistic annotations); WLC text",
        "MACULA Hebrew Linguistic Datasets, Biblica; WLC, OSHB, Groves Center, Cherith",
        "WLC",
    ),
}
for lang, digest, credit in [
    (
        "greek",
        "7624ee738ae47e80f1a352223e28a26d011c9cd4898822cee52f47a010c04efd",
        "Ulrik Petersen",
    ),
    (
        "hebrew",
        "5ce6aeed551c709f49bcfa341cadf2f34bc7599b85d9de9e6ac2ecbf60fc3739",
        "David Instone-Brewer and David Troidl",
    ),
]:
    CATALOG["strongs-" + lang] = Resource(
        STRONGS,
        f"https://raw.githubusercontent.com/openscriptures/strongs/{STRONGS}/{lang}/strongs-{lang}-dictionary.js",
        digest,
        "CC-BY-SA (version unspecified in file header)",
        f"James Strong; Open Scriptures; {credit}",
        "Strong's " + lang.title(),
    )

TOTALS = {
    "macula-greek": (7943, 137779, 5401, 0),
    "macula-sblgnt": (7939, 137741, 5518, 0),
    "macula-hebrew": (23213, 475911, 8457, 0),
    "strongs-greek": (0, 0, 0, 5523),
    "strongs-hebrew": (0, 0, 0, 8674),
}

BOOKS = {
    s: i
    for i, s in enumerate(
        """GEN EXO LEV NUM DEU JOS JDG RUT 1SA 2SA 1KI 2KI 1CH 2CH
 EZR NEH EST JOB PSA PRO ECC SNG ISA JER LAM EZK DAN HOS JOL AMO OBA JON MIC NAM HAB ZEP HAG ZEC MAL
 MAT MRK LUK JHN ACT ROM 1CO 2CO GAL EPH PHP COL 1TH 2TH 1TI 2TI TIT PHM HEB JAS 1PE 2PE 1JN 2JN 3JN JUD REV""".split(),
        1,
    )
}
GREEK_POS = dict(
    adj="adjective",
    adv="adverb",
    conj="conjunction",
    det="determiner",
    intj="interjection",
    num="numeral",
    prep="preposition",
    pron="pronoun",
    ptcl="particle",
)
REFERENCE = re.compile(r"(\w+) (\d+):(\d+)!(\d+)")
GREEK_LETTERS = dict(
    zip(
        "αβγδεζηθικλμνξοπρσςτυφχψω",
        "a b g d e z ē th i k l m n x o p r s s t y ph ch ps ō".split(),
    )
)


@lru_cache(8192)
def romanize(text):
    """Simple orthographic romanization. Breathing marks apply to the initial vowel group."""
    s = unicodedata.normalize("NFD", text.lower())
    letters = [c for c in s if not unicodedata.combining(c) or c == "\u0345"]
    result = []
    for i, c in enumerate(letters):
        if c == "γ" and letters[i + 1 : i + 2] in (["γ"], ["κ"], ["χ"], ["ξ"]):
            result.append("n")
        elif c == "υ" and i and letters[i - 1] in "αεηο" and "\u0308" not in s:
            result.append("u")
        elif c == "\u0345":
            result.append("i")
        else:
            result.append(GREEK_LETTERS.get(c, c))
    out = "".join(result)
    if "\u0314" in s:
        out = ("rh" + out[1:]) if out.startswith("r") else "h" + out
    return out


def import_tokens(db, path, source, progress):
    greek = source != "macula-hebrew"
    lemmas, grammars = {}, {}
    prev = None
    categories = (
        "type",
        "stem",
        "person",
        "case",
        "gender",
        "number",
        "state",
        "tense",
        "voice",
        "mood",
        "degree",
    )
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t", quoting=csv.QUOTE_NONE)
        for i, row in enumerate(reader, 1):
            try:
                ref, token_id = row["ref"], row["xml:id"]
                match = REFERENCE.fullmatch(ref)
                if not match or match[1] not in BOOKS or not token_id:
                    raise ValueError(f"unmapped reference or token ID {ref!r}")
                k = loc(BOOKS[match[1]], int(match[2]), int(match[3]))
                if k != prev:
                    db.execute(
                        "INSERT INTO lex_verses VALUES(?,?,?)",
                        (source, k, ref.split("!")[0]),
                    )
                    prev, position = k, 0
                position += 1
                surface, lemma, code = row["text"], row["lemma"], row["morph"]
                if (
                    not lemma
                    or not code
                    or (greek and not surface)
                    or None in row
                    or None in row.values()
                ):
                    raise ValueError("incomplete token")
                if lemma not in lemmas:
                    lemmas[lemma] = db.execute(
                        "INSERT INTO lex_lemmas(source,lemma,folded) VALUES(?,?,?)",
                        (source, lemma, fold(lemma)),
                    ).lastrowid
                attrs = {"part_of_speech": row["class"] if greek else row["pos"]}
                if greek:
                    attrs["part_of_speech"] = GREEK_POS.get(
                        attrs["part_of_speech"], attrs["part_of_speech"]
                    )
                attrs.update({key: row[key] for key in categories if row.get(key)})
                key = (code, tuple(attrs.items()))
                if key not in grammars:
                    gid = db.execute(
                        "INSERT INTO lex_grammar(source,code,parsing) VALUES(?,?,?)",
                        (source, code, json.dumps(attrs, ensure_ascii=False)),
                    ).lastrowid
                    grammars[key] = gid
                    db.executemany(
                        "INSERT INTO lex_categories VALUES(?,?)",
                        ((v.casefold(), gid) for v in set(attrs.values()) if v),
                    )
                raw = row["strong"] if greek else row["strongnumberx"]
                tid = db.execute(
                    """INSERT INTO lex_tokens(source,k,token_id,position,word_position,surface,folded,
                    transliteration,lemma_id,grammar,gloss,punctuation,raw_strong,language) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        source,
                        k,
                        token_id,
                        position,
                        int(match[4]),
                        surface,
                        fold(row.get("normalized") or surface),
                        romanize(surface) if greek else row["transliteration"],
                        lemmas[lemma],
                        grammars[key],
                        row["gloss"],
                        row["after"],
                        raw,
                        "Greek"
                        if greek
                        else {"H": "Hebrew", "A": "Aramaic"}.get(
                            row["lang"], row["lang"]
                        ),
                    ),
                ).lastrowid
                for component in dict.fromkeys(re.split(r"[+|]", raw) if raw else []):
                    strong = number(("G" if greek else "H") + component)
                    if not strong:
                        raise ValueError(f"invalid Strong's mapping {raw}")
                    db.execute("INSERT INTO lex_numbers VALUES(?,?)", (tid, strong))
            except (ValueError, KeyError, sqlite3.IntegrityError) as e:
                raise ValueError(f"{source} TSV line {i + 1}: {e}") from e
            if i % 50000 == 0:
                progress(f"{source}: {i:,} tokens")
    if prev is None:
        raise ValueError("Empty MACULA file")


def unique_pairs(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("Duplicate dictionary key")
    return result


def import_definitions(db, path, source):
    text = Path(path).read_text(encoding="utf8")
    _, sep, data = text.partition("Dictionary = ")
    if not sep:
        raise ValueError("Missing Open Scriptures dictionary assignment")
    entries, _ = json.JSONDecoder(object_pairs_hook=unique_pairs).raw_decode(
        data.lstrip()
    )
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Empty dictionary")
    prefix = "G" if source.endswith("greek") else "H"
    for strong, d in entries.items():
        if (
            number(strong) != strong
            or not isinstance(d, dict)
            or not strong.startswith(prefix)
            or not isinstance(d.get("lemma"), str)
            or any(not isinstance(value, str) for value in d.values())
        ):
            raise ValueError(f"Malformed dictionary entry {strong}")
        db.execute(
            "INSERT INTO lex_definitions VALUES(?,?,?,?,?,?,?,?)",
            (
                source,
                strong,
                d["lemma"],
                fold(d["lemma"]),
                d.get("translit", d.get("xlit", "")),
                d.get("strongs_def", ""),
                d.get("derivation", ""),
                d.get("kjv_def", ""),
            ),
        )


def counts(db, source):
    return {
        name: db.execute(
            "SELECT count(*) FROM lex_" + name + " WHERE source=?", (source,)
        ).fetchone()[0]
        for name in ("verses", "tokens", "lemmas", "definitions")
    }


def ingest(db, path, source, meta, progress, expected=None):
    with db:
        db.execute("BEGIN IMMEDIATE")
        # Alignments attest these specific source bytes and IDs. Avoid silently discarding them.
        if db.execute(
            "SELECT 1 FROM lex_alignments a JOIN lex_tokens t ON t.id=a.token WHERE t.source=? LIMIT 1",
            (source,),
        ).fetchone():
            if db.execute(
                "SELECT digest FROM lex_sources WHERE name=?", (source,)
            ).fetchone() == (meta.digest,):
                return counts(db, source)
            raise ValueError(
                "Remove associated alignment resources before replacing the token source"
            )
        db.execute("DELETE FROM lex_sources WHERE name=?", (source,))
        db.execute("INSERT INTO lex_sources VALUES(?,?,?,?,?,?,?)", (source, *meta))
        if source.startswith("macula-"):
            import_tokens(db, path, source, progress)
        else:
            import_definitions(db, path, source)
        stats = counts(db, source)
        if expected and tuple(stats.values()) != expected:
            raise ValueError(f"Unexpected coverage for {source}: {stats}")
        return stats


def install(db, source, path=None, progress=lambda message: None):
    meta = CATALOG[source]
    # Hash and import the same private copy even when the supplied path changes.
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "resource"
        progress(f"Reading {path or meta.url}")
        with (
            open(path, "rb") if path else urlopen(meta.url, timeout=90) as incoming,
            staged.open("wb") as out,
        ):
            shutil.copyfileobj(incoming, out, 1024 * 1024)
        sha = hashlib.sha256()
        with staged.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(block)
        if sha.hexdigest() != meta.digest:
            raise ValueError(f"SHA-256 mismatch for {source}")
        return ingest(db, staged, source, meta, progress, expected=TOTALS[source])
