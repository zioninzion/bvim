"""Curses lexical overlay. The reader owns passage navigation and its jump list."""

import curses
from bisect import bisect_left

import lexical
from layout import cells, width, wrap
from listnav import ListNavigation
from refs import label, scope_reference
from themes import ThemeStyles

ENTER = ("\n", "\r", "KEY_ENTER")
HELP = [
    "j/k or w/b  next/previous token",
    "Counts, gg/G, Ctrl-D/U, Ctrl-F/B, u/Ctrl-R  navigate lists",
    "i  compact / interlinear; Tab  cycle installed source editions",
    "Enter  full lexical record; j/k scroll",
    "o  occurrences of this exact source lemma",
    ":sc or :scope REF  limit concordance (. book, .. chapter, bare clears)",
    "/  filter this verse by word, lemma, grammar, gloss or definition",
    "Enter  keep filter; / then Ctrl-U Enter  clear",
    "Esc  back; ?  this help",
]


def fit_row(text, limit):
    """Pad to terminal cells while preserving zero-width marks on the last letter."""
    if text.isascii():
        return text[:limit].ljust(limit)
    used = 0
    for i, ch in enumerate(text):
        size = cells(ch)
        if used + size > limit:
            return text[:i] + " " * (limit - used)
        used += size
    return text + " " * (limit - used)


