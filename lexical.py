"""Offline queries over source-identified, ordered original-language tokens."""

import json
import re
import unicodedata
from functools import lru_cache

from refs import label

SCHEMA = """
CREATE TABLE IF NOT EXISTS lex_sources(
 name TEXT PRIMARY KEY, revision TEXT NOT NULL, url TEXT NOT NULL, digest TEXT NOT NULL,
 license TEXT NOT NULL, attribution TEXT NOT NULL, edition TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lex_verses(
 source TEXT REFERENCES lex_sources ON DELETE CASCADE, k INTEGER, ref TEXT NOT NULL,
 PRIMARY KEY(source,k));
CREATE INDEX IF NOT EXISTS lx_verse ON lex_verses(k,source);
CREATE TABLE IF NOT EXISTS lex_lemmas(
 id INTEGER PRIMARY KEY, source TEXT REFERENCES lex_sources ON DELETE CASCADE,
 lemma TEXT NOT NULL, folded TEXT NOT NULL, UNIQUE(source,lemma));
CREATE INDEX IF NOT EXISTS lx_lemma ON lex_lemmas(folded);
CREATE TABLE IF NOT EXISTS lex_grammar(
 id INTEGER PRIMARY KEY, source TEXT REFERENCES lex_sources ON DELETE CASCADE,
 code TEXT NOT NULL, parsing TEXT NOT NULL, UNIQUE(source,code,parsing));
CREATE INDEX IF NOT EXISTS lx_code ON lex_grammar(code COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS lex_categories(
 category TEXT, grammar INTEGER REFERENCES lex_grammar ON DELETE CASCADE,
 PRIMARY KEY(category,grammar));
CREATE TABLE IF NOT EXISTS lex_tokens(
 id INTEGER PRIMARY KEY, source TEXT, k INTEGER, token_id TEXT NOT NULL,
 position INTEGER NOT NULL, word_position INTEGER NOT NULL, surface TEXT NOT NULL,
 folded TEXT NOT NULL, transliteration TEXT NOT NULL, lemma_id INTEGER REFERENCES lex_lemmas,
 grammar INTEGER REFERENCES lex_grammar, gloss TEXT NOT NULL, punctuation TEXT NOT NULL,
 raw_strong TEXT NOT NULL, language TEXT NOT NULL,
 FOREIGN KEY(source,k) REFERENCES lex_verses ON DELETE CASCADE,
 UNIQUE(source,k,position), UNIQUE(source,token_id));
CREATE INDEX IF NOT EXISTS lx_token_lemma ON lex_tokens(lemma_id,k,position);
CREATE INDEX IF NOT EXISTS lx_token_morph ON lex_tokens(grammar,k);
CREATE INDEX IF NOT EXISTS lx_surface ON lex_tokens(surface);
CREATE INDEX IF NOT EXISTS lx_folded ON lex_tokens(folded);
CREATE TABLE IF NOT EXISTS lex_numbers(
 token INTEGER REFERENCES lex_tokens ON DELETE CASCADE, number TEXT,
 PRIMARY KEY(token,number));
CREATE INDEX IF NOT EXISTS lx_number ON lex_numbers(number,token);
CREATE TABLE IF NOT EXISTS lex_definitions(
 source TEXT REFERENCES lex_sources ON DELETE CASCADE, strong TEXT, lemma TEXT,
 folded TEXT, transliteration TEXT, definition TEXT, derivation TEXT, kjv TEXT,
 PRIMARY KEY(source,strong));
CREATE INDEX IF NOT EXISTS lx_definition ON lex_definitions(strong);
CREATE INDEX IF NOT EXISTS lx_headword ON lex_definitions(folded);
CREATE TABLE IF NOT EXISTS lex_alignments(
 resource TEXT REFERENCES resources ON DELETE CASCADE, version TEXT COLLATE NOCASE REFERENCES editions ON DELETE CASCADE,
 digest TEXT NOT NULL, k INTEGER, position INTEGER, surface TEXT NOT NULL,
 token INTEGER REFERENCES lex_tokens ON DELETE CASCADE,
 PRIMARY KEY(resource,version,k,position,token));
CREATE INDEX IF NOT EXISTS lx_alignment_token ON lex_alignments(token);
CREATE INDEX IF NOT EXISTS lx_alignment ON lex_alignments(version,k,position);
"""


@lru_cache(8192)
def fold(text):
    return "".join(
        c
        for c in unicodedata.normalize("NFD", text.casefold())
        if unicodedata.category(c) != "Mn"
    )


def iter_records(cursor):
    keys = [col[0] for col in cursor.description]
    return (dict(zip(keys, row)) for row in cursor)


