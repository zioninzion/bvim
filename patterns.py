"""Opt-in scan search for patterns outside FTS5's token grammar."""

import re
from fnmatch import translate
from functools import lru_cache

from library import SearchCounts, scopes


def distance_within(word, target, maximum):
    if abs(len(word) - len(target)) > maximum:
        return False
    previous = list(range(len(target) + 1))
    for i, left in enumerate(word, 1):
        current = [i]
        for j, right in enumerate(target, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right))
            )
        if min(current) > maximum:
            return False
        previous = current
    return previous[-1] <= maximum


def _scan(db, versions, query, scope, mode, tolerance, count_all):
    tokens = re.compile(r"\w+", re.UNICODE)
    if mode == "fuzzy":
        target = query.casefold()
        if not tokens.fullmatch(target) or not 0 <= tolerance <= 3:
            raise ValueError("Fuzzy search takes one word and tolerance 0–3")

        @lru_cache(8192)
        def word_matches(word):
            return distance_within(word, target, tolerance)

        def matches(text):
            return (
                word for word in tokens.findall(text.casefold()) if word_matches(word)
            )
    elif mode == "glob":
        pattern = re.compile(translate(query.casefold()))

        def matches(text):
            return (
                word
                for word in tokens.findall(text.casefold())
                if pattern.fullmatch(word)
            )
    else:
        try:
            matches = re.compile(query, re.IGNORECASE).finditer
        except re.error as e:
            raise ValueError(str(e)) from e
    limits = scopes(scope)
    allowed = ",".join("?" for v in versions)
    restriction = " OR ".join("k BETWEEN ? AND ?" for pair in limits)
    rows = db.execute(
        f"SELECT k,version,text FROM verses WHERE version IN ({allowed}) AND ({restriction}) ORDER BY k,version",
        (*versions, *(k for pair in limits for k in pair)),
    )
    for row in rows:
        occurrences = matches(row[2])
        count = (
            sum(1 for _ in occurrences)
            if count_all
            else int(next(occurrences, None) is not None)
        )
        if count:
            yield row, count


def scan(db, versions, query, scope, limit, mode, tolerance, sort="exact"):
    deferred = []
    exact = query.casefold()
    emitted = 0
    for row, _ in _scan(db, versions, query, scope, mode, tolerance, False):
        if (
            sort == "exact"
            and mode == "fuzzy"
            and exact not in re.findall(r"\w+", row[2].casefold())
        ):
            if limit is None or len(deferred) < limit:
                deferred.append(row)
            continue
        yield row
        emitted += 1
        if emitted == limit:
            return
    yield from deferred[: None if limit is None else limit - emitted]


def scan_counts(db, versions, query, scope, mode, tolerance):
    refs = set()
    hits = 0
    for (k, _, _), count in _scan(db, versions, query, scope, mode, tolerance, True):
        refs.add(k)
        hits += count
    return SearchCounts(hits, len(refs))
