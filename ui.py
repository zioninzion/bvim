"""Offline Bible reader, concordance and translation manager."""

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import library
import study
from refs import bounds, label, launch_target, names, parts


def record(k, version, text):
    b, c, v = parts(k)
    return {
        "translation": version,
        "book_id": b,
        "book": names[b],
        "chapter": c,
        "verse": v,
        "text": text,
    }


def emit(rows, fmt):
    for k, version, text in rows:
        if fmt == "jsonl":
            print(json.dumps(record(k, version, text), ensure_ascii=False))
        else:
            text = text if text is not None else "[missing]"
            ref = f"{label(k)} [{version}]"
            print(f"**{ref}** {text}" if fmt == "md" else f"{ref} {text}")


def parser():
    p = argparse.ArgumentParser(prog="bvim", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("history")
    sub.add_parser("reindex")
    i = sub.add_parser("import")
    i.add_argument("file", type=Path)
    i.add_argument("--name", required=True)
    i.add_argument("--source", default="")
    i.add_argument("--license", default="User supplied")
    i.add_argument("--versification", default="unspecified")
    i.add_argument("--replace", action="store_true")
    for cmd in ("versions", "use", "remove", "export"):
        q = sub.add_parser(cmd)
        if cmd != "versions":
            q.add_argument("name")
    for cmd in ("tui", "read", "compare", "search"):
        q = sub.add_parser(cmd)
        q.add_argument("input", nargs="*" if cmd == "tui" else "+")
        q.add_argument("--versions", "-V")
        if cmd != "tui":
            q.add_argument("--format", choices=["text", "md", "jsonl"], default="text")
        if cmd == "compare":
            q.add_argument("--diff", action="store_true")
        if cmd == "search":
            q.add_argument("--in", dest="scope")
            q.add_argument("--limit", type=int)
            q.add_argument(
                "--count",
                action="store_true",
                help="print total hits and distinct verses",
            )
            q.add_argument(
                "--mode", choices=["fts", "regex", "glob", "fuzzy"], default="fts"
            )
            q.add_argument(
                "--sort", choices=("exact", "reference", "relevance"), default="exact"
            )
            q.add_argument("--tolerance", type=int, default=1)
    q = sub.add_parser("resource")
    q.add_argument("file")
    for field in ("name", "license", "source"):
        q.add_argument("--" + field, required=True)
    sub.add_parser("remove-resource").add_argument("name")
    sub.add_parser("lookup").add_argument("term")
    q = sub.add_parser("occurrences")
    q.add_argument("term")
    q.add_argument("--version")
    q.add_argument("--in", dest="scope")
    q.add_argument("--morph")
    return p, sub.choices


def run(db, a):
    cmd = a.cmd
    if cmd == "history":
        row = db.execute("SELECT value FROM settings WHERE key='history'").fetchone()
        for vs, k in json.loads(row[0]) if row else []:
            print(label(k), ",".join(vs), sep="\t")
    elif cmd == "reindex":
        with db:
            db.execute("INSERT INTO idx(idx) VALUES('rebuild')")
    elif cmd == "import":
        n, warnings = library.install(
            db, a.file, a.name, a.source, a.license, a.replace, a.versification
        )
        for warning in warnings:
            print(warning, file=sys.stderr)
        print(f"{a.name}: {n} verses, {len(warnings)} warnings, 0 duplicates")
    elif cmd == "resource":
        print(study.load(db, a.file, a.name, a.source, a.license), "entries")
    elif cmd == "remove-resource":
        with db:
            if not db.execute("DELETE FROM resources WHERE id=?", (a.name,)).rowcount:
                raise ValueError("Unknown resource")
    elif cmd == "lookup":
        rows = study.lookup(db, a.term)
        for row in rows:
            print(*row, sep="\t")
        return 0 if rows else 1
    elif cmd == "occurrences":
        rows = study.occurrences(
            db, a.term, library.edition(db, a.version), a.scope, a.morph
        )
        for (k,) in rows:
            print(label(k))
        return 0 if rows else 1
    elif cmd == "versions":
        for row in db.execute(
            "SELECT name,source,license,digest,versification FROM editions ORDER BY name"
        ):
            print("*" if row[0] == library.edition(db) else "-", *row, sep="\t")
    elif cmd in ("use", "remove", "export"):
        version = library.edition(db, a.name)
        with db:
            if cmd == "use":
                db.execute("DELETE FROM settings WHERE key='panes'")
                db.execute(
                    "INSERT OR REPLACE INTO settings VALUES('default',?)", (version,)
                )
            elif cmd == "remove":
                db.execute("DELETE FROM editions WHERE name=?", (version,))
            else:
                for (line,) in db.execute(
                    "SELECT prefix||text||ending FROM verses WHERE version=? ORDER BY seq",
                    (version,),
                ):
                    sys.stdout.buffer.write(line.encode("utf8"))
    else:
        versions = (
            [library.edition(db, v.strip()) for v in a.versions.split(",")]
            if a.versions
            else [library.edition(db)]
        )
        if cmd in ("compare", "read") and len(versions) > 1:
            schemes = [
                db.execute(
                    "SELECT versification FROM editions WHERE name=?", (v,)
                ).fetchone()[0]
                for v in versions
            ]
            if len(set(schemes)) > 1 or "unspecified" in schemes:
                print(
                    "Comparing numeric references. Versification: "
                    + ", ".join(f"{v}={s}" for v, s in zip(versions, schemes)),
                    file=sys.stderr,
                )
        value = " ".join(a.input)
        if cmd == "tui":
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise ValueError(
                    "Interactive reader requires a terminal. Use bvim read REF."
                )
            if not a.versions:
                saved = db.execute(
                    "SELECT value FROM settings WHERE key='panes'"
                ).fetchone()
                installed = {r[0] for r in db.execute("SELECT name FROM editions")}
                if saved:
                    versions = [
                        v for v in json.loads(saved[0]) if v in installed
                    ] or versions
            import reader

            reader.open_reader(db, versions, value)
        elif cmd == "search":
            if a.limit is not None and a.limit < 1:
                raise ValueError("--limit must be positive")
            if a.sort == "relevance" and a.mode != "fts":
                raise ValueError("Relevance sorting requires --mode fts")
            if a.count or (a.format == "text" and sys.stdout.isatty()):
                if a.mode == "fts":
                    counts = library.search_counts(db, versions, value, a.scope)
                else:
                    from patterns import scan_counts

                    counts = scan_counts(
                        db, versions, value, a.scope, a.mode, a.tolerance
                    )
                if a.count:
                    print(
                        json.dumps(counts._asdict()) if a.format == "jsonl" else counts
                    )
                    return 0 if counts.verses else 1
                print(counts, file=sys.stderr)
            if a.mode == "fts":
                rows = library.search(
                    db, versions, value, a.scope, a.limit or -1, sort=a.sort
                )
            else:
                from patterns import scan

                rows = list(
                    scan(
                        db,
                        versions,
                        value,
                        a.scope,
                        a.limit,
                        a.mode,
                        a.tolerance,
                        sort=a.sort,
                    )
                )
            emit(rows, a.format)
            return 0 if rows else 1
        else:
            for ref in value.split(";"):
                limits = bounds(ref)
                results = {v: dict(library.passage(db, v, limits)) for v in versions}
                keys = sorted(set().union(*results.values()))
                if not keys:
                    raise ValueError(f"No installed verses at {ref}")
                for edge in limits:
                    if edge % 1000 not in (0, 999) and edge not in keys:
                        raise ValueError(f"Unavailable endpoint {label(edge)}")
                if getattr(a, "diff", False):
                    from layout import differences

                    for k in keys:
                        base = results[versions[0]].get(k)
                        for v in versions[1:]:
                            if base is not None and k in results[v]:
                                results[v][k] = differences(base, results[v][k])
                emit(
                    ((k, v, results[v].get(k)) for k in keys for v in versions),
                    a.format,
                )
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    p, commands = parser()
    if not argv:
        argv = ["tui"]
    elif "--print" in argv or "--search" in argv:
        flag = "--search" if "--search" in argv else "--print"
        argv.remove(flag)
        argv.insert(0, "search" if flag == "--search" else "read")
    elif argv[0] not in commands and not argv[0].startswith("-"):
        printing = any(arg == "--format" or arg.startswith("--format=") for arg in argv)
        if sys.stdin.isatty() and sys.stdout.isatty() and not printing:
            argv.insert(0, "tui")
        else:
            read_args = p.parse_args(["read", *argv])
            passage, query = launch_target(" ".join(read_args.input))
            if passage is None:
                argv = ["search", query, "--format", read_args.format]
                if read_args.versions:
                    argv.extend(["--versions", read_args.versions])
            else:
                argv.insert(0, "read")
    a = p.parse_args(argv)
    try:
        with closing(library.connect()) as db:
            return run(db, a)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except (ValueError, OSError, sqlite3.Error) as e:
        print(f"bvim: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