def show(
    win,
    db,
    k,
    aligned=None,
    version=None,
    available=None,
    *,
    scope=None,
    set_scope=None,
    palette=ThemeStyles(),
):
    coverage = db.execute(
        """SELECT count(DISTINCT a.position) FROM lex_alignments a
        JOIN editions e ON e.name=a.version AND e.digest=a.digest WHERE a.k=? AND a.version=?""",
        (k, version),
    ).fetchone()[0]
    coverage_text = (
        f"{version}: {coverage} aligned word positions"
        if version
        else "Source verse by numeric reference"
    )
    all_tokens = lexical.verse(db, k)
    if not all_tokens:
        raise ValueError(lexical.missing_verse(db, k))
    sources = list(dict.fromkeys(t["source"] for t in all_tokens))
    selected = aligned[0] if aligned else sources[0]

    def select(source):
        tokens = [t for t in all_tokens if t["source"] == source]
        documents = [
            lexical.fold(
                " ".join(
                    [
                        t["surface"],
                        t["transliteration"],
                        t["lemma"],
                        t["morphology"],
                        *t["strong"],
                        *t["parsing"].values(),
                        t["gloss"],
                        *(d["definition"] for d in t["definitions"]),
                    ]
                )
            )
            for t in tokens
        ]
        return tokens, documents, list(range(len(tokens)))

    tokens, search, words = select(selected)
    pos = next(
        (i for i, t in enumerate(tokens) if aligned and t["token_id"] == aligned[1]), 0
    )
    mode, query, interlinear = "words", "", False
    notice = ""
    command = None
    previous = None
    occurrence_rows = []
    detail = []
    at = 0
    word_navigation = ListNavigation()
    pane_navigation = ListNavigation()
    cache = {}
    while True:
        h, w = win.getmaxyx()
        if (h, w) != cache.get("size"):
            win.erase()
            cache = {"size": (h, w)}
        rows = {}

        def put(y, line, style=0, h=h, rows=rows):
            if 0 <= y < h:
                rows[y] = (line, style)

        t = tokens[words[pos]] if words else None
        title = t["source"] if t else tokens[0]["source"]
        put(
            0,
            f"LEX  {label(k)}  {title}  ·  {mode}"
            + ("  Tab source" if len(sources) > 1 else ""),
            curses.A_BOLD,
        )
        page = max(1, h - 3)
        if mode in ("words", "filter"):
            step = 3 if interlinear and h >= 7 else 1
            header = int(step == 1 and h >= 9)
            if header:
                put(
                    1,
                    f"  #  {'Original':16}{'Translit.':14}{'Strong':11}Morph    Gloss",
                    curses.A_BOLD,
                )
            page = max(1, (h - 4 - header) // step)
            start = max(0, min(pos - page // 2, len(words) - page))
            for j, index in enumerate(words[start : start + page]):
                item = tokens[index]
                y = 1 + header + j * step
                attr = curses.A_REVERSE if start + j == pos else 0
                surface = item["surface"] or "[implicit]"
                strong = "/".join(item["strong"]) or "—"
                lead = f"{item['position']:>3}  {surface}"
                if step == 1:
                    pad = " " * max(2, 16 - width(surface))
                    put(
                        y,
                        lead
                        + pad
                        + f"{item['transliteration']:<13} {strong:<10} {item['morphology']}  {item['gloss']}",
                        attr,
                    )
                else:
                    put(y, lead, attr)
                    put(y + 1, "     " + item["transliteration"], attr)
                    put(y + 2, "     " + (item["gloss"] or "—"), attr)
            if t:
                put(
                    h - 3,
                    f"{t['lemma']}  ·  {', '.join(t['parsing'].values())}  ·  {t['gloss']}",
                    curses.A_BOLD,
                )
            put(
                h - 2,
                (
                    f"Aligned by {aligned[2]}"
                    if aligned
                    else coverage_text + " · numeric verse reference"
                )
                if not query
                else f"Filter: {query}  ({len(words)} matches)",
            )
            put(
                h - 1,
                "/" + query
                if mode == "filter"
                else "j/k word  Enter definition  o occurrences  / filter  i layout  ? help  Esc back",
            )
        else:
            if mode == "detail":
                lines = [
                    line
                    for paragraph in detail
                    for line in wrap(paragraph, max(1, w - 2))
                ]
            elif mode == "help":
                lines = HELP
            else:
                lines = occurrence_rows
            at = max(0, min(max(0, len(lines) - 1), at))
            start = max(0, min(at - page // 2, len(lines) - page))
            window = (
                lines.window(start, page)
                if mode == "occurrences"
                else lines[start : start + page]
            )
            for j, item in enumerate(window):
                if mode == "occurrences":
                    item = f"{label(item['k'])}  #{item['position']}  {item['surface']}  {item['morphology']}"
                put(j + 1, item, curses.A_REVERSE if at == start + j else 0)
            footer = f"{at + 1 if lines else 0}/{len(lines)}"
            if mode == "occurrences":
                footer += f"  Scope {scope or 'all books'}  :scope  Enter open"
            else:
                footer += "  j/k move  Esc back"
            put(h - 1, footer)
        if notice:
            put(h - 1, notice, curses.A_BOLD)
        if command is not None:
            put(h - 1, ":" + command)
        for y in range(h):
            value = rows.get(y, ("", 0))
            if cache.get(y) == value:
                continue
            try:
                text, attr = value
                # Clear the old row including the tail of a longer previous selection.
                padded = fit_row(text, max(0, w - 1))
                win.addnstr(y, 0, padded, len(padded), palette.row(attr))
            except curses.error:
                pass
            cache[y] = value
        win.refresh()
        key = win.get_wch()
        if isinstance(key, int):
            key = curses.keyname(key).decode()
        if key == "KEY_RESIZE":
            continue
        notice = ""
        if command is not None:
            if key == "\x1b":
                command = None
            elif key in ENTER:
                name, _, value = command.strip().partition(" ")
                command = None
                if name not in ("scope", "sc"):
                    notice = "Use :scope REF or bare :scope to clear the limit"
                    continue
                value = scope_reference(value, k) or None
                try:
                    hits = lexical.LemmaHits(db, t["source"], t["lemma"], value)
                except ValueError as error:
                    notice = str(error)
                    continue
                if set_scope is not None:
                    set_scope(value)
                occurrence_rows, scope, at = hits, value, 0
                pane_navigation = ListNavigation()
            elif key == "\x15":
                command = ""
            elif key == "\x17":
                command = command.rstrip().rpartition(" ")[0]
            elif key in ("KEY_BACKSPACE", "\x7f", "\b"):
                command = command[:-1]
            elif len(key) == 1 and key.isprintable():
                command += key
        elif mode == "filter":
            if key == "\x1b":
                query, words, pos = previous
                mode = "words"
                continue
            if key in ENTER:
                mode = "words"
                word_navigation = ListNavigation()
                continue
            if key == "\x15":
                query = ""
            elif key == "\x17":
                query = (
                    query.rstrip().rsplit(" ", 1)[0] + " "
                    if " " in query.rstrip()
                    else ""
                )
            elif key in ("KEY_BACKSPACE", "\x7f", "\b"):
                query = query[:-1]
            elif len(key) == 1 and key.isprintable():
                query += key
            words = [i for i, doc in enumerate(search) if lexical.fold(query) in doc]
            pos = 0
        elif mode != "words":
            motion = {"w": "j", "b": "k"}.get(key, key)
            position = pane_navigation.move(motion, at, len(lines), page)
            if position is not None:
                at = position
            elif key in ("\x1b", "q") or (mode == "help" and key == "?"):
                mode = "words"
            elif key == ":" and mode == "occurrences":
                command = ""
            elif key in ENTER and mode == "occurrences" and occurrence_rows:
                target = occurrence_rows.window(at, 1)[0]["k"]
                if available is not None:
                    i = bisect_left(available, target)
                    if i == len(available) or available[i] != target:
                        notice = f"{label(target)} absent in selected translations · Esc back"
                        continue
                return target
        elif key in ("\x1b", "q"):
            return None
        elif (
            position := word_navigation.move(
                {"w": "j", "b": "k"}.get(key, key), pos, len(words), page
            )
        ) is not None:
            pos = position
        elif key == "/":
            previous = (query, words, pos)
            mode = "filter"
        elif key == "\t" and len(sources) > 1:
            selected = sources[(sources.index(selected) + 1) % len(sources)]
            tokens, search, words = select(selected)
            query, pos, aligned = "", 0, None
            word_navigation = ListNavigation()
        elif key == "i":
            interlinear = not interlinear
        elif key == "?":
            mode, at = "help", 0
            pane_navigation = ListNavigation()
        elif t and key in ENTER:
            from lexcli import word_lines

            detail = [
                f"{t['source_reference']} · {t['token_id']} · written word {t['word_position']}",
                *word_lines(t),
            ]
            mode, at = "detail", 0
            pane_navigation = ListNavigation()
        elif t and key == "o":
            occurrence_rows = lexical.LemmaHits(db, t["source"], t["lemma"], scope)
            mode, at = "occurrences", 0
            pane_navigation = ListNavigation()
