# Measurements

Benchmarked locally on an Apple M1 Pro, arm64, Python 3.9.6 and SQLite 3.54.0. The private fixture available on this machine was named RcV.txt. Its length was 4,478,035 bytes and its SHA-256 was bb949abdfc790cd06dff166a0913a719c5eee3a580eb27f4e07678171ee23bb2. No separate RcV(3).txt was found for hash comparison.

The real acceptance test imports 31,103 rows across 66 books, requires zero warnings, reads Genesis 1:1 and Revelation 22:21 and compares the CLI’s complete export with the original bytes. An independent line-by-line phrase scan generates expected references for an FTS query. Synthetic tests exercise invalid records, rollback, variant numbering, multiple editions, attributed word links and different terminal sizes. A pseudo-terminal test drives the actual curses process through search, selection, exit and persistence.

## Backend and startup

| Operation | First fresh process (ms) | Subsequent fresh processes, median (ms) |
|---|---:|---:|
| bvim read, one verse | 49.22 | 46.45 |
| Draft print, one verse | 58.73 | 54.14 |
| bvim search, NT phrase | 46.15 | 46.18 |
| Draft search, NT substring | 59.51 | 58.39 |

These are cold interpreter starts with an uncontrolled filesystem cache. The first sample followed import. A physically cold disk and human input latency were unmeasured. Subsequent figures use seven processes per command. The baseline used the original reader with its local modules explicitly supplied. The old substring command prints up to its default limit, while the new indexed command emits all phrase matches. Startup timing includes command execution and redirected output.

Import took 714 ms. Peak process RSS at import completion was 34,275,328 bytes including the benchmark harness. Within a warm process a whole chapter read took 0.022 ms median and a whole-edition indexed phrase search took 0.126 ms median over 50 samples. An early SQLite plan iterated verse keys before FTS, taking roughly 320 ms for the NT CLI phrase query. Starting with the postings and fetching candidate rows by rowid removed that bottleneck.

## Navigation experiment

Reproduce with `python3 bench.py FILE [--legacy-modules DIR]` in the checkout. Each task runs five times against a 24×80 in-memory terminal using the reader’s actual key dispatcher and layout code. Latency is median processing time for the complete sequence including final redraw and quit. It excludes typing, process startup, terminal I/O and clipboard service time. Counts exclude the harness quit key. A control chord counts as one keystroke. The three comparison IDs use separate imports of the same fixture. The linked-entry tasks use synthetic annotations.

| Task | Keys | Mode changes | Enter presses | Temporary views entered | ms | Context after task |
|---|---:|---:|---:|---:|---:|---|
| Jump to John 3:16 from first verse | 8 | 2 | 1 | 1 prompt | 1.68 | Origin in jump list |
| John 3:16 → John 4:1 | 1 | 0 | 0 | 0 | 0.56 | Origin in jump list |
| Genesis 1:1 → Revelation 22:21 | 1 | 0 | 0 | 0 | 0.39 | Origin in jump list |
| Find phrase, open fifth hit | 18 | 2 | 1 | 1 picker | 2.12 | Origin and first hit retained |
| Compare John 1:1 across A,B,C | 16 | 2 | 1 | 1 prompt | 20.65 | Same verse, initial view in history |
| Next chapter and back | 2 | 0 | 0 | 0 | 0.66 | Exact origin restored |
| Named lexical entry → occurrence → back | 17 | 4 | 3 | 3 | 3.45 | Exact origin restored |
| Copy two verses with references | 3 | 2 | 0 | 0 | 0.81 | Selection clears at endpoint |
| Complete book name and open Rev 22:21 | 15 | 2 | 1 | 1 prompt | 4.10 | Origin in jump list |
| Follow contextual entry and return | 5 | 3 | 3 | 2 | 0.76 | Exact origin restored |

The chapter key saves the seven input events needed for the equivalent absolute jump. Direct G crossing the entire edition saves repeated book/chapter navigation. The command prompt deliberately retains one acceptance keystroke for abbreviated or fuzzy passage choices. Following a contextual entry saves twelve events compared with entering the headword in this fixture. The extra entry-selection step permits multiple scholarly sources and makes the selected evidence visible. These workflow measurements compare interaction costs; they do not establish how often a reader performs each task.
