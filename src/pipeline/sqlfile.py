"""The statements of a fix-up file, such as upgrades/43.0/check.sql.

A file holds statements separated by `;`, each led by a comment that says why it is there. The
split skips `;` in comments, quoted strings, quoted identifiers and dollar-quoted bodies.
"""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

DOLLAR = re.compile(r"\$([A-Za-z_][A-Za-z_0-9]*)?\$")


@dataclass(frozen=True)
class Statement:
    sql: str  # without its leading comment
    line: int  # where it starts in its file, from 1
    comment: str  # the comment above it, its lines joined

    @property
    def title(self) -> str:
        """Its comment's first sentence, or its first line: to name it in a failure."""
        if self.comment:
            return self.comment.split(": ")[0].split(". ")[0].rstrip(".")
        return self.sql.splitlines()[0]


def statements(text: str) -> list[Statement]:
    out = []
    start, i, n = 0, 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif c in "'\"":
            end = i + 1
            while end < n:
                if text[end] == c:
                    if end + 1 < n and text[end + 1] == c:  # '' or "" within the quotes
                        end += 2
                        continue
                    break
                end += 1
            i = end + 1
        elif c == "$" and (m := DOLLAR.match(text, i)):
            end = text.find(m.group(0), m.end())
            i = n if end < 0 else end + len(m.group(0))
        elif c == ";":
            _add(out, text, start, i)
            start = i = i + 1
        else:
            i += 1
    _add(out, text, start, n)
    return out


def _add(out: list[Statement], text: str, start: int, end: int) -> None:
    chunk = text[start:end]
    comment, body, line = [], [], text.count("\n", 0, start) + 1
    lines = chunk.splitlines()
    k = 0
    while k < len(lines) and (not lines[k].strip() or lines[k].lstrip().startswith("--")):
        stripped = lines[k].strip()
        if stripped.startswith("--"):
            comment.append(stripped[2:].strip())
        elif comment:
            comment = []  # a blank line ends a comment that belongs to no statement
        k += 1
    body = "\n".join(lines[k:]).strip()
    if not body:
        return
    out.append(Statement(sql=body, line=line + k, comment=" ".join(comment)))


def describe(path: Path) -> dict:
    """What the manifest records of a fix-up file: its sha256 and statements."""
    text = path.read_text()
    return {
        "file": f"upgrades/{path.parent.name}/{path.name}",
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "statements": len(statements(text)),
    }
