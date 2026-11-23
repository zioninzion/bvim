"""Reader color palettes and their monochrome equivalents."""

import curses
from typing import NamedTuple

DEFAULT = "high-contrast"
OPTIONS = {
    DEFAULT: "Light text on black",
    "light": "Dark text on white",
    "terminal": "Terminal background with colored highlights",
    "monochrome": "Terminal colors with bold, reverse, and underline",
}


class ThemeStyles(NamedTuple):
    background: int = 0
    selected: int = 0
    match: int = curses.A_BOLD | curses.A_UNDERLINE
    word: int = curses.A_BOLD

    def row(self, attr):
        if attr & curses.A_REVERSE and self.selected:
            return (attr & ~curses.A_REVERSE) | self.selected | curses.A_BOLD
        return attr | self.background


def styles(name):
    fallback = ThemeStyles()
    try:
        if name == "monochrome" or not curses.has_colors():
            return fallback
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_CYAN)
        match = fallback.match | curses.color_pair(1)
        word = fallback.word | curses.color_pair(2)

        if name in (DEFAULT, "light"):
            fg, bg = curses.COLOR_WHITE, curses.COLOR_BLACK
            if name == "light":
                fg, bg = bg, fg
            curses.init_pair(3, fg, bg)
            curses.init_pair(4, bg, fg)
            return ThemeStyles(curses.color_pair(3), curses.color_pair(4), match, word)
        return ThemeStyles(match=match, word=word)
    except curses.error:
        return fallback
