# Offline lexical study

Run the four installation commands in the README for the Nestle 1904 New Testament, WLC Hebrew Bible and both Strong’s dictionaries. Each resource installs independently. The optional second Greek edition is available with `bvim data install macula-sblgnt`. Reading, filtering, dictionary lookup and corpus searches use the local SQLite library.

## Commands and examples

```sh
bvim lex John 1:1 --word 5
bvim lex Gen 1:1 --format md
bvim lex Rom 8:2 --source macula-greek --format jsonl
bvim lookup G3056
bvim lookup λόγος
bvim occurrences λόγος --morph N-NSM --in 'John;1 John'
bvim occurrences G3056 --source macula-greek --count
bvim occurrences Λόγος --field surface --in John --format jsonl
bvim occurrences ראשית --field normalized --in Gen
bvim morph Vqp3ms --source macula-hebrew --in Gen
bvim morph nominative --in NT --count
bvim morph qal --in OT --count
```

`lex` groups the verse by source. `--word` takes a one-based **analysis-token** position in each source. JSONL includes the unmodified token ID, original and canonical reference, surface, punctuation following the token, orthographic word number, lemma, language, transliteration, raw and indexed Strong’s mappings, tagged morphology, grammatical features, contextual gloss and dictionary records. A dictionary provides its headword, transliteration, derivation, definition and historical KJV renderings independently. An empty value records a gap in the source or in the installed dictionaries.

`occurrences` in original-language mode produces one row per token per edition. Text output gives reference, token position, surface, lemma, morphology and source. JSONL adds the upstream token ID. `--count` reports tokens and distinct numeric references within the selected scope. Counts across editions include each edition’s attestations. Use `--source` for the frequency in a particular text. With no native match, the default command can find existing JSONL study links. `--version` selects those translation-specific links explicitly. The reader’s `:lookup` and `:occ` commands also accept native terms.

| Search field | Matching rule |
|---|---|
| auto | A G/H identifier selects Strong’s mappings. Other terms select lemmas. |
| strong | Explicit token mappings, including source-specific suffixes such as H871a. |
| lemma | Case- and combining-mark-insensitive headword. Ambiguous folded spellings can include multiple lemmas. Results carry their accented spelling. |
| surface | Exact source string with case and diacritics. |
| normalized | Folded MACULA normalized word where supplied, otherwise folded surface. Greek case and Hebrew vowel points are optional. |

Morphological codes are case-sensitive. Category names are case-insensitive whole features. `N-NSM` identifies the Greek noun code for nominative singular masculine. MACULA’s explicit features supply the human-readable parsing. In Hebrew, `Vqp3ms` represents a qal qatal verb, third-person masculine singular. The source also identifies Aramaic. The installed corpus determines which features are available. Grammar tags describe an analyzed form. The contextual gloss, dictionary definition and KJV translation list have distinct roles.

## Reader controls

| Key inside L | Action |
|---|---|
| j/k, w/b, arrows | Select the adjacent original token in logical source order. |
| `2j`, `gg` / `G`, Ctrl-D/U, Ctrl-F/B | Use counted motions, jump to the first or last row, or page through tokens, definitions, and occurrences. |
| `u` / Ctrl-R | Undo or redo selection changes in the current list. |
| Enter | Inspect the token ID, written-word number, parsing and dictionary entries. j/k scroll. |
| o | Browse occurrences of this exact accented lemma in the selected edition. Enter opens the numeric reference in the reader. Ctrl-O returns. |
| `:scope REF`, `:sc REF` | Limit the occurrence list by testament, book, or passage. Use `.` for the book of the analyzed verse and `..` for its chapter. The reader shares this scope. Omit REF to clear it. |
| / | Filter the cached verse by spelling, transliteration, lemma, gloss, grammar, Strong’s or definition. Enter accepts. Esc restores the previous filter. Ctrl-W deletes a word and Ctrl-U clears the prompt. |
| i | Switch between a compact table and three rows per token for surface, transliteration and gloss. Short windows use the compact view. |
| Tab | Cycle installed editions with data for this verse. Each edition retains its token numbering. |
| ?, Esc | Open contextual help or return one level. |

The Greek transliteration is a generated, lowercase orthographic aid. It preserves vowel length for eta/omega and represents rough breathing and iota subscript. Hebrew transliteration comes from MACULA. Hebrew prefixes, suffixes and implicit morphemes have independent source IDs. Multiple rows can belong to the same written word. Empty surfaces are displayed as `[implicit]`. Hebrew strings remain in logical Unicode order, with vowel points and cantillation intact. Terminal font and bidirectional support affect their appearance.

## Installed sources

| Resource | Pinned revision | Verses | Tokens | Distinct source lemma spellings | Dictionary entries |
|---|---|---:|---:|---:|---:|
| macula-greek, Nestle 1904 | 8423afe47b9e | 7,943 | 137,779 | 5,401 | |
| macula-sblgnt, SBLGNT | 8423afe47b9e | 7,939 | 137,741 | 5,518 | |
| macula-hebrew, WLC | 47db250bd55d | 23,213 | 475,911 | 8,457 | |
| strongs-greek | 0acd2f251c2d | | | | 5,523 |
| strongs-hebrew | 0acd2f251c2d | | | | 8,674 |

