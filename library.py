"""Local Bible library. Public operations use edition plus canonical location."""

import hashlib
import os
import re
import sqlite3
from itertools import chain, islice
from pathlib import Path
from typing import NamedTuple

import lexical
import study
import styled
from refs import book, bounds, label, loc, parts, search_ranges

SCHEMA = (
    """
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS editions(name TEXT PRIMARY KEY COLLATE NOCASE, source TEXT, license TEXT, digest TEXT, versification TEXT);
CREATE TABLE IF NOT EXISTS verses(version TEXT COLLATE NOCASE REFERENCES editions ON DELETE CASCADE,
 k INTEGER, text TEXT NOT NULL, prefix TEXT, ending TEXT, seq INTEGER, UNIQUE(version,k));
CREATE INDEX IF NOT EXISTS original_order ON verses(version,seq);
CREATE VIRTUAL TABLE IF NOT EXISTS idx USING fts5(text,content='verses',content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS verse_add AFTER INSERT ON verses BEGIN
 INSERT INTO idx(rowid,text) VALUES(new.rowid,new.text); END;
CREATE TRIGGER IF NOT EXISTS verse_del AFTER DELETE ON verses BEGIN
 INSERT INTO idx(idx,rowid,text) VALUES('delete',old.rowid,old.text); END;
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS marks(name TEXT PRIMARY KEY,version TEXT COLLATE NOCASE REFERENCES editions ON DELETE CASCADE,k INTEGER);
"""
    + study.SCHEMA
    + lexical.SCHEMA
    + """
PRAGMA user_version=4;
COMMIT;
"""
)
LINE = re.compile(r"((.+?)[ \t]+([0-9]+):([0-9]+)[ \t])(.*)")


