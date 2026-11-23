# Reader design and draft audit

The supplied Python reader has useful stacked comparisons, short local references, contiguous passage traversal and readline history. Its menu accepts a book number, chapter and verse in three prompts. Its reader retains direction (f/r) and unit (b/c/v) across Enter presses. Link commands delegate to external applications. Seven translation dictionaries and four helper modules load before argument parsing. The supplied checkout fails even for --help at the first missing import. NENT controls the available locations for every edition. Case-folded substring search visits every verse and translation even after reaching the display limit.

Keep the original program available as legacy_ui.py. Keep Python, the draft’s tuple ordering convention and stacked comparison. Replace the data dependency with an import-time SQLite index and a composite translation/location key. One transaction owns replacement, validation and index updates. Retain the original reference spelling and source order separately from the canonical location. User data stays outside the checkout. Compare the union of available numeric references and label gaps. Numeric correspondence alone cannot establish textual alignment.

The new reader opens directly at the saved location. Normal mode owns the verse cursor. Counts multiply j/k, h/l step chapters, brackets step books, gg/G span the edition. A command line accepts a reference, a local verse number or a translation command. Search is a temporary picker with text previews; accepting a hit records one jump and keeps its result set for n/N. Escape cancels pending input in place. Marks retain the edition. Back and forward record jump origins, including the exact location reached by ordinary scrolling. Use terminal-native curses with no background redraw loop. A single-column layout accommodates narrow terminals and long translations.

The highest-impact slice is native import, direct read, indexed search, keyboard navigation and translation comparison. FTS5 provides transactional search and retrieval in one portable file. A separate Tantivy service or native extension would add an index consistency boundary. Benchmark SQLite first. Use translation-specific, source-identified resources before enabling original-language study.

## Implemented boundaries

| Module | Responsibility |
|---|---|
| refs.py | Canonical 1–66 book table, aliases, ambiguity, suggestion ranking, reference limits and display names. |
| library.py | Schema negotiation, streaming transactions, edition selection, ordered reads, FTS and restricted corpora. |
| patterns.py | Explicit regex, glob and edit-distance scans. |
| study.py | Source-specific entries and edition-linked evidence, validated surface positions, occurrence lists. |
| lexdata.py | Revision and digest catalog, staged downloads, validated TSV/JSON dictionary adapters, atomic installation. |
| lexical.py | Additive schema, source-token identities, lemma and morphology indexes, definition joins, bounded occurrence windows. |
| lexcli.py, lexpane.py | Command formats and a verse-local curses overlay. Reader state owns edition selection, search and jump history. |
| reader.py | Canonical cursor, bounded verse-body cache, jump stacks, named marks, live prompts, comparison and selection. |
| layout.py | Terminal-cell wrapping, column fallback and token differences. |
| ui.py | CLI command parsing, pipeline formats, translation management and TUI entry. |

Both frontends call the same passage and search functions. The TUI caches sorted location arrays per active edition combination and uses binary search for chapter/book jumps. On-demand verse bodies stay in a 512-entry cache. A blocking terminal read keeps idle CPU use low. The results picker previews up to 101 canonically ordered hits, then obtains the complete list when accepted. Explicit regex and fuzzy scans run in the CLI. Text, FTS and user metadata share SQLite transaction semantics. Session positions are saved on reader exit, marks on assignment.

Column comparison uses the union of edition coordinates. The optional token diff uses SequenceMatcher against the first edition and preserves source data separately. Stacked views remain readable below 20 cells per column. The display uses terminal default colors and reverse video. UTF-8 text stays in logical order. Presentation of bidirectional scripts also depends on the terminal emulator.
