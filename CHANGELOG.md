# Changelog

## Unreleased

- Launch directly into a passage, visual range selection, or search result list with bare command-line arguments.

- Search for multiple Bible references, ranges, or comma-separated verses in both the reader and CLI.

- Enter from live search focuses the results list. A second Enter opens the selected verse.

- Resume the previous search and recall earlier queries using Ctrl-P and Ctrl-N.

- Align wrapped verse text in a separate column beside the verse numbers.

- Open Bible Hub’s verse lexicon with x and parallel translations with p.

- Keep the preferred word position when moving between verses.

- Support Ctrl-W and Ctrl-U while editing a command or reference in the colon prompt.

- Give book transitions a bold uppercase title and label chapter boundaries in bold.

- Prioritize exact matches in CLI search and the live reader preview.

- Show full hit and distinct-verse counts during search and highlight the word selected by w/b in the reader.

- Highlighted matching words and phrases in live search results and the reader, including wrapped passages and parallel editions.

- Reduced the default Escape key delay to 10 ms.

- Added Ctrl-W and Ctrl-U for deleting a word or clearing the live search query.

- Centered the active verse with surrounding passage context and added dotted chapter/verse input for relative jumps and range endpoints.

## 0.1.0 — 2026-11-23

- Added an offline SQLite library, native transactional verse-file import, exact source export, source and license tracking, and translation management.
- Added canonical reference parsing, indexed FTS5 search, explicit pattern scans, parallel comparison, token differences and scriptable output.
- Added a curses reader with counted motions, chapter/book jumps, completion, live result previews, jump history, persistent marks, word selection and passage copying.
- Added local study resources with validated edition-specific word links, lexical/dictionary lookup, morphology filters and contextual linked passages.
- Preserved the supplied prompt reader as legacy_ui.py. Added acceptance tests, a terminal integration test, source audit and reproducible benchmarks.
