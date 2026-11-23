"""Keyboard reader. Screen-independent State also drives workflow benchmarks."""

import curses
import json
import os
import re
import shutil
import subprocess
import tempfile
import webbrowser
from bisect import bisect_left
from functools import lru_cache, partial
from pathlib import Path

import lexical
import study
import styled
import themes
from layout import columns, differences, display_wrap
from layout import width as cell_width
from library import SearchCounts, edition, passage, scopes, search, search_counts
from listnav import ListNavigation
from refs import (
    bounds,
    choices,
    label,
    launch_target,
    names,
    normalize_reference,
    parts,
    scope_reference,
)

ENTER = ("\n", "\r", "KEY_ENTER")
BIBLE_HUB_SECTIONS = {
    "lex": "text",
    "lexicon": "text",
    "par": "parallel",
    "parallel": "parallel",
}
NAVIGATION_LIMIT = 100


class State:
    def __init__(self, db, versions, ref=""):
        self.db = db
        self.indices = {}
        self.rows = lru_cache(maxsize=512)(self._rows)
        self.scope = None
        self.sort = "exact"
        self.back, self.forward = [], []
        self.undo_locations, self.redo_locations = [], []
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

    def load_navigation(self):
        settings = dict(
            self.db.execute(
                "SELECT key,value FROM settings WHERE key IN ('navigation_history','history')"
            )
        )
        saved = json.loads(settings.get("navigation_history", "{}"))
        if not saved:
            legacy = json.loads(settings.get("history", "[]"))
            saved = {"back": legacy[:-1], "current": legacy[-1] if legacy else None}
        installed = {
            name.casefold(): name
            for (name,) in self.db.execute("SELECT name FROM editions")
        }

        def available(location):
            if not isinstance(location, list) or len(location) != 2:
                return None
            versions, key = location
            if not versions or not isinstance(versions, list) or type(key) is not int:
                return None
            if any(
                not isinstance(v, str) or v.casefold() not in installed
                for v in versions
            ):
                return None
            versions = tuple(installed[v.casefold()] for v in versions)
            if any(
                next(passage(self.db, version, (key, key)), None)
                for version in versions
            ):
                return versions, key
            return None

        for name in ("back", "forward", "undo_locations", "redo_locations"):
            targets = getattr(self, name)
            for location in saved.get(name, [])[-NAVIGATION_LIMIT:]:
                target = available(location)
                if target is not None:
                    targets.append(target)
        current = available(saved.get("current"))
        if current is not None and current != (self.versions, self.k):
            self.back.append(current)
            self.undo_locations.append(current)
            self.forward.clear()
            self.redo_locations.clear()

    def save_navigation(self):
        current = self.versions, self.k
        saved = {
            name: getattr(self, name)[-NAVIGATION_LIMIT:]
            for name in ("back", "forward", "undo_locations", "redo_locations")
        }
        saved["current"] = current
        self.db.executemany(
            "INSERT OR REPLACE INTO settings VALUES(?,?)",
            (
                ("navigation_history", json.dumps(saved)),
                ("history", json.dumps([*self.back, current][-NAVIGATION_LIMIT:])),
            ),
        )

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

    def prompt_history(self, setting):
        row = self.db.execute(
            "SELECT value FROM settings WHERE key=?", (setting,)
        ).fetchone()
        return json.loads(row[0]) if row else []

    def remember_prompt(self, setting, text):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            recent = [
                text,
                *(item for item in self.prompt_history(setting) if item != text),
            ]
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?, ?)",
                (setting, json.dumps(recent[:100])),
            )

    def search_history(self):
        return self.prompt_history("search_history")

    def remember_search(self, query):
        self.remember_prompt("search_history", query)

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

    def linked_verses(self, term, resource=None, *, original=False):
        version = self.versions[0]
        if original or (resource is None and lexical.has_tokens(self.db, term)):
            return lexical.passage_hits(self.db, term, version, self.scope)
        return [
            (k, version, self.rows((version,), k)[0][1])
            for (k,) in study.occurrences(
                self.db, term, version, scope=self.scope, resource=resource
            )
        ]

    def set_scope(self, value):
        value = scope_reference(value or "", self.k)
        scopes(value)
        self.scope = value or None

    def selected_text(self):
        first, last = sorted(
            (self.anchor if self.anchor is not None else self.i, self.i)
        )
        return "\n".join(
            f"{label(key)} [{version}] {text}"
            for key in self.keys[first : last + 1]
            for version, text in self.rows(self.versions, key)
        )

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
        for c in ("versions", "use", "lookup", "occ", "scope", "sort", "theme")
        if c.startswith(buf.casefold())
    ]
    commands.extend(c for c in BIBLE_HUB_SECTIONS if c.startswith(buf.casefold()))
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
    state.load_navigation()
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
            state.save_navigation()
            db.execute(
                "INSERT OR REPLACE INTO settings VALUES(?,?)",
                ("last:" + state.versions[0], str(state.k)),
            )
        state.rows.cache_clear()


