"""Keyboard reader. Screen-independent State also drives workflow benchmarks."""

import curses
import json
import os
import re
import shutil
import subprocess
import webbrowser
from bisect import bisect_left
from functools import lru_cache, partial

import study
import styled
from layout import columns, differences, display_wrap
from layout import width as cell_width
from library import SearchCounts, edition, passage, scopes, search, search_counts
from refs import (
    bounds,
    choices,
    label,
    launch_target,
    names,
    normalize_reference,
    parts,
)

HELP = [
    "j/k or arrows  next/previous verse     10j  move ten verses",
    "l/h  next/previous chapter     ]/[  next/previous book",
    "gg/G  first/last verse     16G  verse 16 in this chapter",
    "Ctrl-D/U  half screen     Ctrl-F/B  full screen (verses)",
    ":Jn3:16 or :16  jump     Tab  complete suggested book",
    "/  find text     arrows  preview     Enter  browse results     Enter again  open",
    "/Jn 3:16,18; Rom 8:1  find multiple references",
    "Search history: Ctrl-P older, Ctrl-N newer. / resumes your last query.",
    "In / and : prompts, Ctrl-W deletes the preceding word. Ctrl-U clears the line",
    "n/N  next/previous hit     R  reopen results",
    "Ctrl-O/Tab  previous/next jump     ma / 'a  set/recall mark a",
    "v  select verses     y  copy with references     #  toggle numbers",
    ":versions A,B  compare     :use B  switch     :lookup TERM  study",
    ":scope REF limits searches; :scope clears it. :sort exact, relevance or reference",
    "Command prompt: arrows choose a suggestion, Tab inserts it, Enter opens",
    "w/b  select next/previous word in first edition     Enter  word evidence",
    "Bible Hub: x  verse lexicon     p  parallel translations (browser)",
    "Enter  entries linked to verse     :occ TERM  browse linked passages",
    "|  stacked/columns     D  wording differences     z  spacing     H  headings",
    "J/K  scroll wrapped lines within current verse     q  quit",
]
ENTER = ("\n", "\r", "KEY_ENTER")


