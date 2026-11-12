"""Credential scanner for prompts and generated code (C8); pure.

Known keys are turned into 12-character needles (the value, its reverse and its ROT13, windowed)
instead of transforming the text. The text is then searched in several views: raw, joined (only
``[A-Za-z0-9_-]`` kept), per-line escape and percent decodings, base64/base32/hex decodings of
long tokens, Python constant folding and PowerShell ``[char]`` number sequences.
"""

from __future__ import annotations

import ast
import base64
import binascii
import codecs
import re
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import accumulate
from typing import Literal
from urllib.parse import unquote

from aiscript.paths import Language

MatchKind = Literal["known", "pattern"]
SecretView = Literal["raw", "decoded", "reversed", "rot13", "window"]

_WINDOW = 12
_MIN_LENGTH = 8
_PLACEHOLDER = "not-needed"

_RUNS = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN = re.compile(r"[A-Za-z0-9+/_-]{16,}")
_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])sk-([A-Za-z0-9_-]{20,})")
_ESCAPES = re.compile(r"\\x([0-9A-Fa-f]{2})|\\u([0-9A-Fa-f]{4})|\\0?([0-7]{3})")
_NUMBERS = re.compile(r"\d{1,7}")
_HEX = re.compile(r"(?:[0-9A-Fa-f]{2})+")
_BASE32 = re.compile(r"[A-Z2-7]+")

_Needles = dict[int, dict[str, SecretView]]


@dataclass(frozen=True)
class SecretFinding:
    """Where a secret was found; never the value."""

    line: int
    kind: MatchKind
    view: SecretView


def _windows(value: str) -> Iterable[str]:
    if len(value) < _WINDOW:
        return (value,) if len(value) >= _MIN_LENGTH else ()
    return (value[i : i + _WINDOW] for i in range(len(value) - _WINDOW + 1))


def _rot13(value: str) -> str:
    return codecs.encode(value, "rot13")


class KnownSecrets:
    """Configured keys as precomputed 12-character needles."""

    __slots__ = ("_joined", "_raw", "_count")

    def __init__(self, raw: _Needles, joined: _Needles, count: int) -> None:
        self._raw = raw
        self._joined = joined
        self._count = count

    @classmethod
    def from_values(cls, values: Iterable[str]) -> KnownSecrets:
        raw: _Needles = {}
        joined: _Needles = {}
        count = 0
        for value in values:
            value = value.strip()
            if len(value) < _MIN_LENGTH or value == _PLACEHOLDER:
                continue
            count += 1
            rotated = _rot13(value)
            variants: list[tuple[str, SecretView]] = [
                (value, "raw"),
                (value[::-1], "reversed"),
                (rotated, "rot13"),
                (rotated[::-1], "rot13"),
            ]
            for variant, view in variants:
                for needle in _windows(variant):
                    raw.setdefault(len(needle), {}).setdefault(needle, view)
                kept = "".join(_RUNS.findall(variant))
                if len(kept) >= _WINDOW:
                    for needle in _windows(kept):
                        joined.setdefault(len(needle), {}).setdefault(needle, view)
        return cls(raw, joined, count)

    def __repr__(self) -> str:
        return f"KnownSecrets(<{self._count} hidden values>)"

    __str__ = __repr__


def _window_hits(view: str, needles: _Needles) -> list[tuple[int, SecretView]]:
    hits: list[tuple[int, SecretView]] = []
    for size, table in needles.items():
        if len(view) < size:
            continue
        windows = {view[i : i + size] for i in range(len(view) - size + 1)}
        for window in windows.intersection(table):
            start = view.find(window)
            while start != -1:
                hits.append((start, table[window]))
                start = view.find(window, start + 1)
    return hits


def _pattern_hits(view: str) -> list[int]:
    hits: list[int] = []
    for match in _PATTERN.finditer(view):
        body = match.group(1)
        if (
            any(c.isdigit() for c in body)
            and any(c.isupper() for c in body)
            and any(c.islower() for c in body)
        ):
            hits.append(match.start())
    return hits


