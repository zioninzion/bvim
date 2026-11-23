# bvim

An offline Bible reader for the terminal. Open a passage, follow indexed search hits, compare editions, and return to your original verse using one jump history.

## Start reading

Use Python 3.9 or newer with curses and SQLite FTS5 on macOS or Linux. Run the executable from this directory. To make it available as `bvim`, add this directory to PATH. The project name avoids claiming the generic `bible` command. There are no Python package dependencies.

```sh
export PATH="$PWD:$PATH"
bvim import "/path/to/RcV(3).txt" --name RcV --license "User supplied"
bvim mat 3:5
bvim mat 3:5-8
bvim 'Mat 3:5; John 3:16'
bvim eternal life
```

After the first import, `bvim` opens the reader at the last saved location. In the reader, press **l** to reach John 4:1, then **Ctrl-O** to return. Type `/"eternal life"` and press Enter to browse the results. Press **4j** then **Enter** to open the fifth result. **R** reopens the list. Use **ma** to mark a verse and **'a** to return there in a later session. Type **:Jn3:16** then Enter to jump from anywhere. **?** shows the bindings. **q** exits.

Import a second local file under its own ID and enter `:versions RcV,ASV` to compare the same numeric reference. **|** switches between stacked and column layouts. **D** marks wording changes relative to the first edition. Missing verses are labeled individually. A matching numeric reference can correspond to different material across versifications.

## CLI reference

| Command | Purpose |
|---|---|
| `bvim [tui [REF]] [-V A,B]` | Interactive reader. Launch with no arguments to resume. Use the explicit tui subcommand with flags. |
| `bvim INPUT` | In a terminal, open a reference, highlight a range, or browse search results for a reference list or text. Redirect output for plain CLI results. |
| `bvim read REF [-V A,B]` | Print a verse, chapter, book, range, or quoted semicolon-separated list. |
| `bvim compare REF --versions A,B,C [--diff]` | Compare the union of references. Diff output marks deletions as `[-…-]` and additions as `[+…+]`. |
| `bvim search QUERY [-V A,B] [--in SCOPE] [--limit N]` | One row per verse/edition. Add `--count` for total hits and distinct verses across all results. FTS accepts `--sort exact\|reference\|relevance`. |
| `bvim search QUERY --mode regex\|glob\|fuzzy [--tolerance N]` | Explicit pattern scans within the selected corpus. |
| `bvim import FILE --name ID [--source SOURCE] [--license TERMS] [--versification SCHEME] [--replace]` | Validate and install a local edition or atomically update it. |
| `bvim versions`, `bvim use ID`, `bvim remove ID` | List metadata, select the default, uninstall an edition and its dependent marks/links. |
| `bvim export ID > edition.txt` | Recreate the imported UTF-8 file in source order. |
| `bvim reindex` | Rebuild the full-text index from stored verses in a transaction. |
| `bvim resource FILE --name ID --source SOURCE --license TERMS` | Install a local study resource. |
| `bvim lookup TERM`, `bvim occurrences TERM [--version ID] [--in REF] [--morph CODE]` | Read attributed definitions or list distinct linked verses. |
| `bvim remove-resource ID` | Remove an installed resource and its links. |
| `bvim history` | Print the jump path captured when the last reader session exited. |

Read, compare and search accept `--format text|md|jsonl`. JSONL contains translation, book_id, book, chapter, verse and text. Missing comparison text is null. `--diff` explicitly requests annotated text. Exit 0 means success, 1 means an empty search/lookup/occurrence list and 2 reports an invalid request or data error on stderr. Plain output contains no color codes. Source the matching file under `completions/` for shell subcommand completion (zsh requires compinit).

```sh
bvim 'John 3:16; Rom 8:2' --format md
bvim search '"eternal life"' --in 'John;1 John;2 John;3 John;Rev' --format jsonl
bvim search 'faith AND works' --in NT
bvim search 'NEAR("eternal life" believe, 5)'
bvim search 'believ*' --versions RcV
bvim search 'beli?ve*' --mode glob
bvim search 'begining' --mode fuzzy --tolerance 1 --in Gen
```

Both `/` and `bvim search` accept reference lists, for example `Jn 3:16, 18-21; Rom 8.1-2`. Enter to browse the results in the requested order, then Enter on a verse to open it. Overlapping references appear once per translation. Use `ref: John; Romans` to search for entire books. A bare book name such as `John` still searches verse text.

### References and search semantics

The canonical book ID runs from Genesis (1) to Revelation (66). Book names, common aliases and unique prefixes ignore case, periods and whitespace. Ambiguous input returns suggestions. Fuzzy suggestions require an explicit completion. A bare book or chapter selects its available rows. Explicit verse endpoints delimit inclusive ranges, including cross-chapter and cross-book ranges. The TUI lands on the first verse of a reference. The reader centers the active verse between the header and footer. Both `John 3.4` and `John 3:4` open the same verse. In the reader, `:3.4` jumps within the current book. A bare number in its command prompt means a verse in the current chapter. Spell out the chapter for single-chapter books, e.g. `Jude 1:5`.