def records(cursor):
    return list(iter_records(cursor))


def number(term):
    m = re.fullmatch(r"([GH])0*(\d+)([a-z]?)", term, re.IGNORECASE)
    return m[1].upper() + str(int(m[2])) + m[3].lower() if m else None


DEF_FIELDS = "source,strong,lemma,transliteration,definition,derivation,kjv"


def missing_verse(db, k, source=None):
    path = db.execute("PRAGMA database_list").fetchone()[2] or "in-memory library"
    default_sources = (
        ("macula-greek", "macula-sblgnt") if k >= 40000000 else ("macula-hebrew",)
    )
    candidates = (source,) if source else default_sources
    if not any(
        db.execute(
            "SELECT 1 FROM lex_verses WHERE source=? LIMIT 1", (name,)
        ).fetchone()
        for name in candidates
    ):
        from lexdata import CATALOG

        if candidates[0] in CATALOG:
            hint = f"Install the source in this library with `bvim data install {candidates[0]}`."
        else:
            hint = f"Source {source!r} is unavailable. See `bvim data list`."
    else:
        hint = "Check the source edition’s verse numbering or choose another source."
    return f"No original-language verse at {label(k)} in {path}. {hint}"


def definitions(db, term):
    strong = number(term)
    condition = (
        "strong=?"
        if strong
        else """(folded=? OR strong IN (
        SELECT n.number FROM lex_lemmas l JOIN lex_tokens t ON t.lemma_id=l.id
        JOIN lex_numbers n ON n.token=t.id WHERE l.folded=?))"""
    )
    params = (strong,) if strong else (fold(term), fold(term))
    return records(
        db.execute(
            f"SELECT {DEF_FIELDS} FROM lex_definitions WHERE {condition} ORDER BY source,strong",
            params,
        )
    )


def verse(db, k, source=None):
    kw = (source,) if source else ()
    sql = """SELECT t.id,t.source,v.ref AS source_reference,t.token_id,t.position,t.word_position,
        t.surface,t.transliteration,l.lemma,g.code AS morphology,g.parsing,t.gloss,
        t.punctuation,t.raw_strong,t.language FROM lex_verses v JOIN lex_tokens t
        ON t.source=v.source AND t.k=v.k JOIN lex_lemmas l ON l.id=t.lemma_id
        JOIN lex_grammar g ON g.id=t.grammar WHERE v.k=?"""
    rows = records(
        db.execute(
            sql
            + (" AND v.source=?" if source else "")
            + " ORDER BY v.source,t.position",
            (k, *kw),
        )
    )
    if not rows:
        return []
    tokens = {}
    for row in rows:
        tokens[row.pop("id")] = row
        row.update(reference=label(k), strong=[], definitions=[])
        row["parsing"] = json.loads(row["parsing"])
    ids = list(tokens)
    for start in range(0, len(ids), 400):
        batch = ids[start : start + 400]
        cur = db.execute(
            """SELECT n.token,n.number,d."""
            + DEF_FIELDS.replace(",", ",d.")
            + " FROM lex_numbers n LEFT JOIN lex_definitions d ON d.strong=n.number WHERE n.token IN ("
            + ",".join("?" for _ in batch)
            + ") ORDER BY n.token,n.number,d.source",
            batch,
        )
        for token, strong, *entry in cur:
            row = tokens[token]
            if strong not in row["strong"]:
                row["strong"].append(strong)
            if entry[0]:
                row["definitions"].append(dict(zip(DEF_FIELDS.split(","), entry)))
    return rows


def occurrences(
    db,
    term,
    *,
    field="auto",
    scope=None,
    morph=None,
    source=None,
    count=False,
    stream=False,
):
    """One row per attested token. Identical locations from distinct editions stay separate."""
    from library import scopes

    fields = {
        "strong": ("JOIN lex_numbers n ON n.token=t.id", "n.number=?", number(term)),
        "surface": ("", "t.surface=?", term),
        "normalized": ("", "t.folded=?", fold(term)),
        "lemma": ("", "l.folded=?", fold(term)),
        "exact-lemma": ("", "l.lemma=?", term),
        "morph": ("", "1", None),
    }
    if field == "auto":
        field = "strong" if number(term) else "lemma"
    join, where, value = fields[field]
    if field == "morph":
        morph = term
    args = [] if field == "morph" else [value]
    if morph:
        where += """ AND t.grammar IN (SELECT id FROM lex_grammar WHERE code=? COLLATE NOCASE AND code=?
                    UNION SELECT grammar FROM lex_categories WHERE category=?)"""
        args += [morph, morph, morph.casefold()]
    if source:
        where += " AND t.source=?"
        args.append(source)
    ranges = scopes(scope)
    where += " AND (" + " OR ".join("t.k BETWEEN ? AND ?" for _ in ranges) + ")"
    args.extend(n for pair in ranges for n in pair)
    select = (
        "count(*),count(DISTINCT t.k)"
        if count
        else "t.k,t.source,t.token_id,t.position,t.surface,l.lemma,g.code AS morphology"
    )
    order = "" if count else " ORDER BY t.k,t.source,t.position"
    cursor = db.execute(
        f"""SELECT {select} FROM lex_tokens t JOIN lex_lemmas l ON t.lemma_id=l.id JOIN lex_grammar g ON g.id=t.grammar
        {join} WHERE {where}{order}""",
        args,
    )
    if count:
        return cursor.fetchone()
    return iter_records(cursor) if stream else records(cursor)