def _check_piece(piece: str, secrets: KnownSecrets) -> frozenset[MatchKind]:
    kinds: set[MatchKind] = set()
    if len(piece) >= _MIN_LENGTH:
        if _window_hits(piece, secrets._raw):
            kinds.add("known")
        if _pattern_hits(piece):
            kinds.add("pattern")
    return frozenset(kinds)


def _decode_base64(token: str) -> bytes | None:
    token = token.replace("-", "+").replace("_", "/").rstrip("=")
    if len(token) % 4 == 1:
        token = token[:-1]
    try:
        return base64.b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError):
        return None


def _decode_hex(token: str) -> bytes | None:
    if _HEX.fullmatch(token) is None:
        return None
    return bytes.fromhex(token)


def _decode_base32(token: str) -> bytes | None:
    upper = token.upper()
    if _BASE32.fullmatch(upper) is None:
        return None
    try:
        return base64.b32decode(upper + "=" * (-len(upper) % 8))
    except (binascii.Error, ValueError):
        return None


def _token_views(token: str) -> list[str]:
    views: list[str] = []
    for decoded in (_decode_base64(token), _decode_hex(token), _decode_base32(token)):
        if decoded:
            views.append(decoded.decode("latin-1"))
    return views


def _unescape(line: str) -> str:
    def replace(match: re.Match[str]) -> str:
        hex2, hex4, octal = match.groups()
        code = int(hex2 or hex4 or octal, 16 if (hex2 or hex4) else 8)
        return chr(code)

    return _ESCAPES.sub(replace, line)


class _Folder:
    """Constant-folds the small Python expressions that hide a string."""

    def __init__(self, names: dict[str, ast.expr] | None = None) -> None:
        self._memo: dict[int, object | None] = {}
        self._names = names or {}
        self._resolving: set[str] = set()

    def fold(self, node: ast.AST, env: dict[str, object] | None = None) -> object | None:
        if env:
            return self._fold(node, env)
        key = id(node)
        if key not in self._memo:
            self._memo[key] = self._fold(node, {})
        return self._memo[key]

    def _fold(self, node: ast.AST, env: dict[str, object]) -> object | None:
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, bool) or not isinstance(value, (str, bytes, int)):
                return None
            return value
        if isinstance(node, ast.Name):
            if node.id in env:
                return env[node.id]
            return self._resolve(node.id) if isinstance(node.ctx, ast.Load) else None
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [self.fold(element, env) for element in node.elts]
            return None if any(item is None for item in items) else items
        if isinstance(node, ast.BinOp):
            return self._binop(node, env)
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
            return self._slice(node, env)
        if isinstance(node, ast.Call):
            return self._call(node, env)
        return None

    def _resolve(self, name: str) -> object | None:
        """Value of a name assigned exactly once (and never mutated); guards against cycles."""
        value = self._names.get(name)
        if value is None or name in self._resolving:
            return None
        self._resolving.add(name)
        try:
            return self.fold(value)
        finally:
            self._resolving.discard(name)

    def _binop(self, node: ast.BinOp, env: dict[str, object]) -> object | None:
        left = self.fold(node.left, env)
        right = self.fold(node.right, env)
        if isinstance(node.op, ast.Add):
            if isinstance(left, str) and isinstance(right, str):
                return left + right
            if isinstance(left, bytes) and isinstance(right, bytes):
                return left + right
            if isinstance(left, int) and isinstance(right, int):
                return left + right
            if isinstance(left, list) and isinstance(right, list):
                return left + right
        if isinstance(node.op, ast.Sub) and isinstance(left, int) and isinstance(right, int):
            return left - right
        return None

    def _slice(self, node: ast.Subscript, env: dict[str, object]) -> object | None:
        base = self.fold(node.value, env)
        bounds = node.slice
        if not isinstance(bounds, ast.Slice) or not isinstance(base, (str, bytes, list)):
            return None
        parts: list[int | None] = []
        for part in (bounds.lower, bounds.upper, bounds.step):
            if part is None:
                parts.append(None)
                continue
            folded = self.fold(part, env)
            if not isinstance(folded, int):
                return None
            parts.append(folded)
        try:
            return base[slice(*parts)]
        except ValueError:
            return None

    def _items(self, node: ast.AST, env: dict[str, object]) -> list[object] | None:
        if isinstance(node, (ast.GeneratorExp, ast.ListComp)):
            if len(node.generators) != 1 or node.generators[0].ifs:
                return None
            generator = node.generators[0]
            if not isinstance(generator.target, ast.Name):
                return None
            source = self.fold(generator.iter, env)
            if isinstance(source, (str, bytes)):
                source = list(source)
            if not isinstance(source, list):
                return None
            out: list[object] = []
            for item in source:
                folded = self.fold(node.elt, {**env, generator.target.id: item})
                if folded is None:
                    return None
                out.append(folded)
            return out
        folded_node = self.fold(node, env)
        return folded_node if isinstance(folded_node, list) else None

    def _call(self, node: ast.Call, env: dict[str, object]) -> object | None:
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        attr = func.attr if isinstance(func, ast.Attribute) else None
        args = node.args
        if len(args) == 1 and not node.keywords:
            if name == "chr":
                code = self.fold(args[0], env)
                if isinstance(code, int) and 0 <= code < 0x110000:
                    return chr(code)
                return None
            if name in ("bytes", "bytearray"):
                items = self._items(args[0], env)
                if items is not None and all(isinstance(i, int) and 0 <= i < 256 for i in items):
                    return bytes(i for i in items if isinstance(i, int))
                return None
            if attr == "join" and isinstance(func, ast.Attribute):
                separator = self.fold(func.value, env)
                items = self._items(args[0], env)
                if isinstance(separator, str) and items is not None:
                    if all(isinstance(i, str) for i in items):
                        return separator.join(i for i in items if isinstance(i, str))
                return None
            if name in ("b64decode", "urlsafe_b64decode", "a2b_base64", "unhexlify", "fromhex") or (
                attr in ("b64decode", "urlsafe_b64decode", "a2b_base64", "unhexlify", "fromhex")
            ):
                return self._decode_call(name or attr or "", self.fold(args[0], env))
        if attr in ("decode", "encode") and isinstance(func, ast.Attribute) and not args:
            base = self.fold(func.value, env)
            if attr == "decode" and isinstance(base, bytes):
                return base.decode("utf-8", errors="replace")
            if attr == "encode" and isinstance(base, str):
                return base.encode("utf-8", errors="replace")
        if attr == "decode" and len(args) == 2 and isinstance(func, ast.Attribute):
            text = self.fold(args[0], env)
            codec = self.fold(args[1], env)
            if isinstance(text, str) and codec == "rot13":
                return _rot13(text)
        return None

    @staticmethod
    def _decode_call(which: str, argument: object | None) -> bytes | None:
        if isinstance(argument, bytes):
            argument = argument.decode("latin-1")
        if not isinstance(argument, str):
            return None
        if which in ("unhexlify", "fromhex"):
            return _decode_hex(argument.replace(" ", ""))
        return _decode_base64(argument)