class Heading(str):
    """A section label drawn independently of the verse selection."""


HELP_SECTIONS = (
    (
        "Normal shortcuts",
        (
            ("j/k, ↑/↓", "Move by verse. Add a count, such as 10j."),
            ("h/l, [ / ]", "Move by chapter or book."),
            (
                "gg / G, 16G",
                "Go to the first or last verse, or to verse 16 in this chapter.",
            ),
            ("Ctrl-D/U, Ctrl-F/B", "Move a half or full screen."),
            ("J/K", "Scroll within a wrapped verse."),
            (
                "Ctrl-O / Ctrl-I",
                "Go back or forward through jumps. Tab also goes forward.",
            ),
            ("u / Ctrl-R", "Undo or redo cursor movement."),
            ("ma / 'a", "Set or recall mark a."),
            ("/, :", "Open the search or command prompt."),
            ("n/N, R", "Go to the next or previous hit, or reopen results."),
            ("v, y, e", "Select verses, copy them, or open a copy in Vim."),
            ("w/b, Enter", "Select a word or open linked study entries."),
            ("L", "Open offline Greek or Hebrew analysis."),
            ("#, H, z", "Toggle verse numbers, headings, or spacing."),
            ("|, D", "Switch comparison layout or show wording differences."),
            ("?, Esc, q", "Open help, cancel, or quit."),
        ),
    ),
    (
        "Prompt controls",
        (
            ("↑/↓, Ctrl-P/N", "Recall older or newer commands and searches."),
            ("Ctrl-W / Ctrl-U", "Delete the preceding word or clear the prompt."),
            ("Ctrl-F/B", "Move through search previews or command suggestions."),
            ("Tab", "Insert the selected command suggestion."),
            (
                "Enter",
                "Run a command. In search, focus results, then press Enter again to open a hit.",
            ),
            ("Esc", "Close the prompt."),
            ("/Jn 3:16,18; Rom 8:1", "Find several references in one search."),
            (
                "Result and study lists",
                "Use j/k, counts, gg/G, page keys, and u/Ctrl-R.",
            ),
        ),
    ),
    (
        "Colon commands",
        (
            (":Jn 3:16, :16", "Jump to a reference or a verse in the current chapter."),
            (
                ":scope, :sc",
                "Limit searches and concordance. Use . for this book, .. for this chapter, or no argument to clear.",
            ),
            (":sort", "Choose exact, relevance, or reference order."),
            (":use ID", "Switch translation."),
            (":versions A,B", "Compare translations at the current verse."),
            (":lookup TERM", "Look up a dictionary or lexical entry."),
            (":occ TERM", "Browse occurrences or linked verses."),
            (":lex / :lexicon", "Open the current verse on Bible Hub’s lexicon."),
            (
                ":par / :parallel",
                "Open the current verse on Bible Hub’s parallel page.",
            ),
            (":theme / :th", "Choose a color theme."),
        ),
    ),
)
HELP = [row for title, bindings in HELP_SECTIONS for row in (Heading(title), *bindings)]
HELP_STARTS = [index for index, row in enumerate(HELP) if isinstance(row, Heading)]