By default, a whole-verse match ranks first, followed by contiguous token phrases, then verses containing the words separately. A prefix search prioritizes the complete token, and fuzzy search puts exact words first. Ties follow reference order. Use `:sort exact` to restore this ordering in the reader.

Default search uses SQLite FTS5 unicode61 tokenization. Spaces imply AND. Double quotes delimit a token phrase (case and punctuation can normalize). Uppercase AND, OR, binary NOT, parentheses, trailing prefix stars and FTS5 NEAR groups are supported. NEAR measures intervening tokens and permits either order. `--in` accepts OT, NT, or a semicolon-separated union of references. The explicit regex mode searches verse text with Python’s case-insensitive regex engine. Glob mode matches a whole Unicode word with shell pattern syntax. Fuzzy mode compares a single word using Levenshtein distance 0–3. These three CLI modes scan the chosen range. [FTS5 query syntax](https://sqlite.org/fts5.html#full_text_query_syntax)

### Reader keys

| Keys | Action |
|---|---|
| j / k, ↓ / ↑ | Next / previous available verse, across book and chapter boundaries. Count prefixes multiply movement. |
| h / l, [ / ] | Previous / next chapter, previous / next book. Land on its first available verse. |
| gg / G, 16G | Edition start / end, or verse 16 in this chapter. |
| Ctrl-D / U, Ctrl-F / B (all with Ctrl) | Half / full screen in visible verse units. |
| J / K | Scroll within a long wrapped verse. |
| : | Reference or command. Ctrl-W deletes the preceding word. Ctrl-U clears the line. Arrows choose a suggested completion, Tab inserts it, Enter executes. |
| / | Live indexed search. Reopening / restores the query, including edits dismissed with Esc in this session. Ctrl-P / Ctrl-N recall older / newer queries. The last 100 distinct submitted queries persist across sessions. Ctrl-W deletes the preceding word. Ctrl-U clears the query. Matches are underlined and highlighted in yellow on color terminals, both in results and while reading. Arrows preview results. Enter finishes typing and focuses the full results list. Use j/k or a count such as 4j, then Enter to open the selected verse. Esc returns to the original passage. The preview shows up to 101 rows. The header counts all hits and distinct verse references in scope. Each highlighted match region counts once per edition, including repeated matches in a verse. Overlapping FTS matches share one highlight. |
| n / N, R | Next / previous accepted search hit (counts supported), reopen full result list. In a list j/k or arrows move, Enter opens. |
| Ctrl-O / Ctrl-I | Back / forward across jumps. Tab also sends Ctrl-I in a terminal. Ordinary j/k motion adds no jumps. |
| m followed by a letter, ' followed by that letter | Set / recall persistent verse mark. |
| v, y | Start/end verse selection, copy with references and edition IDs. Uses pbcopy, wl-copy or xclip. |
| w / b, Enter | Move the cyan word highlight forward / backward in the first edition. Verse motions keep the same word number, using the last word of a shorter verse until the preferred position is available again. Enter inspects annotations at that exact token. Search matches within the selected word keep their underline. Enter without a word shows passage-linked entries. |
| :scope REF, :sort relevance | Filter future searches by corpus or passage and order by relevance. Bare :scope clears the filter. :sort reference restores canonical order. |
| x / p | Open the current verse on Bible Hub in your browser for original-language text analysis or parallel translations. |
| :lookup TERM, :occ TERM | Show lexical/dictionary entries or browse linked verses. Enter on an entry opens that resource’s linked verses. |
| :use ID, :versions A,B | Switch edition or synchronize a comparison at the cursor. |
| #, H, z | Toggle verse numbers, book and chapter headings and expanded spacing. |
| vertical bar, D | Toggle column layout or wording differences. Narrow columns fall back to stacking. |
| ?, Esc, q | Help, cancel/close, quit. In a result/help/study list q closes the list. |

The reader allows 10 ms for the remaining bytes of an arrow or function key after Escape. Set `ESCDELAY` (milliseconds) to override this on slower connections.

## Storage, data and verification

The default database is `~/.local/share/bvim/library.db`. Set `BVIM_DB` to choose another file. A new library starts empty. Local imports remain outside this repository. See [data formats and recovery](docs/data.md), [architecture and draft audit](docs/design.md), [comparison of five implementations](docs/research.md), [measured workflows](docs/performance.md) and the [prioritized roadmap](docs/roadmap.md).

```sh
python3 -m unittest discover -s tests -v
RCV_FIXTURE="/path/to/RcV(3).txt" python3 -m unittest discover -s tests -v
python3 bench.py "/path/to/RcV(3).txt"
```

The original prompt-driven reader and external-link actions remain available through `python3 legacy_ui.py` with the original translation/helper modules on PYTHONPATH. The new entry point also accepts `--print` and `--search`; its default search semantics are indexed token expressions.