def _single_assignments(tree: ast.AST) -> dict[str, ast.expr]:
    """Names assigned exactly once and never augmented or mutated, with their value."""
    counts: dict[str, int] = {}
    values: dict[str, ast.expr] = {}
    tainted: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    counts[target.id] = counts.get(target.id, 0) + 1
                    values[target.id] = node.value
                else:
                    tainted.update(n.id for n in ast.walk(target) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign, ast.NamedExpr)):
            tainted.update(n.id for n in ast.walk(node.target) if isinstance(n, ast.Name))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            tainted.update(n.id for n in ast.walk(node.target) if isinstance(n, ast.Name))
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.attr in ("append", "extend", "insert"):
                tainted.add(node.value.id)
    return {n: v for n, v in values.items() if counts[n] == 1 and n not in tainted}


def _folded_pieces(text: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return []
    folder = _Folder(_single_assignments(tree))
    pieces: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    try:
        for node in ast.walk(tree):
            if not isinstance(node, ast.expr):
                continue
            value = folder.fold(node)
            if isinstance(value, bytes):
                value = value.decode("latin-1")
            if isinstance(value, str) and len(value) >= _MIN_LENGTH:
                entry = (node.lineno, value)
                if entry not in seen:
                    seen.add(entry)
                    pieces.append(entry)
    except RecursionError:
        pass
    return pieces


def scan(
    text: str, secrets: KnownSecrets, *, language: Language | None = None
) -> list[SecretFinding]:
    """Find known keys and generic credential patterns in ``text``."""
    newlines = [m.start() for m in re.finditer("\n", text)]

    def line_at(offset: int) -> int:
        return bisect_left(newlines, offset) + 1

    found: dict[tuple[int, MatchKind], SecretView] = {}

    def add(line: int, kind: MatchKind, view: SecretView) -> None:
        found.setdefault((line, kind), view)

    for offset, view in _window_hits(text, secrets._raw):
        add(line_at(offset), "known", view)
    for offset in _pattern_hits(text):
        add(line_at(offset), "pattern", "raw")

    _scan_joined(text, secrets, line_at, add)

    cache: dict[str, frozenset[MatchKind]] = {}

    def add_cached(line: int, piece: str) -> None:
        if piece not in cache:
            cache[piece] = _check_piece(piece, secrets)
        for kind in cache[piece]:
            add(line, kind, "decoded")

    for number, line_text in enumerate(text.split("\n"), start=1):
        if "\\" in line_text:
            add_cached(number, _unescape(line_text))
        if "%" in line_text:
            add_cached(number, unquote(line_text, errors="replace"))

    token_views: dict[str, list[str]] = {}
    for match in _TOKEN.finditer(text):
        token = match.group()
        if token not in token_views:
            token_views[token] = _token_views(token)
        line = line_at(match.start())
        for view_text in token_views[token]:
            add_cached(line, view_text)

    if language == "python":
        for line, piece in _folded_pieces(text):
            add_cached(line, piece)
    elif language == "powershell":
        _scan_numbers(text, secrets, line_at, add)

    findings = [
        SecretFinding(line=line, kind=kind, view=view)
        for (line, kind), view in found.items()
        if kind == "known" or (line, "known") not in found
    ]
    findings.sort(key=lambda f: (f.line, f.kind != "known"))
    return findings


def _scan_joined(
    text: str,
    secrets: KnownSecrets,
    line_at: Callable[[int], int],
    add: Callable[[int, MatchKind, SecretView], None],
) -> None:
    if not secrets._joined:
        return
    runs = [(m.start(), m.group()) for m in _RUNS.finditer(text)]
    joined = "".join(run for _, run in runs)
    offsets = [0, *accumulate(len(run) for _, run in runs)]
    for offset, view in _window_hits(joined, secrets._joined):
        index = bisect_right(offsets, offset) - 1
        add(line_at(runs[index][0] + offset - offsets[index]), "known", view)


def _scan_numbers(
    text: str,
    secrets: KnownSecrets,
    line_at: Callable[[int], int],
    add: Callable[[int, MatchKind, SecretView], None],
) -> None:
    """PowerShell ``[char]`` sequences: printable decimal numbers read as characters."""
    chars: list[str] = []
    positions: list[int] = []
    for match in _NUMBERS.finditer(text):
        value = int(match.group())
        if 32 <= value < 127:
            chars.append(chr(value))
            positions.append(match.start())
    view = "".join(chars)
    for offset, _ in _window_hits(view, secrets._raw):
        add(line_at(positions[offset]), "known", "decoded")
    for offset in _pattern_hits(view):
        add(line_at(positions[offset]), "pattern", "decoded")


_KIND_LABEL: dict[MatchKind, str] = {"known": "known key", "pattern": "key pattern"}


def refusal_message(stage: Literal["prompt", "code"], findings: Sequence[SecretFinding]) -> str:
    """Line numbers and kinds, never the value."""
    parts: list[str] = []
    for kind in ("known", "pattern"):
        lines = sorted({f.line for f in findings if f.kind == kind})
        if lines:
            noun = "line" if len(lines) == 1 else "lines"
            parts.append(f"{_KIND_LABEL[kind]} on {noun} {', '.join(str(n) for n in lines)}")
    where = "; ".join(parts) or "a credential"
    if stage == "prompt":
        return (
            f"The prompt contains a credential ({where}), so the build was refused before "
            "anything was sent. aiscript uses the key from your config; remove it from the "
            "prompt and try again."
        )
    return (
        f"The generated code contains a credential ({where}), so it was refused and nothing "
        "was saved or run. aiscript uses the key from your config; remove it from the prompt "
        "and build again."
    )
