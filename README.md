# bvim

An offline Bible reader for the terminal. Open a passage, follow indexed search hits, compare editions, and return to your original verse using one jump history.

## Start reading

Use Python 3.9 or newer with curses and SQLite FTS5 on macOS or Linux. From the project directory, add the executable to your shell’s path and launch it. There are no Python package dependencies.

```sh
export PATH="$PWD:$PATH"
bvim
```

On the first interactive launch of an empty library, choose a translation by number, or type its abbreviation or name to filter the list. Enter several numbers together, such as `1,5,6`, or an inclusive range like `1-11`, or build a selection across searches. Press `i` to install the selected translations and study resources, then Enter to open the reader. Press `l` to select local verse-per-line files. Enter a path, a glob such as `*.txt`, or a regex such as `re:^(KJV|YLT)\.txt$`. Patterns match filenames in the current directory. A blank entry lists `.txt` files for selection by number or range. The filename stem becomes the translation ID, with spaces and other unsupported characters replaced by underscores. Run `bvim setup` to reopen the installer later. Catalog items download when you start installation and are available offline after installation.

The default menu offers ASV, WEB, BSB, KJV, Darby and YLT from a pinned [thiagobodruk/bible snapshot](https://github.com/thiagobodruk/bible/tree/4c8b8a4a7bd75fee381e1b55523b152191d6a1a5). Search by abbreviation or name to find other upstream editions, such as ESV or NIV, and import them from a local file. Catalog downloads use the collection’s verse numbering. Some verses shift after an omission, so use a local edition file if you need published verse numbering. [Import formats and source details](docs/data.md)

| Run in a terminal | What opens |
|---|---|
| `bvim` | Resume the last reading location. |
| `bvim mat 3:5` | Open Matthew 3:5 in the reader. |
| `bvim mat 3:5-8` | Center Matthew 3:5 and select verses 5–8. Press `y` to copy the passage with references or Esc to clear the selection. |
| `bvim 'Mat 3:5; John 3:16'` | Browse those references in the supplied order. Press Enter to open the selected verse. |
| `bvim eternal life` | Browse text search results. Exact phrases rank ahead of separated terms. |

Quote reference lists containing semicolons so the shell passes the whole list to bvim. The same quoting works for a shell variable:

```sh
passage='Jn 3:16, 18-21; Rom 8.1-2'
bvim "$passage"
```

For a short navigation exercise, run `bvim Jn 3:16`. Press `l` to reach John 4:1 and Ctrl-O to return. Type `ma` to mark John 3:16, then use `'a` to return there in a later session. Press `?` for the key reference and `q` to quit the reader.

Import a second local file under its own ID and enter `:versions ASV,KJV` to compare the same numeric reference. **|** switches between stacked and column layouts. **D** marks wording changes relative to the first edition. Missing verses are labeled individually. A matching numeric reference can correspond to different material across versifications.

## Study a verse in Greek or Hebrew

Install the two tagged texts and their dictionaries once. Afterward, lexical study works offline, including from the CLI with no translation selected.

```sh
bvim data install macula-greek
bvim data install macula-hebrew
bvim data install strongs-greek
bvim data install strongs-hebrew
bvim lex John 1:1 --word 5
bvim lex Genesis 1:1 --format jsonl
bvim occurrences G3056 --in John --count
bvim morph N-NSM --in NT
```

In the reader, press **L** at a verse. Move with **j/k** or **w/b**, press **Enter** for the selected token’s dictionary record, or **o** for occurrences of its lemma. **i** toggles interlinear display and **/** filters the verse. **Esc** steps back. Opening an occurrence records a normal jump, so **Ctrl-O** returns to the starting passage. The optional `macula-sblgnt` resource adds a second Greek edition. Use **Tab** inside the pane to switch source editions.

Genesis 1:1 has seven written words and eleven analysis rows in MACULA WLC. The first row is the prefix בְּ and the second is רֵאשִׁ֖ית. The JSONL fields `position` and `word_position` expose both levels. Instructions for alignments, source-specific morphology, licensing and maintenance are in the [lexical study guide](docs/lexical.md).

## CLI reference

| Command | Purpose |
|---|---|
| `bvim [tui [REF]] [-V A,B]` | Interactive reader. Launch with no arguments to resume. Use the explicit tui subcommand with flags. |
| `bvim INPUT` | In a terminal, open a reference, highlight a range, or browse search results for a reference list or text. Redirect output for plain CLI results. |
| `bvim read REF [-V A,B]` | Print a verse, chapter, book, range, or quoted semicolon-separated list. |
| `bvim compare REF --versions A,B,C [--diff]` | Compare the union of references. Diff output marks deletions as `[-…-]` and additions as `[+…+]`. |
| `bvim search QUERY [-V A,B] [--in SCOPE] [--limit N]` | One row per verse/edition. Add `--count` for total hits and distinct verses across all results. FTS accepts `--sort exact\|reference\|relevance`. |
| `bvim search QUERY --mode regex\|glob\|fuzzy [--tolerance N]` | Explicit pattern scans within the selected corpus. |
| `bvim setup` | Install translations and optional study resources interactively. |
| `bvim import FILE --name ID [--source SOURCE] [--license TERMS] [--versification SCHEME] [--replace]` | Validate and install a local edition or atomically update it. |
| `bvim versions`, `bvim use ID`, `bvim remove ID` | List metadata, select the default, uninstall an edition and its dependent marks/links. |
| `bvim export ID > edition.txt` | Recreate the imported UTF-8 file in source order. |
| `bvim reindex` | Rebuild the full-text index from stored verses in a transaction. |
| `bvim resource FILE --name ID --source SOURCE --license TERMS` | Install a local study resource. |
| `bvim lex REF [--word N] [--source ID] [--format text/md/jsonl]` | Analyze original-language tokens at one source reference. |
| `bvim lookup TERM` | Read dictionary entries, original-language counts and linked study resources. |
| `bvim occurrences TERM [--field FIELD] [--source ID] [--in SCOPE] [--morph CODE] [--count]` | List original tokens with their source IDs in JSONL, or select legacy translation-linked verses with `--version ID`. |
| `bvim morph CODE_OR_CATEGORY [--source ID] [--in SCOPE] [--count]` | Search tagged morphology. Both token search commands accept `--format jsonl`. |
| `bvim data list/status/verify/reindex`, `bvim data install ID [--file PATH]`, `bvim data remove ID` | Inspect, validate, index and manage local scholarly data. |
| `bvim remove-resource ID` | Remove an installed resource and its links. |
| `bvim history` | Print the jump path captured when the last reader session exited. |

Read, compare and search accept `--format text|md|jsonl`. JSONL contains translation, book_id, book, chapter, verse and text. Missing comparison text is null. `--diff` explicitly requests annotated text. Exit 0 means success, 1 means an empty search/lookup/occurrence list and 2 reports an invalid request or data error on stderr. Plain output contains no color codes. Source the matching file under `completions/` for shell subcommand completion (zsh requires compinit).

```sh
bvim 'John 3:16; Rom 8:2' --format md
bvim search '"eternal life"' --in 'John;1 John;2 John;3 John;Rev' --format jsonl
bvim search 'faith AND works' --in NT
bvim search 'NEAR("eternal life" believe, 5)'
bvim search 'believ*' --versions ASV
bvim search 'beli?ve*' --mode glob
bvim search 'begining' --mode fuzzy --tolerance 1 --in Gen
```

Both `/` and `bvim search` accept reference lists such as `Jn 3:16, 18-21; Rom 8.1-2`. The CLI prints the matching verses in the requested order. Overlapping references appear once per translation. Use `ref: John; Romans` to search for entire books. A bare book name such as `John` still searches verse text.

### References and search semantics

The canonical book ID runs from Genesis (1) to Revelation (66). Book names, common aliases and unique prefixes ignore case, periods and whitespace. Ambiguous input returns suggestions. Fuzzy suggestions require an explicit completion. A bare book or chapter selects its available rows. Explicit verse endpoints delimit inclusive ranges, including cross-chapter and cross-book ranges. The TUI lands on the first verse of a reference. The reader centers the active verse between the header and footer. Spaces also work: `bvim gen 3 2` opens Genesis 3:2, and `bvim gen 3 4 6` selects Genesis 3:4–6. Both `John 3.4` and `John 3:4` open the same verse. In the reader, `:3.4` jumps within the current book. A bare number in its command prompt means a verse in the current chapter. In a one-chapter book, the number is a verse. `Jud 3` means Jude 1:3 and `Jude 3-5` selects verses 3 through 5. `SOS` names Song of Songs (Song of Solomon), and `Jdg` names Judges.

By default, a whole-verse match ranks first, followed by contiguous token phrases, then verses containing the words separately. A prefix search prioritizes the complete token, and fuzzy search puts exact words first. Ties follow reference order. Use `:sort exact` to restore this ordering in the reader.

Plain searches include partial matches. A plain word of three or more letters can match with one intervening letter, so `ter` matches `father` by skipping the `h`. Adding a leading space, as in ` ter`, makes the query literal. It matches `a terminal`. Trailing spaces also count. Exact word matches rank ahead of partial-only results. Plain space-separated words still support implicit AND, and the substring search also finds a contiguous literal match. Keep spaces inside shell quotes, for example `bvim search ' ter'`.

Token search uses SQLite FTS5 unicode61. Double quotes delimit a token phrase (case and punctuation can normalize). Uppercase AND, OR, binary NOT, parentheses, trailing prefix stars and FTS5 NEAR groups are supported. NEAR measures intervening tokens and permits either order. `--in` accepts OT, NT, or a semicolon-separated union of references. The explicit regex mode searches verse text with Python’s case-insensitive regex engine. Glob mode matches a whole Unicode word with shell pattern syntax. Fuzzy mode compares a single word using Levenshtein distance 0–3. These three CLI modes scan the chosen range. [FTS5 query syntax](https://sqlite.org/fts5.html#full_text_query_syntax)

### Search in the reader

1. Press `/` to edit the previous query. Ctrl-U clears the line for a fresh search and Ctrl-W deletes the preceding word. Up or Ctrl-P recalls older queries. Down or Ctrl-N recalls newer queries. The last 100 distinct submitted queries persist across sessions.
2. Type a word, phrase, or reference list. For an exact phrase, include straight double quotes, as in `"eternal life"`. The preview shows up to 101 rows. The header counts hits across all matching editions and counts each verse reference once. Repeated highlighted regions in a verse count separately. Overlapping FTS matches share one region.
3. Press Enter to focus the full results list. Use `j`/`k` with optional counts, `gg`/`G` for first or last, and Ctrl-D/U or Ctrl-F/B to page. `u` and Ctrl-R undo and redo selection changes. Press Enter again to open the verse, or Esc to return to the passage you were reading.
4. In the reader, use `n` and `N` to visit the next or previous matching row. Press `R` to reopen the list. Matching text stays underlined and appears yellow on color terminals.

### Reader keys

| Keys | Action |
|---|---|
| j / k, ↓ / ↑ | Next / previous available verse, across book and chapter boundaries. Count prefixes multiply movement. |
| h / l, [ / ] | Previous / next chapter, previous / next book. Land on its first available verse. |
| gg / G, 16G | Edition start / end, or verse 16 in this chapter. |
| Ctrl-D / U, Ctrl-F / B (all with Ctrl) | Half / full screen in visible verse units. |
| J / K | Scroll within a long wrapped verse. |
| : | Reference or command. Up or Ctrl-P recalls older commands, and Down or Ctrl-N recalls newer ones. The last 100 distinct submitted commands persist across sessions. Ctrl-W deletes the preceding word and Ctrl-U clears the line. Ctrl-F and Ctrl-B choose a suggested completion, Tab inserts it, and Enter executes. |
| / | Edit the last query. Up and Down recall search history. Ctrl-F and Ctrl-B move the preview. Enter focuses the list, and a second Enter opens the verse. Esc retains the draft for this session. |
| n / N, R | Next / previous accepted search hit (counts supported), reopen full result list. In a list j/k or arrows move, Enter opens. |
| Ctrl-O / Ctrl-I | Back / forward across jumps. Tab also sends Ctrl-I in a terminal. Ordinary j/k motion adds no jumps. |
| `u` / Ctrl-R | Undo / redo cursor movement, including ordinary verse motions and jumps. A counted motion is one step. A new move after undo clears redo. |
| m followed by a letter, ' followed by that letter | Set / recall persistent verse mark. |
| v, y | Start/end verse selection, copy with references and edition IDs. Uses pbcopy, wl-copy or xclip. |
| `e` | Open an editable copy of the current verse, visual selection, or focused search result in Vim. Save with `:wq` to keep the edited text. Files are stored in the `edits/` directory beside the active library. |
| w / b, Enter | Move the cyan word highlight forward / backward in the first edition. Verse motions keep the same word number, using the last word of a shorter verse until the preferred position is available again. Enter inspects annotations at that exact token. Search matches within the selected word keep their underline. Enter without a word shows passage-linked entries. |
| `:scope REF`, `:sc REF` | Limit text searches and concordance results. Use `.` for the current book and `..` for the current chapter. Both commands also work inside the lexical concordance. Omit the argument to clear the limit. |
| `:sort relevance`, `:sort reference` | Order text searches by relevance or canonical reference. |
| `:theme` / `:th` | Choose high-contrast, light, terminal, or monochrome colors. Use j/k or the arrows and Enter to apply. The default uses light text on black. bvim saves your choice for future sessions. |
| L | Analyze the original-language verse locally. Use ? inside the pane for its controls. |
| `:lex` / `:lexicon` | Open the current verse’s lexicon on Bible Hub. |
| `:par` / `:parallel` | Open the current verse’s parallel translations on Bible Hub. |
| :lookup TERM, :occ TERM | Show lexical/dictionary entries or browse linked verses. Enter on an entry opens that resource’s linked verses. |
| :use ID, :versions A,B | Switch edition or synchronize a comparison at the cursor. |
| #, H, z | Toggle verse numbers, book and chapter headings and expanded spacing. |
| vertical bar, D | Toggle column layout or wording differences. Narrow columns fall back to stacking. |
| ?, Esc, q | Open help, cancel or close, or quit. In help, use j/k to scroll and [ / ] to jump between normal shortcuts, prompt controls, and colon commands. |

On exit, bvim saves up to 100 positions in each back, forward, undo, and redo list. Launch without a reference to resume the saved cursor and its history. Launching at a different passage counts as a new jump.

The reader allows 10 ms for the remaining bytes of an arrow or function key after Escape. Set `ESCDELAY` (milliseconds) to override this on slower connections.

## Storage, data and verification

The default database is `~/.local/share/bvim/library.db`. Set `BVIM_DB` to choose another file. A new library starts empty. Local imports remain outside this repository. See [data formats and recovery](docs/data.md), [architecture and draft audit](docs/design.md), [comparison of five implementations](docs/research.md), [measured workflows](docs/performance.md) and the [prioritized roadmap](docs/roadmap.md).

```sh
python3 -m unittest discover -s tests -v
RCV_FIXTURE="/path/to/RcV(3).txt" python3 -m unittest discover -s tests -v
python3 bench.py "/path/to/ASV.txt"
```

The optional `RCV_FIXTURE` test verifies the known 31,103-verse Recovery Version file and checks its export byte-for-byte. The lexical suite uses attributed extracts from pinned upstream texts. Set `BVIM_LEX_FILES` to a directory containing the five pinned downloads named by resource ID to exercise the complete offline installer. Run `python3 bench.py --lexical` against an installed library for lexical timings.

The original prompt-driven reader and external-link actions remain available through `python3 legacy_ui.py` with the original translation/helper modules on PYTHONPATH. The new entry point also accepts `--print` and `--search`; its default search semantics are indexed token expressions.