def aligned(db, version, k, position):
    return db.execute(
        """SELECT t.source,t.token_id,a.resource FROM lex_alignments a
        JOIN editions e ON e.name=a.version AND e.digest=a.digest
        JOIN lex_tokens t ON t.id=a.token WHERE a.version=? AND a.k=? AND a.position=?
        ORDER BY t.source,t.position""",
        (version, k, position),
    ).fetchall()


def has_tokens(db, term):
    strong = number(term)
    if strong:
        return (
            db.execute(
                "SELECT 1 FROM lex_numbers WHERE number=? LIMIT 1", (strong,)
            ).fetchone()
            is not None
        )
    return (
        db.execute(
            "SELECT 1 FROM lex_lemmas WHERE folded=? LIMIT 1", (fold(term),)
        ).fetchone()
        is not None
    )


def summary(db, term):
    """Counts grouped by linguistic source; indexed joins also serve dictionary-only installs."""
    if number(term):
        clause = "JOIN lex_numbers n ON n.token=t.id WHERE n.number=?"
        value = number(term)
    else:
        clause = "JOIN lex_lemmas l ON l.id=t.lemma_id WHERE l.folded=?"
        value = fold(term)
    return db.execute(
        "SELECT t.source,count(*),count(DISTINCT t.k),min(t.k),group_concat(DISTINCT g.code) FROM lex_tokens t JOIN lex_grammar g ON g.id=t.grammar "
        + clause
        + " GROUP BY t.source",
        (value,),
    ).fetchall()


class LemmaHits:
    """Window onto one source lemma's ordered occurrences for keyboard browsing."""

    def __init__(self, db, source, lemma, scope=None):
        from library import scopes

        self.db = db
        lemma_id = db.execute(
            "SELECT id FROM lex_lemmas WHERE source=? AND lemma=?", (source, lemma)
        ).fetchone()[0]
        ranges = scopes(scope)
        restriction = " OR ".join("t.k BETWEEN ? AND ?" for _ in ranges)
        self.where = f"t.lemma_id=? AND ({restriction})"
        self.params = (lemma_id, *(n for pair in ranges for n in pair))
        self.total = db.execute(
            f"SELECT count(*) FROM lex_tokens t WHERE {self.where}", self.params
        ).fetchone()[0]
        self.start, self.rows = 0, []

    def __len__(self):
        return self.total

    def window(self, start, size):
        size = min(size, self.total - start)
        if start < self.start or start + size > self.start + len(self.rows):
            self.start = max(0, start - 16)
            self.rows = records(
                self.db.execute(
                    f"""SELECT t.k,t.position,t.surface,g.code AS morphology
                FROM lex_tokens t JOIN lex_grammar g ON g.id=t.grammar WHERE {self.where}
                ORDER BY t.k,t.position LIMIT ? OFFSET ?""",
                    (*self.params, size + 32, self.start),
                )
            )
        offset = start - self.start
        return self.rows[offset : offset + size]


def passage_hits(db, term, version, scope=None):
    """Reader destinations in an installed edition using numeric reference correspondence."""
    from library import scopes

    if number(term):
        join = "JOIN lex_numbers a ON a.token=t.id"
        condition, value = "a.number=?", number(term)
    else:
        join = "JOIN lex_lemmas a ON a.id=t.lemma_id"
        condition, value = "a.folded=?", fold(term)
    ranges = scopes(scope)
    restrict = " OR ".join("t.k BETWEEN ? AND ?" for _ in ranges)
    return db.execute(
        f"""SELECT v.k,v.version,v.text FROM verses v WHERE v.version=? AND v.k IN (
        SELECT t.k FROM lex_tokens t {join} WHERE {condition} AND ({restrict})) ORDER BY v.k""",
        (version, value, *(n for pair in ranges for n in pair)),
    ).fetchall()