class State:
    def __init__(self, db, versions, ref=""):
        self.db = db
        self.indices = {}
        self.rows = lru_cache(maxsize=512)(self._rows)
        self.scope = None
        self.sort = "exact"
        self.back, self.forward = [], []
        self.hits, self.hit = [], 0
        self.result_summary = ""
        self.highlights = {}
        self.anchor = None
        self.set_versions(versions)
        saved = db.execute(
            "SELECT value FROM settings WHERE key=?", ("last:" + self.versions[0],)
        ).fetchone()
        if ref:
            self.i = self.resolve(ref)
        elif saved and int(saved[0]) in self.keys:
            self.i = bisect_left(self.keys, int(saved[0]))

    def set_versions(self, versions):
        versions = tuple(dict.fromkeys(edition(self.db, v) for v in versions))
        if versions not in self.indices:
            holders = ",".join("?" for _ in versions)
            self.indices[versions] = [
                k
                for (k,) in self.db.execute(
                    f"SELECT DISTINCT k FROM verses WHERE version IN ({holders}) ORDER BY k",
                    versions,
                )
            ]
        self.versions = versions
        self.keys = self.indices[versions]
        self.i = 0

    @property
    def k(self):
        return self.keys[self.i]

    def resolve(self, ref):
        ref = ref.strip()
        if re.match(r"^\d+(?:\s*[:.]|\s+\d)", ref):
            ref = names[self.k // 1000000] + " " + ref
        if ref.isdecimal():
            ref = label(self.k).rsplit(":", 1)[0] + ":" + ref
        lo, hi = bounds(ref)
        i = bisect_left(self.keys, lo)
        if (
            i == len(self.keys)
            or self.keys[i] > hi
            or (lo % 1000 and self.keys[i] != lo)
        ):
            raise ValueError("Reference unavailable in selected editions")
        return i

    def jump(self, versions, k):
        old = self.versions, self.k
        self.set_versions(versions)
        self.i = bisect_left(self.keys, k)
        if self.i >= len(self.keys) or self.k != k:
            self.restore(old)
            raise ValueError("Reference unavailable in selected editions")
        if old != (self.versions, k):
            self.back.append(old)
            self.forward.clear()
        self.anchor = None

    def restore(self, target):
        versions, k = target
        self.set_versions(versions)
        self.i = bisect_left(self.keys, k)
        self.anchor = None

    def history(self, back):
        src, dst = (self.back, self.forward) if back else (self.forward, self.back)
        if src:
            dst.append((self.versions, self.k))
            self.restore(src.pop())

    def _rows(self, versions, k):
        return [
            (v, next((text for _, text in passage(self.db, v, (k, k))), "[missing]"))
            for v in versions
        ]

    def motion(self, key, count):
        if key in ("j", "k"):
            self.i = max(
                0, min(len(self.keys) - 1, self.i + count * (1 if key == "j" else -1))
            )
            return
        unit = 1000 if key in "hl" else 1000000
        i = self.i
        for _ in range(min(count, len(self.keys))):
            group = self.keys[i] // unit
            if key in "l]":
                dest = bisect_left(self.keys, (group + 1) * unit)
                if dest >= len(self.keys):
                    break
            else:
                previous = bisect_left(self.keys, group * unit) - 1
                if previous < 0:
                    break
                dest = bisect_left(self.keys, self.keys[previous] // unit * unit)
            i = dest
        self.jump(self.versions, self.keys[i])

    def find(self, query, limit=-1):
        return search(
            self.db,
            self.versions,
            query,
            self.scope,
            limit,
            highlight=True,
            sort=self.sort,
        )

    def search_history(self):
        row = self.db.execute(
            "SELECT value FROM settings WHERE key='search_history'"
        ).fetchone()
        return json.loads(row[0]) if row else []

    def remember_search(self, query):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            recent = [query, *(q for q in self.search_history() if q != query)]
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES('search_history', ?)",
                (json.dumps(recent[:100]),),
            )

    def preview(self, query):
        limit = 101
        hits = self.find(query, limit)
        counts = (
            SearchCounts.from_highlights(hits)
            if len(hits) < limit
            else search_counts(self.db, self.versions, query, self.scope)
        )
        return hits, counts

    def set_hits(self, hits, *, text_search=False):
        self.result_summary = (
            str(SearchCounts.from_highlights(hits))
            if text_search
            else f"{len(hits)} linked verses"
        )
        self.hits = hits
        self.hit = 0
        self.highlights = {
            (k, v): text for k, v, text in hits if isinstance(text, styled.MatchedText)
        }

    def linked_verses(self, term, resource=None):
        version = self.versions[0]
        return [
            (k, version, self.rows((version,), k)[0][1])
            for (k,) in study.occurrences(self.db, term, version, resource=resource)
        ]

    def accept(self, i):
        if self.hits:
            self.hit = i % len(self.hits)
            k, v, _ = self.hits[self.hit]
            self.jump(self.versions if v in self.versions else [v], k)


def completions(state, buf):
    cmd, sep, arg = buf.partition(" ")
    if sep and cmd in ("versions", "use"):
        prefix, comma, tail = arg.rpartition(",")
        return [
            cmd + " " + prefix + comma + name
            for (name,) in state.db.execute("SELECT name FROM editions ORDER BY name")
            if name.casefold().startswith(tail.strip().casefold())
        ]
    if sep and cmd in ("lookup", "occ"):
        return [
            cmd + " " + term
            for (term,) in state.db.execute(
                "SELECT DISTINCT term FROM entries WHERE instr(lower(term),lower(?))>0 ORDER BY length(term),term LIMIT 12",
                (arg,),
            )
        ]
    if not buf or any(ch.isdigit() for ch in buf.lstrip("123")):
        return []
    commands = [
        c + " "
        for c in ("versions", "use", "lookup", "occ", "scope", "sort")
        if c.startswith(buf.casefold())
    ]
    return commands + [names[i] + " " for i in choices(buf)[:8]]


def open_reader(db, versions, ref):
    state = State(db, versions)
    query = ""
    if ref:
        limits, query = launch_target(ref)
        if limits is not None:
            ref = normalize_reference(ref)
            state.i = state.resolve(ref)
            if re.search(r"\d\s*[-–—]", ref):
                end = bisect_left(state.keys, limits[1])
                if end == len(state.keys) or state.keys[end] != limits[1]:
                    raise ValueError(f"Unavailable endpoint {label(limits[1])}")
                state.anchor = end
    # ncurses reads this during initialization to distinguish Esc from arrow keys.
    os.environ.setdefault("ESCDELAY", "10")
    try:
        curses.wrapper(interact, state, query)
    except curses.error as error:
        raise ValueError(f"Terminal initialization or input failed: {error}") from error
    finally:
        with db:
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES('panes',?)",
                (json.dumps(state.versions),),
            )
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES('history',?)",
                (json.dumps([*state.back, (state.versions, state.k)][-100:]),),
            )
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                ("last:" + state.versions[0], str(state.k)),
            )
        state.rows.cache_clear()


