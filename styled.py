"""Plain display text with optional search-match character ranges."""

import re
from uuid import uuid4

# Per-process delimiters keep literal brackets in an edition ordinary text.
_marker = uuid4().hex
START = f"<{_marker}>"
END = f"</{_marker}>"


class MatchedText(str):
    def __new__(cls, text, spans, selected=()):
        result = super().__new__(cls, text)
        merged = []
        for start, end in spans:
            if merged and merged[-1][1] == start:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        result.spans = tuple(merged)
        result.selected = tuple(selected)
        return result


def from_fts(markup):
    chunks = markup.split(START)
    if len(chunks) == 1:
        return markup
    pieces = [chunks[0]]
    offset = len(chunks[0])
    spans = []
    for chunk in chunks[1:]:
        matched, _, tail = chunk.partition(END)
        spans.append((offset, offset + len(matched)))
        pieces.extend((matched, tail))
        offset += len(matched) + len(tail)
    return MatchedText("".join(pieces), spans)


def select_word(text, index):
    for i, token in enumerate(re.finditer(r"\S+", text)):
        if i == index:
            return MatchedText(text, getattr(text, "spans", ()), [token.span()])
    return text


def section(text, start, end):
    value = text[start:end]
    if isinstance(text, MatchedText):

        def clipped(ranges):
            return [
                (max(a, start) - start, min(b, end) - start)
                for a, b in ranges
                if a < end and b > start
            ]

        spans, selected = clipped(text.spans), clipped(text.selected)
        if spans or selected:
            return MatchedText(value, spans, selected)
    return value


def join(parts):
    offset = 0
    spans = []
    pieces = []
    selected = []
    for part in parts:
        pieces.append(part)
        if isinstance(part, MatchedText):
            spans.extend((offset + a, offset + b) for a, b in part.spans)
            selected.extend((offset + a, offset + b) for a, b in part.selected)
        offset += len(part)
    value = "".join(pieces)
    return MatchedText(value, spans, selected) if spans or selected else value
