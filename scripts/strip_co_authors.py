#!/usr/bin/env python3
"""Remove ``Co-Authored-By`` trailers from a commit message.

This project records a single author per commit. A variety of editors, CLIs and
commit templates append ``Co-Authored-By:`` trailers automatically, and whether
they do depends on each contributor's local tooling rather than on any decision
made here. This hook removes them, so the convention holds no matter what any
individual has installed.

Anything removed is reported on stderr. A hook that edits your commit message
silently is a hook you stop trusting, so this one always says what it did.

Run by pre-commit at the ``commit-msg`` stage, which passes the path of the file
holding the prepared message as the sole argument. Exits non-zero only on a real
error (bad arguments, unreadable file, undecodable message) - never merely
because it found something to remove, since removing it is the point.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Matches a trailer line only at the start of a line, tolerating the spelling
# variations git itself accepts (`Co-authored-by`, `CO-AUTHORED-BY`) and any
# leading whitespace a template may have introduced.
_TRAILER = re.compile(r"^[ \t]*co-authored-by[ \t]*:", re.IGNORECASE)


def strip_co_authors(message: str) -> tuple[str, list[str]]:
    """Return ``message`` without its co-author trailers, and what was removed.

    Line endings of the surviving lines are preserved exactly as they were, so a
    CRLF message stays CRLF. Blank lines orphaned at the end by the removal are
    trimmed, because a trailer is normally preceded by one and leaving it behind
    would add trailing whitespace that the project's own hooks then flag.
    """
    kept: list[str] = []
    removed: list[str] = []

    for line in message.splitlines(keepends=True):
        if _TRAILER.match(line):
            removed.append(line.strip())
        else:
            kept.append(line)

    if not removed:
        return message, []

    # Drop blank lines left dangling at the end, but keep the body's own final
    # newline. Comment lines (`#`) are git's, and are cleaned up by git itself.
    while kept and not kept[-1].strip():
        kept.pop()

    cleaned = "".join(kept)
    if cleaned and not cleaned.endswith("\n"):
        cleaned += "\n"

    return cleaned, removed


def _report(text: str) -> None:
    """Write one line to stderr.

    Not ``print``: the project's lint configuration bans it (T201) so that stray
    debugging output cannot reach a test run, and a hook is not a good enough
    reason to punch a per-file hole in a rule that is right everywhere else.
    """
    sys.stderr.write(f"{text}\n")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        _report(f"usage: {Path(__file__).name} <commit-msg-file>")
        return 2

    path = Path(argv[0])
    try:
        # Explicit UTF-8 both ways. The default encoding on Windows is not UTF-8,
        # and this project's commit messages contain non-ASCII characters, so
        # relying on the platform default would corrupt them.
        #
        # newline="" on the *read* as well as the write, and via open() rather
        # than read_text(), for two reasons: without it the reader translates
        # CRLF to LF before this code ever sees it, silently rewriting the line
        # endings of every message it touches; and read_text() only accepts a
        # newline argument from 3.13, while this project targets 3.11.
        with path.open(encoding="utf-8", newline="") as handle:
            original = handle.read()
    except OSError as exc:
        _report(f"cannot read commit message file {path}: {exc}")
        return 1
    except UnicodeDecodeError as exc:
        _report(f"commit message file {path} is not valid UTF-8: {exc}")
        return 1

    cleaned, removed = strip_co_authors(original)
    if not removed:
        return 0

    try:
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(cleaned)
    except OSError as exc:
        _report(f"cannot write commit message file {path}: {exc}")
        return 1

    noun = "trailer" if len(removed) == 1 else "trailers"
    _report(f"removed {len(removed)} co-author {noun} from the commit message:")
    for line in removed:
        _report(f"  {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