class Heading(str):
    """A section label drawn independently of the verse selection."""


def verse_lines(s, i, width, numbers, changes, headings, parallel, expanded, word=None):
    k = s.keys[i]
    lines = []
    rows = [(v, s.highlights.get((k, v), text)) for v, text in s.rows(s.versions, k)]
    if i == s.i and word is not None:
        version, text = rows[0]
        rows[0] = version, styled.select_word(text, word)
    if changes and len(rows) > 1:
        rows = [rows[0]] + [
            (
                v,
                differences(rows[0][1], t)
                if t != "[missing]" and rows[0][1] != "[missing]"
                else t,
            )
            for v, t in rows[1:]
        ]
    if headings and (i == 0 or s.keys[i - 1] // 1000 != k // 1000):
        book, chapter, _ = parts(k)
        book_start = i == 0 or s.keys[i - 1] // 1000000 != book
        chapter_title = f"Chapter {chapter}"
        if book_start:
            lines.extend(
                Heading(line)
                for line in display_wrap(names[book].upper(), max(1, width - 2))
            )
        else:
            chapter_title = f"{names[book]} · {chapter_title}"
            if len(chapter_title) > width - 2:
                chapter_title = f"{names[book]} {chapter}"
        lines.extend(
            Heading(line) for line in display_wrap(chapter_title, max(1, width - 2))
        )
    first_verse_line = len(lines)
    available = max(1, width - 2)
    gutter = f"{k % 1000:<3} " if numbers else ""
    if gutter and available < len(gutter) + 2:
        lines.append(gutter.rstrip())
        gutter = ""
    body_width = available - len(gutter)
    indent = " " * len(gutter)
    if parallel and len(rows) > 1:
        body = columns(rows, body_width)
        lines.extend(
            styled.join((gutter if n == 0 else indent, line))
            for n, line in enumerate(body)
        )
    else:
        for v, text in rows:
            body = styled.join((f"[{v}] ", text)) if len(rows) > 1 else text
            lines.extend(
                styled.join((gutter if n == 0 else indent, line))
                for n, line in enumerate(display_wrap(body, body_width))
            )
    if expanded:
        lines.append("")
    if i == s.i and word is not None:
        first_verse_line = next(
            (n for n, line in enumerate(lines) if getattr(line, "selected", ())),
            first_verse_line,
        )
    return lines, first_verse_line


def draw_passage(s, put, height, offset, render):
    middle = height // 2
    active, first = render(s.i)
    scroll_lines = len(active) - first
    focus = first + min(offset, scroll_lines - 1)
    selected_from, selected_to = sorted((s.i, s.i if s.anchor is None else s.anchor))
    visible = 0

    def draw(i, lines, top):
        attr = curses.A_REVERSE if selected_from <= i <= selected_to else 0
        for row in range(max(1, top), min(height - 1, top + len(lines))):
            line = lines[row - top]
            put(row, line, curses.A_BOLD if isinstance(line, Heading) else attr)

    top = middle - focus
    draw(s.i, active, top)
    visible += 1
    bottom = top + len(active)
    for i in range(s.i - 1, -1, -1):
        if top <= 1:
            break
        lines, _ = render(i)
        top -= len(lines)
        draw(i, lines, top)
        visible += 1
    for i in range(s.i + 1, len(s.keys)):
        if bottom >= height - 1:
            break
        lines, _ = render(i)
        draw(i, lines, bottom)
        bottom += len(lines)
        visible += 1
    return visible, scroll_lines


def match_style():
    attr = curses.A_BOLD | curses.A_UNDERLINE
    word_attr = curses.A_BOLD
    try:
        if curses.has_colors():
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
            attr |= curses.color_pair(1)
            curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
            word_attr |= curses.color_pair(2)
    except curses.error:
        pass
    return attr, word_attr


def interact(win, s, initial_query=""):
    match_attr, word_attr = match_style()
    preview_counts = None
    recent = s.search_history()
    last_query = recent[0] if recent else ""
    history_pos = 0
    history_choices = []
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    mode, buf, pending, count, msg = "NORMAL", "", "", "", ""
    items, idx, offset = [], 0, 0
    if s.anchor is not None:
        mode = "VISUAL"
    if initial_query:
        last_query = buf = initial_query
        mode = "SEARCH"
        try:
            items = s.find(buf)
            if items:
                s.set_hits(items, text_search=True)
                s.remember_search(buf)
                mode = "RESULTS"
                msg = "j/k select  Enter open  Esc return"
            else:
                preview_counts = SearchCounts(0, 0)
        except ValueError as error:
            msg = str(error)
    completion_idx = 0
    parent_study = None
    numbers = True
    preferred_word = None
    parallel = changes = expanded = False
    headings = True
    while True:
        if mode == "VISUAL" and s.anchor is None:
            mode = "NORMAL"
        word = None
        if preferred_word is not None and mode == "NORMAL":
            row = next(passage(s.db, s.versions[0], (s.k, s.k)), None)
            if row:
                tokens = row[1].split()
                word = min(preferred_word, len(tokens) - 1)
        height, width = win.getmaxyx()
        win.erase()

        def put(y, line, attr=0, height=height, width=width):
            if 0 <= y < height:
                try:
                    win.addnstr(y, 0, line, max(0, width - 1), attr)
                    for start, end in getattr(line, "spans", ()):
                        x = cell_width(line[:start])
                        match = line[start:end]
                        overlay = (
                            match_attr
                            if match_attr & curses.A_COLOR
                            else attr | match_attr
                        )
                        win.addnstr(y, x, match, len(match), overlay)
                    for start, end in getattr(line, "selected", ()):
                        selection = (
                            word_attr
                            if word_attr & curses.A_COLOR
                            else word_attr | (attr ^ curses.A_REVERSE)
                        )
                        win.addnstr(
                            y,
                            cell_width(line[:start]),
                            line[start:end],
                            end - start,
                            selection,
                        )
                        for a, b in line.spans:
                            lo, hi = max(a, start), min(b, end)
                            if lo < hi:
                                win.addnstr(
                                    y,
                                    cell_width(line[:lo]),
                                    line[lo:hi],
                                    hi - lo,
                                    selection | curses.A_UNDERLINE,
                                )
                except curses.error:
                    pass

        detail = ""
        if mode == "SEARCH" and preview_counts is not None:
            detail = f"  {preview_counts}"
        elif mode == "RESULTS":
            detail = f"  {s.result_summary}"
        put(
            0,
            f"{'NORMAL · RESULTS' if mode == 'RESULTS' else mode}{detail}  {label(s.k)}  {' / '.join(s.versions)}",
            curses.A_REVERSE,
        )
        visible = 0
        y = 1
        if mode in ("HELP", "STUDY", "SEARCH", "RESULTS"):
            lines = HELP if mode == "HELP" else items
            for i in range(idx, len(lines)):
                item = lines[i]
                line = (
                    styled.join((f"{label(item[0])} [{item[1]}] ", item[2]))
                    if isinstance(item, tuple)
                    else item
                )
                for part in display_wrap(line, max(1, width - 2)):
                    if y >= height - 1:
                        break
                    put(y, part, curses.A_REVERSE if i == idx else 0)
                    y += 1
                if y >= height - 1:
                    break
        else:
            render = partial(
                verse_lines,
                s,
                width=width,
                numbers=numbers,
                changes=changes,
                headings=headings,
                parallel=parallel,
                expanded=expanded,
                word=word if mode == "NORMAL" else None,
            )
            visible, current_lines = draw_passage(s, put, height, offset, render)
        if word is not None and mode == "NORMAL" and not msg:
            msg = f"Word {word + 1}: {tokens[word]}   Enter lookup"
        prompt = {"SEARCH": "/", "COMMAND": ":"}.get(mode)
        footer = (
            prompt + buf + "  " + msg
            if prompt
            else msg or pending + count or "? help  : jump  / search"
        )
        put(height - 1, footer, curses.A_BOLD)
        win.refresh()
        key = win.get_wch()
        if isinstance(key, int):
            key = curses.keyname(key).decode()
        if key == "KEY_RESIZE":
            continue
        msg = ""
        try:
            verse_motion = key in (
                "j",
                "k",
                "KEY_DOWN",
                "KEY_UP",
                "h",
                "l",
                "[",
                "]",
                "g",
                "G",
                "\x04",
                "\x15",
                "\x06",
                "\x02",
                "\x0f",
                "\t",
                "n",
                "N",
            )
            if mode == "NORMAL" and not (
                verse_motion or key.isdecimal() or key in ("w", "b", "x", "p", *ENTER)
            ):
                preferred_word = None
            if key == "\x1b":
                if mode == "SEARCH":
                    last_query = buf
                if mode == "RESULTS" and parent_study:
                    items, study_terms, idx = parent_study
                    parent_study, mode = None, "STUDY"
                    continue
                preferred_word = None
                mode, buf, count, pending = "NORMAL", "", "", ""
                s.anchor = None
                continue
            if (
                mode in ("HELP", "STUDY", "RESULTS")
                or mode == "SEARCH"
                and key in ("KEY_DOWN", "KEY_UP", *ENTER)
            ):
                size = len(HELP) if mode == "HELP" else len(items)
                if (
                    mode == "RESULTS"
                    and len(key) == 1
                    and key.isascii()
                    and key.isdecimal()
                ):
                    count = (count + key)[:6]
                    continue
                step = int(count or 1)
                count = ""
                if mode == "RESULTS" and key == "G":
                    idx = max(0, size - 1)
                    continue
                if key in ("j", "KEY_DOWN", "k", "KEY_UP"):
                    idx = max(
                        0,
                        min(
                            size - 1,
                            idx + (step if key in ("j", "KEY_DOWN") else -step),
                        ),
                    )
                elif key in ENTER and mode == "SEARCH" and items:
                    s.set_hits(s.find(buf), text_search=True)
                    s.remember_search(buf)
                    last_query = buf
                    items, mode = s.hits, "RESULTS"
                    msg = "j/k select  Enter open  Esc return"
                elif key in ENTER and mode == "RESULTS" and items:
                    s.accept(idx)
                    msg = s.result_summary
                    mode, offset = "NORMAL", 0
                elif key in ENTER and mode == "SEARCH" and preview_counts is not None:
                    s.remember_search(buf)
                    last_query = buf
                    msg = "No matching verses"
                elif key in ENTER and mode == "STUDY" and items:
                    parent_study = items, study_terms, idx
                    term, res = study_terms[idx]
                    hits = s.linked_verses(term, res)
                    s.set_hits(hits)
                    items, idx, mode = hits, 0, "RESULTS"
                    msg = f"{len(hits)} linked verses"
                elif key in ("q", "?") or key in ENTER and mode in ("HELP", "STUDY"):
                    mode = "NORMAL"
                continue
            if mode in ("COMMAND", "SEARCH"):
                if key in ("KEY_DOWN", "KEY_UP") and mode == "COMMAND":
                    options = completions(s, buf)
                    if options:
                        completion_idx = (
                            completion_idx + (1 if key == "KEY_DOWN" else -1)
                        ) % len(options)
                        msg = options[completion_idx] + "  Tab completes"
                    continue
                if mode == "SEARCH" and key in ("\x10", "\x0e"):
                    if not history_choices:
                        history_choices = [
                            buf,
                            *(q for q in s.search_history() if q != buf),
                        ]
                    history_pos = max(
                        0,
                        min(
                            len(history_choices) - 1,
                            history_pos + (1 if key == "\x10" else -1),
                        ),
                    )
                    buf = history_choices[history_pos]
                elif key in ENTER:
                    cmd, _, arg = buf.strip().partition(" ")
                    if cmd in ("versions", "use"):
                        vs = [edition(s.db, v.strip()) for v in arg.split(",")]
                        s.jump(vs, s.k)
                    elif cmd == "scope":
                        scopes(arg)
                        s.scope = arg or None
                        msg = f"Search scope: {arg or 'all books'}"
                    elif cmd == "sort":
                        if arg not in ("exact", "relevance", "reference"):
                            raise ValueError(
                                "Use :sort exact, :sort relevance or :sort reference"
                            )
                        s.sort = arg
                        msg = f"Search order: {arg}"
                    elif cmd == "lookup":
                        entries = study.lookup(s.db, arg)
                        items = [" | ".join(row) for row in entries]
                        study_terms = [(arg, row[0]) for row in entries]
                        mode, idx = "STUDY", 0
                        msg = f"{len(items)} entries  Esc returns"
                        continue
                    elif cmd == "occ":
                        hits = s.linked_verses(arg)
                        s.set_hits(hits)
                        items, idx, mode = hits, 0, "RESULTS"
                        msg = f"{len(hits)} linked verses"
                        continue
                    else:
                        s.jump(s.versions, s.keys[s.resolve(buf)])
                    mode, offset = "NORMAL", 0
                elif key == "\x17":  # Ctrl-W
                    buf = re.sub(r"\S+$", "", buf.rstrip())
                elif key == "\x15":  # Ctrl-U
                    buf = ""
                elif key in ("KEY_BACKSPACE", "\x7f", "\b"):
                    buf = buf[:-1]
                elif key == "\t" and mode == "COMMAND":
                    options = completions(s, buf)
                    if options:
                        buf = options[completion_idx % len(options)]
                elif len(key) == 1 and key.isprintable():
                    buf += key
                if mode == "SEARCH":
                    if key not in ("\x10", "\x0e"):
                        history_pos, history_choices = 0, []
                    items, idx, preview_counts = [], 0, None
                    if buf.strip():
                        items, preview_counts = s.preview(buf)
                elif mode == "COMMAND":
                    completion_idx = 0
                    options = completions(s, buf)
                    msg = "  ".join(options[:3])
                    if not options and buf:
                        try:
                            k = s.keys[s.resolve(buf)]
                            msg = label(k) + " " + s.rows(s.versions, k)[0][1]
                        except ValueError:
                            pass
                continue
            if pending:
                op, pending = pending, ""
                if op == "g" and key == "g":
                    s.jump(s.versions, s.keys[0])
                elif op == "m" and len(key) == 1 and key.isalnum():
                    with s.db:
                        s.db.execute(
                            "INSERT OR REPLACE INTO marks VALUES(?,?,?)",
                            (
                                key,
                                next(
                                    v
                                    for v in s.versions
                                    if next(passage(s.db, v, (s.k, s.k)), None)
                                ),
                                s.k,
                            ),
                        )
                    msg = f"Mark {key} saved"
                elif op == "'":
                    row = s.db.execute(
                        "SELECT version,k FROM marks WHERE name=?", (key,)
                    ).fetchone()
                    if row:
                        s.jump([row[0]], row[1])
                    else:
                        msg = "Unknown mark"
                offset = 0
                continue
            if len(key) == 1 and key.isascii() and key.isdigit():
                count = (count + key)[:6]
                continue
            n = int(count or 1)
            numbered, count = bool(count), ""
            if key not in ("J", "K"):
                offset = 0
            if key in ("g", "m", "'"):
                pending = key
            elif key in ("x", "p"):
                book, chapter, verse = parts(s.k)
                slug = "songs" if book == 22 else names[book].lower().replace(" ", "_")
                section = "text" if key == "x" else "parallel"
                url = f"https://biblehub.com/{section}/{slug}/{chapter}-{verse}.htm"
                if not webbrowser.open_new_tab(url):
                    msg = f"Could not open browser: {url}"
            elif key == "q":
                return
            elif key in ("J", "K"):
                offset = max(
                    0, min(current_lines - 1, offset + (n if key == "J" else -n))
                )
            elif key in ("j", "k", "KEY_DOWN", "KEY_UP", "h", "l", "]", "["):
                s.motion({"KEY_DOWN": "j", "KEY_UP": "k"}.get(key, key), n)
            elif key in ("\x04", "\x15", "\x06", "\x02"):
                s.motion(
                    "j" if key in ("\x04", "\x06") else "k",
                    n * max(1, visible // (2 if key in ("\x04", "\x15") else 1)),
                )
            elif key == "G":
                s.jump(
                    s.versions, s.keys[s.resolve(str(n))] if numbered else s.keys[-1]
                )
            elif key in ("\x0f", "\t"):
                s.history(key == "\x0f")
            elif key in ("/", ":"):
                s.anchor = None
                parent_study = None
                completion_idx = 0
                preview_counts = None
                mode, buf, items, idx = (
                    ("SEARCH" if key == "/" else "COMMAND"),
                    "",
                    [],
                    0,
                )
                if mode == "SEARCH":
                    history_pos, history_choices = 0, []
                    buf = last_query
                    if buf.strip():
                        items, preview_counts = s.preview(buf)
            elif key == "?":
                s.anchor = None
                mode, idx = "HELP", 0
            elif key in ("n", "N"):
                s.accept(s.hit + (n if key == "n" else -n))
                msg = s.result_summary
            elif key == "R":
                parent_study = None
                mode, items, idx = "RESULTS", s.hits, s.hit
                msg = "j/k preview  Enter open  Esc return"
            elif key == "|":
                parallel = not parallel
            elif key == "D":
                changes = not changes
            elif key == "H":
                headings = not headings
            elif key == "z":
                expanded = not expanded
            elif key == "#":
                numbers = not numbers
            elif key == "v":
                s.anchor = s.i if s.anchor is None else None
                mode = "VISUAL" if s.anchor is not None else "NORMAL"
            elif key == "y":
                tool = next(
                    (v for v in ("pbcopy", "wl-copy", "xclip") if shutil.which(v)), None
                )
                if not tool:
                    raise ValueError("Install pbcopy, wl-copy or xclip")
                a, b = sorted((s.anchor if s.anchor is not None else s.i, s.i))
                value = "\n".join(
                    f"{label(k)} [{v}] {t}"
                    for k in s.keys[a : b + 1]
                    for v, t in s.rows(s.versions, k)
                )
                subprocess.run(
                    [tool] + (["-selection", "clipboard"] if tool == "xclip" else []),
                    input=value.encode(),
                    check=True,
                )
                s.anchor, mode, msg = None, "NORMAL", "Copied"
            elif key in ("w", "b"):
                row = next(passage(s.db, s.versions[0], (s.k, s.k)), None)
                if row:
                    last = len(row[1].split()) - 1
                    if word is None:
                        preferred_word = (
                            min(n - 1, last) if key == "w" else max(0, last - n + 1)
                        )
                    else:
                        preferred_word = max(
                            0, min(last, word + (n if key == "w" else -n))
                        )
            elif key in ENTER:
                entries = study.annotations(
                    s.db, s.versions[0], s.k, None if word is None else word + 1
                )
                items = [
                    f"{kind} · {term} ({res})  {surface or ''} {morph}  {body}"
                    for term, res, kind, body, morph, surface in entries
                ]
                study_terms = [(row[0], row[1]) for row in entries]
                preferred_word = None
                mode, idx, msg = (
                    "STUDY",
                    0,
                    f"{len(items)} linked entries  Enter references  Esc returns",
                )
        except (
            ValueError,
            OSError,
            subprocess.SubprocessError,
            webbrowser.Error,
        ) as error:
            msg = str(error)
