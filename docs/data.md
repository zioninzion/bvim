# Local data

## Verse files

Supply a UTF-8 plain-text file containing one complete verse per line. The import grammar is a recognized book name, horizontal whitespace, decimal chapter, colon, decimal verse, one space or tab, then nonblank text. The first separator after the verse belongs to the reference prefix. All additional whitespace belongs to the text. LF, CRLF and a final line without a newline round-trip. Identifiers support periods and spaces, including S.S., 1 Sam. and 1 Kings.

The importer streams lines, computes SHA-256, resolves canonical IDs and inserts verses and full-text postings in a single transaction. A unique edition/location constraint rejects duplicates even under different book aliases. The original line ordinal, reference prefix, text and ending permit a byte-exact export. Readers use a numeric location ordered by canonical book, chapter and verse. Chapters and verses each occupy three decimal digits. Unsupported suffixed or combined identifiers fail validation. Editions can omit a verse or use a different numbered verse. The application never splits or shifts text to force a correspondence.

Validation reports the source line for malformed records, rejects unknown/ambiguous books, and reports discontinuities in source order and chapter/verse numbering. Numeric gaps are warnings since an omission can be intentional. The file alone cannot establish whether a final verse, final chapter or whole book should have been present. The RcV integration test separately asserts its known coverage and endpoints. Use `--versification` for a source-defined scheme and `--source` for the edition/release identifier. Scheme labels document the source’s numbering and do not remap it.

An existing translation requires `--replace`. A failed replacement restores text, metadata and index. An edition carrying study links can be replaced by identical bytes. For changed text, remove the dependent resource first, then revalidate it against the new edition. Removing an edition removes its dependent marks and associations. Retain original files for reinstallation. A database backup can be made with SQLite’s online backup command or by copying the closed database after all bvim processes have exited. Use `bvim reindex` for a damaged FTS index when the underlying verse table remains readable. Preserve a damaged library separately before restoring from a backup.

Schema versions 1 and 2 migrate through version 3. The version 4 migration adds lexical tables and indexes in a transaction. See [original-language resources and alignment import](lexical.md). Version 5 adds an FTS5 trigram index for partial search when SQLite supports that tokenizer. Older SQLite builds and one- or two-character queries use a scoped scan for substrings. Plain words of three or more letters also check for matches with one extra letter within the matched word. A newer unknown schema produces an error. The version list shows default marker, ID, source, license, digest and versification.

## Study resources

Each JSON line contains a unique term within its named resource, a kind (`lexicon`, `dictionary` or `cross-reference`), a body and optional references. A term can be a Greek/Hebrew lemma, a Strong’s identifier or a topical headword. Put published transliteration, glosses and definitions in the body with their attribution. Each reference names an installed edition and a single existing verse. Morphology codes retain the provider’s vocabulary. To associate evidence with a particular word, include both a one-based whitespace-token position and its exact surface, including punctuation. Validation rejects a mismatched surface. Passage-level links remain available when word alignment is absent.

For a reproducible exercise, install the following explicitly synthetic data in a temporary library. The placeholder annotations demonstrate the mechanics only.

```sh
export BVIM_DB="$(mktemp -d)/demo.db"
printf 'John 1:1 token sample\nJohn 1:2 other token\n' > "${BVIM_DB%/*}/demo.txt"
bvim import "${BVIM_DB%/*}/demo.txt" --name DEMO
cat > "${BVIM_DB%/*}/demo.jsonl" <<'JSON'
{"term":"sample-entry","kind":"lexicon","body":"Synthetic annotation for testing","references":[{"version":"DEMO","ref":"Jn 1:1","position":1,"surface":"token","morph":"TEST"},{"version":"DEMO","ref":"Jn 1:2","position":2,"surface":"token","morph":"TEST"}]}
JSON
bvim resource "${BVIM_DB%/*}/demo.jsonl" --name demo --source "Synthetic exercise" --license "Example"
bvim lookup sample-entry
bvim occurrences sample-entry --version DEMO --morph TEST
bvim tui Jn1:1
```

Press w, Enter, Enter, j, Enter to follow the selected token to the other linked verse. Ctrl-O returns to the source verse. The occurrences list counts distinct linked verses. An English search hit alone supplies no original-language evidence.

## Interactive setup catalog

A terminal launch opens setup when the active library has no translations. Select translations and resources by number. Separate numbers or inclusive ranges with spaces or commas, such as `1-3,5`. Selecting a number again removes it from the queue. Press `i` to install the selections or `c` to clear them. Type an abbreviation such as `WEB` or a name such as `American Standard Version` to filter the list, then pick a number. Press Enter while filtering to show the full menu. Press `l` to select local verse-per-line files. Enter a path, a glob such as `*.txt`, or a regex such as `re:^(KJV|YLT)\.txt$`. Patterns match filenames in the current directory. A blank entry lists `.txt` files for selection by number or range. The filename stem becomes the translation ID, with spaces and other unsupported characters replaced by underscores. Enter finishes setup once a translation is installed. Use `bvim setup` to add resources to any library. Successful imports remain installed if another item fails. Failed items stay selected for retry. Quitting discards pending selections.

The catalog translations use SHA-256-verified XML files from [thiagobodruk/bible at revision 4c8b8a](https://github.com/thiagobodruk/bible/tree/4c8b8a4a7bd75fee381e1b55523b152191d6a1a5/xml). Each edition records its exact source URL and the text’s rights notice. KJV is public domain outside the UK, where Crown rights apply. [ASV](https://ebible.org/asv/) · [WEB](https://worldenglish.bible/) · [BSB](https://berean.bible/licensing.htm) · [KJV](https://ebible.org/eng-kjv2006/copr.htm) · [Darby](https://ebible.org/engDBY/copyright.htm) · [YLT](https://ebible.org/engylt/copyright.htm) · [UK Crown rights](https://assets.cambridge.org/97805212/28626/copyright/9780521228626_copyright_info.pdf)

The main menu shows the public-domain download options. Manual search also indexes the other editions named in the pinned upstream README. Select a result marked `local file required` to import a verse-per-line file you have permission to use. For example, search for `ESV` or `English Standard Version`. Crossway’s digital permissions govern full-text use. [Crossway permissions](https://www.crossway.org/permissions/)

The upstream XML provides numeric chapter and verse labels. Some of its labels differ from the published editions because numbering can shift after an omission. For example, the ASV and BSB snapshots label the story’s next verse as John 5:4 after omitting the conventional verse 4. The installer preserves the XML labels, and `bvim versions` displays the source-specific numbering scheme. Use a locally supplied edition with published numbering when precise reference parity matters.
