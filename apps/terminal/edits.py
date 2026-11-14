"""Parse model replies into edits, apply them to text, render a diff. No I/O."""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass


class EditError(Exception):
    pass


@dataclass
class Edit:
    path: str
    search: str | None  # None: whole-file content in `replace`
    replace: str


_S = re.compile(r"^<{5,9} SEARCH\s*$")
_M = re.compile(r"^={5,9}\s*$")
_E = re.compile(r"^>{5,9} REPLACE\s*$")
_FILE = re.compile(r"^\s*FILE:\s*(\S+)\s*$")
_END = re.compile(r"^\s*END FILE\s*$")
_FENCE = re.compile(r"^\s*```")
_DASHED = re.compile(r"^--- ([\w./\\-]+\.\w+) ---\s*$")  # the context format, echoed back as a whole file
_PATHLINE = re.compile(r"^[\s`*#=-]*(?:FILE:\s*)?([\w./\\-]+\.\w+)(?:[\s`*:=-]*|:\s.*|\s+\[.*\])$")


def _path(line: str) -> str | None:
    m = _PATHLINE.match(line)
    return m.group(1) if m else None


def parse_edits(text: str, default: str | None = None) -> list[Edit]:
    """SEARCH/REPLACE blocks, `FILE: p ... END FILE` blocks, or a fenced block under a path line.

    A SEARCH block with no path line above it goes to `default` (the only file in context), else the last path seen.
    """
    lines = text.splitlines()
    out: list[Edit] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _S.match(ln):
            near = [lines[j] for j in range(i - 1, max(i - 4, -1), -1) if lines[j].strip() and not _FENCE.match(lines[j])]
            prev = (_path(near[0]) if near else None) or (out[-1].path if out else default) or ""  # "": caller resolves
            j = i + 1
            s: list[str] = []
            while j < len(lines) and not _M.match(lines[j]):
                s.append(lines[j]); j += 1
            r: list[str] = []
            j += 1
            while j < len(lines) and not _E.match(lines[j]):
                r.append(lines[j]); j += 1
            if j < len(lines):
                out.append(Edit(prev, "\n".join(s), "\n".join(r)))
            i = j + 1
            continue
        d = _DASHED.match(ln)
        if d and not any(_S.match(x) for x in lines[i + 1:i + 4]):
            j = i + 1
            body = []
            while j < len(lines) and not _DASHED.match(lines[j]):
                body.append(lines[j]); j += 1
            out.append(Edit(d.group(1), None, _unfence(body).rstrip("\n")))
            i = j
            continue
        m = _FILE.match(ln)
        if m:
            j = i + 1
            body: list[str] = []
            while j < len(lines) and not _END.match(lines[j]):
                body.append(lines[j]); j += 1
            if any(_S.match(b) for b in body):  # SEARCH blocks wrapped in FILE ... END FILE
                out.extend(parse_edits("\n".join(body), m.group(1)))
            else:
                out.append(Edit(m.group(1), None, _unfence(body)))
            i = j + 1
            continue
        if _FENCE.match(ln) and i > 0:
            p = _path(lines[i - 1]) if lines[i - 1].strip() else None
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if p and not _S.match(nxt):  # a fence around SEARCH blocks is just decoration
                j = i + 1
                body = []
                while j < len(lines) and not _FENCE.match(lines[j]):
                    body.append(lines[j]); j += 1
                out.append(Edit(p, None, "\n".join(body)))
                i = j + 1
                continue
        i += 1
    return out


def _unfence(body: list[str]) -> str:
    if body and _FENCE.match(body[0]):
        body = body[1:]
        if body and _FENCE.match(body[-1]):
            body = body[:-1]
    return "\n".join(body)


def apply_edit(old: str | None, e: Edit) -> str:
    """New file text. Raises EditError when a SEARCH block does not match."""
    if e.search is None or (not e.search.strip()):
        return e.replace + ("\n" if e.replace and not e.replace.endswith("\n") else "")
    if old is None:
        raise EditError(f"{e.path}: SEARCH block for a file that does not exist")
    if e.search in old:
        return old.replace(e.search, e.replace, 1)
    # Tolerant retry: ignore leading/trailing space and blank lines (small models drop the blank lines).
    ol = old.split("\n")
    want = [x.strip() for x in e.search.split("\n") if x.strip()]
    idx = [k for k, x in enumerate(ol) if x.strip()]
    for a in range(len(idx) - len(want) + 1):
        if want and [ol[k].strip() for k in idx[a:a + len(want)]] == want:
            lo, hi = idx[a], idx[a + len(want) - 1] + 1
            return "\n".join(ol[:lo] + e.replace.split("\n") + ol[hi:])
    raise EditError(f"{e.path}: SEARCH block not found in the file")


def _finds(text: str, e: Edit) -> bool:
    try:
        apply_edit(text, e)
        return True
    except EditError:
        return False


def plan(edits: list[Edit], read, files: tuple[str, ...] = ()) -> tuple[dict[str, tuple[str | None, str]], list[str]]:
    """(path -> (old text or None, new text), errors). `read(path)` returns the text or None for a new file."""
    state: dict[str, tuple[str | None, str]] = {}
    errors: list[str] = []
    for e in edits:
        old, cur = state.get(e.path, (None, None))
        if not e.path:  # no path given: the one context file whose text holds the SEARCH lines
            e.path = next((p for p in files if (t := read(p)) is not None and _finds(t, e)), "")
            if not e.path:
                errors.append("a SEARCH block has no file path and matches no context file")
                continue
        if e.path not in state:
            old = read(e.path)
            cur = old
        try:
            new = apply_edit(cur, e)
        except EditError as err:
            errors.append(str(err))
            continue
        state[e.path] = (old, new)
    return state, errors


def unified(path: str, old: str | None, new: str) -> list[str]:
    a = (old or "").splitlines(keepends=True)
    b = new.splitlines(keepends=True)
    return list(difflib.unified_diff(a, b, f"a/{path}" if old is not None else "/dev/null", f"b/{path}"))
