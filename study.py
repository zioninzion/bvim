"""Source-identified study entries, with explicit edition-specific passage links."""

import json

from refs import bounds

SCHEMA = """
CREATE TABLE IF NOT EXISTS resources(id TEXT PRIMARY KEY, source TEXT NOT NULL, license TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entries(resource TEXT REFERENCES resources ON DELETE CASCADE, term TEXT,
 kind TEXT, body TEXT, PRIMARY KEY(resource,term));
CREATE TABLE IF NOT EXISTS links(resource TEXT, term TEXT, version TEXT COLLATE NOCASE REFERENCES editions ON DELETE CASCADE,
 k INTEGER, morph TEXT, position INTEGER, surface TEXT, FOREIGN KEY(resource,term) REFERENCES entries ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS entry_refs ON links(resource,term,version,k);
CREATE INDEX IF NOT EXISTS passage_entries ON links(version,k);
"""


def load(db, path, name, source, license):
    with open(path, encoding="utf8") as f, db:
        db.execute("INSERT INTO resources VALUES(?,?,?)", (name, source, license))
        count = 0
        for count, line in enumerate(f, 1):
            try:
                item = json.loads(line)
                term, kind, body = (item[k] for k in ("term", "kind", "body"))
                if kind not in ("lexicon", "dictionary", "cross-reference") or not all(
                    isinstance(s, str) and s.strip() for s in (term, body)
                ):
                    raise ValueError("invalid entry")
                db.execute(
                    "INSERT INTO entries VALUES(?,?,?,?)", (name, term, kind, body)
                )
                for ref in item.get("references", []):
                    k, end = bounds(ref["ref"])
                    version = ref["version"]
                    row = db.execute(
                        "SELECT text FROM verses WHERE version=? AND k=?", (version, k)
                    ).fetchone()
                    if k != end or not row:
                        raise ValueError(f"Unavailable verse {ref['ref']}")
                    position, surface = ref.get("position"), ref.get("surface")
                    if position is not None or surface is not None:
                        tokens = row[0].split()
                        if (
                            type(position) is not int
                            or not 1 <= position <= len(tokens)
                            or tokens[position - 1] != surface
                        ):
                            raise ValueError(
                                "Token position and surface must match the installed edition exactly"
                            )
                    db.execute(
                        "INSERT INTO links VALUES(?,?,?,?,?,?,?)",
                        (
                            name,
                            term,
                            version,
                            k,
                            ref.get("morph", ""),
                            position,
                            surface,
                        ),
                    )
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"Resource line {count}: {e}") from e
        if not count:
            raise ValueError("Empty resource")
    return count


def lookup(db, term):
    return db.execute(
        "SELECT resource,kind,term,body,source,license FROM entries JOIN resources ON resource=id WHERE term=? COLLATE NOCASE ORDER BY resource",
        (term,),
    ).fetchall()


def occurrences(db, term, version, scope=None, morph=None, resource=None):
    limits = bounds(scope) if scope else (0, 67000000)
    return db.execute(
        """SELECT DISTINCT l.k FROM links l JOIN verses v ON v.version=l.version AND v.k=l.k
        WHERE term=? COLLATE NOCASE AND l.version=? AND l.k BETWEEN ? AND ? AND (? IS NULL OR morph=?)
        AND (? IS NULL OR resource=?) ORDER BY l.k""",
        (term, version, *limits, morph, morph, resource, resource),
    ).fetchall()


def annotations(db, version, k, position=None):
    return db.execute(
        """SELECT DISTINCT e.term,e.resource,e.kind,e.body,l.morph,l.surface
        FROM links l JOIN entries e ON e.term=l.term AND e.resource=l.resource
        WHERE l.version=? AND l.k=? AND (? IS NULL OR l.position=?)
        ORDER BY e.resource,e.term,l.morph""",
        (version, k, position, position),
    ).fetchall()
