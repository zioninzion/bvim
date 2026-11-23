"""Wrap displayed text to terminal cells while keeping stored text intact."""

import re
import unicodedata
from difflib import SequenceMatcher
from itertools import zip_longest

import styled


def cells(ch):
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1


def width(text):
    return sum(map(cells, text)) if not text.isascii() else len(text)


def wrap(text, limit):
    limit = max(1, limit)
    line = ""
    used = 0
    for word in text.split():
        size = width(word)
        if used and used + size + 1 > limit:
            yield line
            line, used = "", 0
        if used:
            line += " "
            used += 1
        if size > limit:
            for ch in word:
                n = cells(ch)
                if used and used + n > limit:
                    yield line
                    line, used = "", 0
                line += ch
                used += n
        else:
            line += word
            used += size
    yield line


def display_wrap(text, limit):
    if not isinstance(text, styled.MatchedText):
        yield from wrap(text, limit)
        return
    # Map collapsed whitespace back to the FTS spans before slicing visual lines.
    tokens = list(re.finditer(r"\S+", text))
    parts = []
    end = 0
    for token in tokens:
        if parts:
            gap = styled.section(text, end, end + 1)
            parts.append(
                styled.MatchedText(" ", [(0, 1)])
                if isinstance(gap, styled.MatchedText)
                else " "
            )
        parts.append(styled.section(text, *token.span()))
        end = token.end()
    normalized = styled.join(parts)
    offset = 0
    for line in wrap(normalized, limit):
        if normalized[offset : offset + 1] == " ":
            offset += 1
        yield styled.section(normalized, offset, offset + len(line))
        offset += len(line)


def columns(rows, limit):
    sep = "  │  "
    size = (limit - (len(rows) - 1) * len(sep)) // len(rows)
    if size < 20:
        for v, t in rows:
            yield from display_wrap(styled.join((f"[{v}] ", t)), limit)
    else:
        for row in zip_longest(
            *(display_wrap(styled.join((f"[{v}] ", t)), size) for v, t in rows),
            fillvalue="",
        ):
            parts = []
            for cell in row:
                if parts:
                    parts.append(sep)
                parts.extend((cell, " " * (size - width(cell))))
            line = styled.join(parts)
            yield styled.section(line, 0, len(line.rstrip()))


def differences(base, text):
    # Preserve the compared edition's whitespace inside each marked span.
    a = re.findall(r"\S+\s*", base)
    b = [styled.section(text, *m.span()) for m in re.finditer(r"\S+\s*", text)]
    matcher = SequenceMatcher(
        None, [w.rstrip() for w in a], [w.rstrip() for w in b], autojunk=False
    )
    output = []
    for tag, i, j, k, l in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            output.append("[-" + "".join(a[i:j]).rstrip() + "-] ")
        if tag in ("replace", "insert"):
            added = styled.join(b[k:l])
            output.extend(("[+", styled.section(added, 0, len(added.rstrip())), "+] "))
        if tag == "equal":
            output.extend(b[k:l])
    line = styled.join(output)
    return styled.section(line, 0, len(line.rstrip()))