MACULA Greek Linguistic Datasets, available at https://github.com/Clear-Bible/macula-greek/. © 2022–2024 Biblica, CC BY 4.0. The Nestle 1904 transcription is by Diego Santos, with morphology by Ulrik Sandborg-Petersen and markup by Jonathan Robie. The Greek glosses used here are from the public-domain Berean interlinear. The optional SBL Greek New Testament is copyright 2010 Society of Biblical Literature and Logos Bible Software, CC BY 4.0. Both installations use the official word-level TSV. [MACULA Greek component licenses](https://github.com/Clear-Bible/macula-greek/blob/8423afe47b9e8f24b7772e808af45c7159a6fe7e/LICENSE.md) · [SBLGNT license](https://github.com/LogosBible/SBLGNT/blob/736fdc76158950c3d04b949b7e013ca14305145a/README.md)

MACULA Hebrew Linguistic Datasets, available at https://github.com/Clear-Bible/macula-hebrew/. © 2022–2024 Biblica, CC BY 4.0. The WLC permits copying. MACULA incorporates OSHB morphology and Groves linguistic data under CC BY 4.0. The Cherith Hebrew glosses are © 2022 Cherith Analytics, by Andi Wu, CC BY 4.0. bvim imports selected word-level columns. The import excludes UBS MARBLE/SDBH domains and semantic dictionary content. [MACULA Hebrew component licenses](https://github.com/Clear-Bible/macula-hebrew/blob/47db250bd55d0d8577f2a94fba114ef16c35b23c/LICENSE.md) · [Original OSHB data](https://github.com/openscriptures/morphhb)

The dictionaries derive from James Strong’s 1890 Greek and 1894 Hebrew dictionaries. The Open Scriptures JSON file headers credit the electronic editions under CC-BY-SA, with no license version specified there. Greek XML credit goes to Ulrik Petersen. Hebrew source preparation credits David Instone-Brewer and David Troidl. The installer reads the JSON assignment as data. [Greek dictionary and notice](https://github.com/openscriptures/strongs/blob/0acd2f251c2d35ff8db2dece4e0593979d3ac223/greek/strongs-greek-dictionary.js) · [Hebrew dictionary and notice](https://github.com/openscriptures/strongs/blob/0acd2f251c2d35ff8db2dece4e0593979d3ac223/hebrew/strongs-hebrew-dictionary.js)

MorphGNT’s seven-column SBLGNT files supply lemmas and morphology under CC BY-SA 3.0 for the annotations. The MACULA tables provide source token IDs, glosses and Strong’s links together. Using their published tables keeps the joins reproducible and preserves edition differences. Mark 1:1, for example, contains seven tokens in the Nestle export and five in SBLGNT. [MorphGNT file format and terms](https://github.com/morphgnt/sblgnt)

## Versification and alignment

The reader opens the **numeric source reference**. WLC numbering can diverge from an English translation, including in the Psalms. A shared chapter and verse number gives a navigation destination. It does not establish correspondence between individual words or resolve split or merged verses. The pane identifies the source and reports the number of explicitly aligned translation positions. `data verify` counts source coordinates missing from each installed translation.

A Hebrew extended identifier such as `0871a` retains its suffix as `H871a`. A bare Strong’s dictionary entry for H871 would describe a different identifier. Greek `+` compound and Hebrew `|` alternative mappings preserve their raw spelling in `raw_strong`. Searching a component returns the attested token. A supplied dictionary entry is available for inspection even when a compound or alternative requires interpretation.

To import a published word alignment, use the existing attributed JSONL resource format. Each linked English word carries the exact installed translation SHA-256, position and surface. Each explicitly supplied original token carries its resource ID, file SHA-256 and upstream token ID. The example below is a schema template. Replace the placeholders with evidence from the alignment publisher.

```json
{"term":"publisher-entry-id","kind":"lexicon","body":"Publisher annotation","references":[{"version":"EDITION","edition_digest":"TRANSLATION_SHA256","ref":"John 1:1","position":1,"surface":"EXACT_EDITION_TOKEN","tokens":[{"source":"macula-greek","digest":"CORPUS_SHA256","id":"PUBLISHER_LINKED_TOKEN_ID"}]}]}
```

Use `bvim versions` and `bvim data status` to inspect digests. Import with `bvim resource FILE --name ID --source SOURCE --license TERMS`. A reference can link to multiple original tokens. Multiple translation positions can name the same token. The importer checks the source revision by digest, token identity, verse and edition surface. These checks validate applicability. The linguistic judgment belongs to the alignment publisher. In the reader select an English word with w/b, press Enter, then choose the named original token. No published English alignment ships with these corpora.

## Maintenance and recovery

`data list` shows available pins. `data status` shows installed revisions, source URLs, license notices, digests and coverage. `data install ID` downloads to a temporary file, verifies SHA-256, parses source records and replaces that resource in a transaction. Hebrew uses the Git LFS media object. Progress goes to stderr. An offline copy installs with `data install ID --file PATH`. The digest must match the pinned release. Updating bvim’s catalog and rerunning the installer installs a new release. An aligned corpus requires review of the alignment resource before changing its underlying revision.

`data verify` checks SQLite integrity, foreign keys, installed manifests and expected record totals. Reinstall from a verified download to restore source content. `data reindex` rebuilds lexical indexes. `data remove ID` removes that resource and dependent token mappings. Back up the library with SQLite’s backup facility before changing a personally annotated collection. Keep source files for independently supplied resources and alignments. [Library backup and recovery](data.md)