def _migrate_substring_index(db):
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("PRAGMA user_version").fetchone()[0] != 4:
            return
        try:
            db.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS substring_idx USING
                fts5(text,content='verses',content_rowid='rowid',tokenize='trigram')""")
        except sqlite3.OperationalError as error:
            if "no such tokenizer" not in str(error):
                raise
        else:
            db.execute("""CREATE TRIGGER IF NOT EXISTS substring_add AFTER INSERT ON verses BEGIN
                INSERT INTO substring_idx(rowid,text) VALUES(new.rowid,new.text); END""")
            db.execute("""CREATE TRIGGER IF NOT EXISTS substring_del AFTER DELETE ON verses BEGIN
                INSERT INTO substring_idx(substring_idx,rowid,text) VALUES('delete',old.rowid,old.text); END""")
            db.execute("INSERT INTO substring_idx(substring_idx) VALUES('rebuild')")
        db.execute("PRAGMA user_version=5")


def connect(path=None):
    path = Path(
        path or os.environ.get("BVIM_DB", "~/.local/share/bvim/library.db")
    ).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("PRAGMA foreign_keys=ON")
    version = db.execute("pragma user_version").fetchone()[0]
    if version == 0:
        db.executescript(SCHEMA)
    elif version in (1, 2):
        with db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute("pragma user_version").fetchone()[0]
            if version == 1:
                db.execute("ALTER TABLE links ADD COLUMN position INTEGER")
                db.execute("ALTER TABLE links ADD COLUMN surface TEXT")
            if version <= 2:
                db.execute(
                    "ALTER TABLE editions ADD COLUMN versification TEXT DEFAULT 'unspecified'"
                )
                db.execute("PRAGMA user_version=3")
    elif version not in (3, 4, 5):
        raise ValueError(f"Unsupported library schema {version}")
    if 1 <= version <= 3:
        db.executescript(
            "BEGIN IMMEDIATE;\n" + lexical.SCHEMA + "\nPRAGMA user_version=4; COMMIT;"
        )
    if version < 5:
        _migrate_substring_index(db)
    return db


def install(
    db,
    path,
    name,
    source="",
    license="User supplied",
    replace=False,
    versification="unspecified",
):
    if not re.fullmatch(r"[\w.-]+", name):
        raise ValueError(
            "Use letters, numbers, dots, underscores or hyphens for the translation ID"
        )
    warnings = []
    digest = hashlib.sha256()
    previous = None
    with open(path, "rb") as stream, db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT 1 FROM editions WHERE name=?", (name,)).fetchone()
        if exists and not replace:
            raise ValueError("Translation exists. Use --replace to update it.")
        db.execute("INSERT OR IGNORE INTO editions(name) VALUES(?)", (name,))

        db.execute("DELETE FROM verses WHERE version=?", (name,))
        for seq, raw in enumerate(stream, 1):
            digest.update(raw)
            line = raw.decode("utf-8")
            body = line.rstrip("\r\n")
            match = LINE.fullmatch(body)
            if not match or not match[5].strip():
                raise ValueError(f"Line {seq}: malformed or empty verse")
            try:
                k = loc(book(match[2]), int(match[3]), int(match[4]))
                db.execute(
                    "INSERT INTO verses VALUES(?,?,?,?,?,?)",
                    (name, k, match[5], match[1], line[len(body) :], seq),
                )
            except sqlite3.IntegrityError as e:
                raise ValueError(f"Line {seq}: duplicate {label(k)}") from e
            except ValueError as e:
                raise ValueError(f"Line {seq}: {e}") from e
            if previous is not None and previous >= k:
                warnings.append(f"Line {seq}: source order changes at {label(k)}")
            previous = k
        if previous is None:
            raise ValueError("Empty translation")
        prev = (0, 0, 0)
        for (k,) in db.execute(
            "SELECT k FROM verses WHERE version=? ORDER BY k", (name,)
        ):
            b, c, v = parts(k)
            expected_c = prev[1] + 1 if b == prev[0] else 1
            expected_v = prev[2] + 1 if (b, c) == prev[:2] else 1
            if ((b, c) != prev[:2] and c != expected_c) or v != expected_v:
                warnings.append(f"Numbering gap or unusual number at {label(k)}")
            prev = b, c, v
        if (
            exists
            and db.execute(
                "SELECT 1 FROM links WHERE version=? LIMIT 1", (name,)
            ).fetchone()
        ):
            old = db.execute(
                "SELECT digest FROM editions WHERE name=?", (name,)
            ).fetchone()[0]
            if old != digest.hexdigest():
                raise ValueError(
                    "Edition has study links. Remove associated resources before replacing the text."
                )
        db.execute(
            "UPDATE editions SET source=?,license=?,digest=?,versification=? WHERE name=?",
            (
                source or Path(path).name,
                license,
                digest.hexdigest(),
                versification,
                name,
            ),
        )
        db.execute("INSERT OR IGNORE INTO settings VALUES('default',?)", (name,))
    return seq, warnings


def edition(db, name=None):
    row = db.execute(
        """SELECT name FROM editions WHERE name=COALESCE(?,
        (SELECT value FROM settings WHERE key='default'))""",
        (name,),
    ).fetchone()
    if not row and name is None:
        row = db.execute("SELECT name FROM editions ORDER BY name LIMIT 1").fetchone()
    if not row:
        raise ValueError(
            f"Unknown translation {name}"
            if name
            else "Import a translation first: bvim import FILE --name ID"
        )
    return row[0]


def passage(db, version, limits):
    return db.execute(
        "SELECT k,text FROM verses WHERE version=? AND k BETWEEN ? AND ? ORDER BY k",
        (version, *limits),
    )


class SearchCounts(NamedTuple):
    hits: int
    verses: int

    def __str__(self):
        return f"{self.hits} {'hit' if self.hits == 1 else 'hits'} in {self.verses} {'verse' if self.verses == 1 else 'verses'}"

    @classmethod
    def from_highlights(cls, rows):
        return cls(
            sum(
                len(text.spans) if isinstance(text, styled.MatchedText) else 1
                for _, _, text in rows
            ),
            len({k for k, _, _ in rows}),
        )


def _verse_filter(versions, scope):
    clause = ",".join("?" for _ in versions)
    ranges = scopes(scope)
    restriction = " OR ".join("k BETWEEN ? AND ?" for _ in ranges)
    return f"version IN ({clause}) AND ({restriction})", (
        *versions,
        *(x for pair in ranges for x in pair),
    )


def _search_filter(versions, query, scope):
    if not query.strip():
        raise ValueError("Enter a search expression")
    verse_filter, params = _verse_filter(versions, scope)
    source = f"""FROM idx CROSS JOIN verses v ON v.rowid=idx.rowid
        WHERE idx MATCH ? AND {verse_filter}"""
    return source, (query, *params)


def _reference_rows(db, versions, ranges, scope, *, count=False, limit=-1):
    # Intersect each requested passage with the active scope before reading.
    requested = [
        (position, max(lo, start), min(hi, end))
        for position, (lo, hi) in enumerate(ranges)
        for start, end in scopes(scope)
        if lo <= end and start <= hi
    ]
    if not requested:
        return SearchCounts(0, 0) if count else []
    values = ",".join("(?,?,?)" for _ in requested)
    editions = ",".join("?" for _ in versions)
    sql = f"""WITH requests(position,lo,hi) AS (VALUES {values}),
        matches AS (
          SELECT v.rowid AS id,v.k,v.version,min(position) AS position
          FROM requests CROSS JOIN verses v
          WHERE v.version IN ({editions}) AND v.k BETWEEN lo AND hi
          GROUP BY v.rowid
        ) """
    args = [n for request in requested for n in request] + list(versions)
    if count:
        return SearchCounts(
            *db.execute(
                sql + "SELECT count(*),count(distinct k) FROM matches", args
            ).fetchone()
        )
    return db.execute(
        sql
        + """SELECT m.k,m.version,v.text FROM matches m JOIN verses v ON v.rowid=m.id
                         ORDER BY m.position,m.k,m.version LIMIT ?""",
        [*args, limit],
    ).fetchall()


def search_counts(db, versions, query, scope=None):
    ranges = search_ranges(query)
    if ranges is not None:
        return _reference_rows(db, versions, ranges, scope, count=True)
    literal = _substring_query(query)
    if literal is not None:
        return SearchCounts.from_highlights(
            _search_with_substrings(
                db, versions, query, scope, -1, True, "reference", literal
            )
        )
    source, args = _search_filter(versions, query, scope)
    # One ASCII byte per highlighted region. LIMIT keeps highlight() inside
    # the FTS row query, where SQLite makes the matched positions available.
    sql = f"""SELECT coalesce(sum(n),0),count(distinct k) FROM (
        SELECT k,length(cast(highlight(idx,0,'+','') AS blob))-length(cast(v.text AS blob)) AS n
        {source} LIMIT -1)"""
    try:
        return SearchCounts(*db.execute(sql, args).fetchone())
    except sqlite3.OperationalError as e:
        raise ValueError(f"Search failed: {e}") from e


def search(db, versions, query, scope=None, limit=-1, highlight=False, sort="exact"):
    ranges = search_ranges(query)
    if ranges is not None:
        return _reference_rows(db, versions, ranges, scope, limit=limit)
    literal = _substring_query(query)
    if literal is not None:
        return _search_with_substrings(
            db, versions, query, scope, limit, highlight, sort, literal
        )
    return _fts_rows(db, versions, query, scope, limit, highlight, sort)


def _fts_rows(db, versions, query, scope, limit, highlight, sort):
    source, args = _search_filter(versions, query, scope)
    body = "highlight(idx,0,?,?)" if highlight else "v.text"
    order = "rank,k,version" if sort == "relevance" else "k,version"
    order_args = ()
    if sort == "exact":
        plain = query.strip()
        quoted = re.fullmatch(r'"([^"]+)"', plain)
        if quoted:
            plain = quoted[1]
        elif not re.fullmatch(r"\w+(?:\s+\w+)*\*?", plain) or {
            "AND",
            "OR",
            "NOT",
        } & set(plain.split()):
            plain = ""
        if plain:
            prefix = not quoted and plain.endswith("*")
            literal = plain[:-1] if prefix else plain
            priorities = ["(v.text = ? COLLATE NOCASE) DESC"]
            order_args = (literal,)
            if not quoted and (prefix or len(literal.split()) > 1):
                priorities.append(
                    "(v.rowid IN (SELECT rowid FROM idx WHERE idx MATCH ?)) DESC"
                )
                order_args += ('"' + literal + '"',)
            order = ",".join([*priorities, order])
    sql = f"""SELECT v.k,v.version,{body} {source}
        ORDER BY {order} LIMIT ?"""
    try:
        markers = (styled.START, styled.END) if highlight else ()
        rows = db.execute(
            sql,
            (*markers, *args, *order_args, limit),
        ).fetchall()
        if highlight:
            return [(k, v, styled.from_fts(text)) for k, v, text in rows]
        return rows
    except sqlite3.OperationalError as e:
        raise ValueError(f"Search failed: {e}") from e


def _substring_query(query):
    plain = query.strip()
    word_phrase = re.fullmatch(r"\w+(?:[ \t]+\w+)*", plain)
    if word_phrase and not {"AND", "OR", "NOT"} & set(plain.split()):
        return query
    quoted = re.fullmatch(r'"([^"]+)"', plain)
    if quoted and quoted[1].strip() and quoted[1] != quoted[1].strip():
        return quoted[1]
    return None


def has_substring_index(db):
    return (
        db.execute("SELECT 1 FROM sqlite_master WHERE name='substring_idx'").fetchone()
        is not None
    )


def _substring_rows(db, versions, literal, scope):
    restriction, args = _verse_filter(versions, scope)
    if len(literal) >= 3 and has_substring_index(db):
        expression = '"' + literal.replace('"', '""') + '"'
        rows = db.execute(
            f"""SELECT v.k,v.version,highlight(substring_idx,0,?,?)
            FROM substring_idx CROSS JOIN verses v ON v.rowid=substring_idx.rowid
            WHERE substring_idx MATCH ? AND {restriction}
            ORDER BY v.k,v.version""",
            (styled.START, styled.END, expression, *args),
        )
        for k, version, text in rows:
            yield k, version, styled.from_fts(text)
    else:
        pattern = re.compile(re.escape(literal), re.IGNORECASE)
        for k, version, text in db.execute(
            f"SELECT k,version,text FROM verses WHERE {restriction} ORDER BY k,version",
            args,
        ):
            spans = [match.span() for match in pattern.finditer(text)]
            if spans:
                yield k, version, styled.MatchedText(text, spans)


def _one_gap_rows(db, versions, word, scope):
    if len(word) < 3 or not word.isalpha():
        return
    splits = [(word[:i], word[i:]) for i in range(1, len(word))]
    expression = "|".join(
        re.escape(left) + r"[^\W\d_]" + re.escape(right) for left, right in splits
    )
    pattern = re.compile(expression, re.IGNORECASE)
    restriction, args = _verse_filter(versions, scope)
    if word.isascii() and len(word) < 40:
        # LIKE narrows the candidates in SQLite. Check letter boundaries in
        # Python, since LIKE's wildcard can also match whitespace and digits.
        candidates = ["text LIKE ?" for _ in splits]
        if {"i", "k", "s"} & set(word.lower()):
            candidates.append("length(text) != length(cast(text AS blob))")
        restriction += " AND (" + " OR ".join(candidates) + ")"
        args += tuple(f"%{left}_{right}%" for left, right in splits)
    for k, version, text in db.execute(
        f"SELECT k,version,text FROM verses WHERE {restriction} ORDER BY k,version",
        args,
    ):
        spans = [match.span() for match in pattern.finditer(text)]
        if spans:
            yield k, version, styled.MatchedText(text, spans)


def _search_with_substrings(
    db, versions, query, scope, limit, highlight, sort, literal
):
    # Leading or trailing whitespace asks for a literal boundary. Plain words
    # also keep the existing whole-token and implicit AND results.
    substrings = _substring_rows(db, versions, literal, scope)
    if literal != literal.strip():
        rows = substrings if limit < 0 else islice(substrings, limit)
        return [(k, v, text if highlight else str(text)) for k, v, text in rows]
    results = {
        (k, version): text
        for k, version, text in _fts_rows(
            db, versions, query, scope, -1, highlight, sort
        )
    }
    for k, version, text in chain(
        substrings, _one_gap_rows(db, versions, literal, scope)
    ):
        key = k, version
        if key not in results:
            results[key] = text
        elif highlight:
            previous = results[key]
            spans = sorted(
                (*getattr(previous, "spans", ()), *getattr(text, "spans", ()))
            )
            merged = []
            for start, end in spans:
                if merged and start < merged[-1][1]:
                    merged[-1] = merged[-1][0], max(end, merged[-1][1])
                else:
                    merged.append((start, end))
            results[key] = styled.MatchedText(previous, merged)
    keys = sorted(results) if sort == "reference" else list(results)
    if limit >= 0:
        keys = keys[:limit]
    return [
        (k, version, results[k, version] if highlight else str(results[k, version]))
        for k, version in keys
    ]


def scopes(scope):
    if not scope:
        return [(0, 67000000)]
    if scope.upper() in ("OT", "NT"):
        return [(0, 39999999)] if scope.upper() == "OT" else [(40000000, 66999999)]
    return [bounds(ref) for ref in scope.split(";")]
