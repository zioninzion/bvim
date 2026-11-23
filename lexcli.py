"""Original-language commands shared with the offline study backend."""

import json
import sys

import lexical
from refs import bounds, label


def arguments(sub):
    q = sub.add_parser("lex", help="analyze a verse in its source edition")
    q.add_argument("input", nargs="+")
    q.add_argument("--word", type=int)
    q.add_argument("--source")
    q.add_argument("--format", choices=("text", "md", "jsonl"), default="text")
    q = sub.add_parser("morph", help="find original tokens by morphology")
    q.add_argument("term")
    filters(q)
    q = sub.add_parser(
        "data", help="manage pinned original-language resources"
    ).add_subparsers(dest="action", required=True)
    q.add_parser("list")
    q.add_parser("status")
    q.add_parser("verify")
    q.add_parser("reindex")
    i = q.add_parser("install")
    i.add_argument("source")
    i.add_argument("--file", help="offline copy of the pinned upstream file")
    q.add_parser("remove").add_argument("source")


def filters(q):
    q.add_argument("--in", dest="scope")
    q.add_argument("--source")
    q.add_argument("--count", action="store_true")
    q.add_argument("--format", choices=("text", "jsonl"), default="text")


def data(db, a):
    from lexdata import CATALOG, TOTALS, counts, install

    if a.action == "list":
        for name, meta in CATALOG.items():
            print(name, meta.edition, meta.revision, meta.license, sep="\t")
    elif a.action == "install":
        if a.source not in CATALOG:
            raise ValueError("Unknown resource. See bvim data list")
        stats = install(
            db, a.source, a.file, lambda line: print(line, file=sys.stderr, flush=True)
        )
        print(a.source, *(f"{n:,} {key}" for key, n in stats.items()), sep="\t")
    elif a.action == "remove":
        with db:
            if not db.execute(
                "DELETE FROM lex_sources WHERE name=?", (a.source,)
            ).rowcount:
                raise ValueError("Unknown installed lexical resource")
    elif a.action == "reindex":
        with db:
            for (index,) in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name GLOB 'lex_*'"
            ).fetchall():
                db.execute('REINDEX "' + index.replace('"', '""') + '"')
    else:
        if a.action == "verify" and (
            db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
            or db.execute("PRAGMA foreign_key_check").fetchone()
        ):
            raise ValueError("SQLite integrity or foreign-key verification failed")
        for name, rev, url, digest, lic, credit, edition in db.execute(
            "SELECT * FROM lex_sources ORDER BY name"
        ):
            if a.action == "verify" and (
                name not in CATALOG
                or tuple(CATALOG[name]) != (rev, url, digest, lic, credit, edition)
            ):
                raise ValueError(
                    f"Resource provenance differs from current catalog: {name}"
                )
            coverage = counts(db, name)
            if a.action == "verify" and tuple(coverage.values()) != TOTALS[name]:
                raise ValueError(f"Unexpected installed record counts for {name}")
            print(name, edition, rev, digest, lic, credit, url, coverage, sep="\t")
            if a.action == "verify" and name.startswith("macula-"):
                for (version,) in db.execute("SELECT name FROM editions"):
                    n = db.execute(
                        """SELECT count(*) FROM lex_verses v WHERE v.source=?
                        AND NOT EXISTS (SELECT 1 FROM verses t WHERE t.k=v.k AND t.version=?)""",
                        (name, version),
                    ).fetchone()[0]
                    print(f"{name}: {n} numeric references absent from {version}")
        if a.action == "verify":
            print(
                "Database integrity, relationships and installed source manifests verified."
            )
    return 0


def word_lines(t):
    yield f"{t['position']}. {t['surface'] or '[implicit]'}  {t['transliteration']}  ·  {t['lemma']}  ·  {' / '.join(t['strong']) or '—'}  ·  {t['morphology']}"
    if "|" in t["raw_strong"] or "+" in t["raw_strong"]:
        relation = (
            "alternative mappings" if "|" in t["raw_strong"] else "compound mapping"
        )
        yield f"   {relation}: {t['raw_strong']}"
    yield "   " + ", ".join(t["parsing"].values()) + "  ·  " + (t["gloss"] or "—")
    for d in t["definitions"]:
        yield f"   {d['strong']} [{d['source']}]  {d['definition'] or '[no definition supplied]'}"
        if d["derivation"]:
            yield f"   Derivation: {d['derivation']}"
        if d["kjv"]:
            yield f"   KJV renderings: {d['kjv']}"
    if not t["definitions"]:
        yield "   No installed definition for this mapping."


def analyze(db, a):
    k, end = bounds(" ".join(a.input))
    if k != end:
        raise ValueError("lex takes one verse, e.g. John 1:1")
    rows = lexical.verse(db, k, a.source)
    if not rows:
        raise ValueError(lexical.missing_verse(db, k, a.source))
    if a.word is not None:
        rows = [r for r in rows if r["position"] == a.word]
        if not rows:
            raise ValueError("Original-language token position out of range")
    source = None
    for t in rows:
        if a.format == "jsonl":
            print(json.dumps(t, ensure_ascii=False))
        else:
            if t["source"] != source:
                source = t["source"]
                print(("## " if a.format == "md" else "") + f"{label(k)} [{source}]")
                print(
                    "Position. Original  Transliteration  ·  Lemma  ·  Strong’s  ·  Morphology"
                )
                if a.format == "md":
                    print()
            if a.word is not None:
                print(
                    f"{t['language']} · {t['source_reference']} · {t['token_id']} · written word {t['word_position']}"
                )
            lines = list(word_lines(t))
            if a.format == "md":
                print(
                    "\n".join(
                        [
                            lines[0],
                            "",
                            *("   " + s.strip() + "  " for s in lines[1:]),
                            "",
                        ]
                    )
                )
            else:
                print("\n".join(lines))
    return 0


def count_label(tokens, verses):
    return f"{tokens} {'token' if tokens == 1 else 'tokens'} in {verses} {'verse' if verses == 1 else 'verses'}"


def hits(db, a):
    rows = lexical.occurrences(
        db,
        a.term,
        field="morph" if a.cmd == "morph" else a.field,
        scope=a.scope,
        morph=getattr(a, "morph", None),
        source=a.source,
        count=a.count,
        stream=True,
    )
    if a.count:
        stats = dict(zip(("tokens", "verses"), rows))
        print(
            json.dumps(stats)
            if a.format == "jsonl"
            else count_label(stats["tokens"], stats["verses"])
        )
        return 0 if stats["tokens"] else 1
    emitted = False
    for r in rows:
        emitted = True
        r["reference"] = label(r.pop("k"))
        if a.format == "jsonl":
            print(json.dumps(r, ensure_ascii=False))
        else:
            print(
                r["reference"],
                r["position"],
                r["surface"],
                r["lemma"],
                r["morphology"],
                r["source"],
                sep="\t",
            )
    return 0 if emitted else 1