def help_lines(item, width):
    if isinstance(item, Heading):
        yield item
        return
    keys, description = item
    if width < 55:
        yield from display_wrap(keys, width)
        for line in display_wrap(description, max(1, width - 2)):
            yield "  " + line
        return
    gutter = 24
    for index, line in enumerate(display_wrap(description, width - gutter)):
        yield (keys.ljust(gutter) if index == 0 else " " * gutter) + line


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


def edit_in_vim(win, db, text):
    vim = shutil.which("vim")
    if not vim:
        raise ValueError("Vim is unavailable on PATH")
    library_path = Path(db.execute("PRAGMA database_list").fetchone()[2])
    edits = library_path.parent / "edits"
    edits.mkdir(mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="bvim-",
        suffix=".txt",
        dir=edits,
        delete=False,
    ) as draft:
        draft.write(text + "\n")
    curses.def_prog_mode()
    curses.endwin()
    try:
        subprocess.run([vim, draft.name], check=True)
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"Vim failed. Editable copy: {draft.name}") from error
    finally:
        curses.reset_prog_mode()
        win.clearok(True)
    return f"Editable copy: {draft.name}"


def interact(win, s, initial_query=""):
    saved_theme = s.db.execute(
        "SELECT value FROM settings WHERE key='theme'"
    ).fetchone()
    theme_name = (
        saved_theme[0]
        if saved_theme and saved_theme[0] in themes.OPTIONS
        else themes.DEFAULT
    )
    palette = themes.styles(theme_name)
    if palette.background:
        win.bkgd(" ", palette.background)
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
    list_mode, list_items = None, None
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
                    win.addnstr(y, 0, line, max(0, width - 1), palette.row(attr))
                    match_attr, word_attr = palette.match, palette.word
                    for start, end in getattr(line, "spans", ()):
                        x = cell_width(line[:start])
                        match = line[start:end]
                        overlay = (
                            match_attr
                            if match_attr & curses.A_COLOR
                            else palette.row(attr | match_attr)
                        )
                        win.addnstr(y, x, match, len(match), overlay)
                    for start, end in getattr(line, "selected", ()):
                        selection = (
                            word_attr
                            if word_attr & curses.A_COLOR
                            else palette.row(word_attr | (attr ^ curses.A_REVERSE))
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
        if mode in ("HELP", "STUDY", "SEARCH", "RESULTS", "THEME"):
            lines = HELP if mode == "HELP" else items
            if mode != list_mode or lines is not list_items:
                list_navigation = ListNavigation()
                list_mode, list_items = mode, lines
            start = max(0, idx - max(0, (height - 3) // 2)) if mode == "THEME" else idx
            for i in range(start, len(lines)):
                item = lines[i]
                if mode == "HELP":
                    wrapped_lines = help_lines(item, max(1, width - 2))
                    attr = curses.A_BOLD if isinstance(item, Heading) else 0
                else:
                    line = (
                        styled.join((f"{label(item[0])} [{item[1]}] ", item[2]))
                        if isinstance(item, tuple)
                        else item
                    )
                    wrapped_lines = display_wrap(line, max(1, width - 2))
                    attr = curses.A_REVERSE if i == idx else 0
                for part in wrapped_lines:
                    if y >= height - 1:
                        break
                    put(y, part, attr)
                    y += 1
                if y >= height - 1:
                    break
        else:
            list_mode, list_items = None, None
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
            "[ / ] section  j/k scroll  Esc close"
            if mode == "HELP"
            else (
                prompt + buf + "  " + msg
                if prompt
                else msg or pending + count or "? help  : jump  / search"
            )
        )
        put(height - 1, footer, curses.A_BOLD)
        win.refresh()
        key = win.get_wch()
        if isinstance(key, int):
            key = curses.keyname(key).decode()
        if key == "KEY_RESIZE":
            continue
        msg = ""
        previous_location = s.versions, s.k
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
                "u",
                "\x12",
                "n",
                "N",
            )
            if mode == "NORMAL" and not (
                verse_motion or key.isdecimal() or key in ("w", "b", "L", "e", *ENTER)
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
                mode in ("HELP", "STUDY", "RESULTS", "THEME")
                or mode == "SEARCH"
                and key in ("\x06", "\x02", *ENTER)
            ):
                size = len(HELP) if mode == "HELP" else len(items)
                if mode == "HELP" and key in ("[", "]"):
                    if key == "]":
                        section = min(
                            len(HELP_STARTS) - 1, bisect_left(HELP_STARTS, idx + 1)
                        )
                    else:
                        section = max(0, bisect_left(HELP_STARTS, idx) - 1)
                    idx = HELP_STARTS[section]
                    continue
                if mode != "SEARCH":
                    position = list_navigation.move(key, idx, size, height - 2)
                    if position is not None:
                        idx = position
                        continue
                if mode == "SEARCH" and key in ("\x06", "\x02"):
                    idx = max(
                        0,
                        min(size - 1, idx + (1 if key == "\x06" else -1)),
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
                elif key == "e" and mode == "RESULTS" and items:
                    k, version, _ = items[idx]
                    _, text = s.rows((version,), k)[0]
                    msg = edit_in_vim(win, s.db, f"{label(k)} [{version}] {text}")
                elif key in ENTER and mode == "THEME":
                    theme_name = tuple(themes.OPTIONS)[idx]
                    replacement = themes.styles(theme_name)
                    if palette.background or replacement.background:
                        win.bkgd(" ", replacement.background)
                    palette = replacement
                    with s.db:
                        s.db.execute(
                            "INSERT OR REPLACE INTO settings VALUES('theme',?)",
                            (theme_name,),
                        )
                    mode, msg = "NORMAL", f"Theme: {theme_name}"
                elif key in ENTER and mode == "SEARCH" and preview_counts is not None:
                    s.remember_search(buf)
                    last_query = buf
                    msg = "No matching verses"
                elif key in ENTER and mode == "STUDY" and items:
                    if (
                        isinstance(study_terms[idx], dict)
                        and "alignment" in study_terms[idx]
                    ):
                        from lexpane import show

                        target = show(
                            win,
                            s.db,
                            s.k,
                            study_terms[idx]["alignment"],
                            version=s.versions[0],
                            available=s.keys,
                            scope=s.scope,
                            set_scope=s.set_scope,
                            palette=palette,
                        )
                        if target is not None:
                            s.jump(s.versions, target)
                            mode, offset = "NORMAL", 0
                        continue
                    parent_study = items, study_terms, idx
                    selected = study_terms[idx]
                    if isinstance(selected, dict):
                        hits = s.linked_verses(selected["strong"], original=True)
                    else:
                        term, res = selected
                        hits = s.linked_verses(term, res)
                    s.set_hits(hits)
                    items, idx, mode = hits, 0, "RESULTS"
                    msg = f"{len(hits)} linked verses"
                elif key in ("q", "?") or key in ENTER and mode in ("HELP", "STUDY"):
                    mode = "NORMAL"
                continue
            if mode in ("COMMAND", "SEARCH"):
                if key in ("\x06", "\x02") and mode == "COMMAND":
                    options = completions(s, buf)
                    if options:
                        completion_idx = (
                            completion_idx + (1 if key == "\x06" else -1)
                        ) % len(options)
                        msg = options[completion_idx] + "  Tab completes"
                    continue
                key = {"KEY_UP": "\x10", "KEY_DOWN": "\x0e"}.get(key, key)
                if key in ("\x10", "\x0e"):
                    if not history_choices:
                        setting = (
                            "search_history" if mode == "SEARCH" else "command_history"
                        )
                        history_choices = [
                            buf,
                            *(
                                text
                                for text in s.prompt_history(setting)
                                if text != buf
                            ),
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
                    submitted = buf.strip()
                    history_pos, history_choices = 0, []
                    if submitted:
                        s.remember_prompt("command_history", submitted)
                    cmd, _, arg = submitted.partition(" ")
                    if cmd in ("versions", "use"):
                        vs = [edition(s.db, v.strip()) for v in arg.split(",")]
                        s.jump(vs, s.k)
                    elif cmd in BIBLE_HUB_SECTIONS:
                        if arg.strip():
                            raise ValueError(f":{cmd} opens the current verse")
                        book, chapter, verse = parts(s.k)
                        slug = (
                            "songs"
                            if book == 22
                            else names[book].lower().replace(" ", "_")
                        )
                        section = BIBLE_HUB_SECTIONS[cmd]
                        url = f"https://biblehub.com/{section}/{slug}/{chapter}-{verse}.htm"
                        if not webbrowser.open_new_tab(url):
                            msg = f"Could not open browser: {url}"
                    elif cmd in ("scope", "sc"):
                        s.set_scope(arg)
                        msg = f"Search scope: {s.scope or 'all books'}"
                    elif cmd in ("theme", "th"):
                        items = [
                            f"{name} · {description}"
                            + (" (active)" if name == theme_name else "")
                            for name, description in themes.OPTIONS.items()
                        ]
                        mode, idx = "THEME", tuple(themes.OPTIONS).index(theme_name)
                        msg = "j/k choose  Enter apply  Esc cancel"
                        continue
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
                        for entry in lexical.definitions(s.db, arg):
                            items.append(
                                f"{entry['strong']} · {entry['lemma']} [{entry['source']}] {entry['definition'] or entry['derivation']}"
                            )
                            study_terms.append({"strong": entry["strong"]})
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
                if key not in ("\x10", "\x0e"):
                    history_pos, history_choices = 0, []
                if mode == "SEARCH":
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
            if key not in ("J", "K", "L", "e", "u", "\x12"):
                offset = 0
            if key in ("g", "m", "'"):
                pending = key
            elif key == "L":
                from lexpane import show

                target = show(
                    win,
                    s.db,
                    s.k,
                    version=s.versions[0],
                    available=s.keys,
                    scope=s.scope,
                    set_scope=s.set_scope,
                    palette=palette,
                )
                if target is not None:
                    s.jump(s.versions, target)
                    offset = 0
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
            elif key in ("u", "\x12"):
                undoing = key == "u"
                source, destination = (
                    (s.undo_locations, s.redo_locations)
                    if undoing
                    else (s.redo_locations, s.undo_locations)
                )
                if source:
                    for _ in range(min(n, len(source))):
                        destination.append((s.versions, s.k))
                        s.restore(source.pop())
                    previous_location = None
                    offset = 0
                else:
                    msg = f"No location to {'undo' if undoing else 'redo'}"
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
                history_pos, history_choices = 0, []
                if mode == "SEARCH":
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
            elif key == "e":
                msg = edit_in_vim(win, s.db, s.selected_text())
            elif key == "y":
                tool = next(
                    (v for v in ("pbcopy", "wl-copy", "xclip") if shutil.which(v)), None
                )
                if not tool:
                    raise ValueError("Install pbcopy, wl-copy or xclip")
                subprocess.run(
                    [tool] + (["-selection", "clipboard"] if tool == "xclip" else []),
                    input=s.selected_text().encode(),
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
                if word is not None:
                    for mapping in lexical.aligned(s.db, s.versions[0], s.k, word + 1):
                        items.append(
                            f"Original token {mapping[1]} [{mapping[0]}] · alignment: {mapping[2]}"
                        )
                        study_terms.append({"alignment": mapping})
                preferred_word = None
                mode, idx, msg = (
                    "STUDY",
                    0,
                    f"{len(items)} linked entries  Enter inspect  Esc returns"
                    if items
                    else "No linked annotations for this selection · Esc then L for source verse",
                )
        except (
            ValueError,
            OSError,
            subprocess.SubprocessError,
            webbrowser.Error,
        ) as error:
            msg = str(error)
        finally:
            if previous_location is not None and previous_location != (s.versions, s.k):
                s.undo_locations.append(previous_location)
                s.redo_locations.clear()
