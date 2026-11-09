"""Execution and immutable reviewed cache for explicit prompt files."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Generator, Sequence
from pathlib import Path

from aiscript import builder, env, paths, pysetup
from aiscript.config import Settings
from aiscript.errors import AiscriptError
from aiscript.file_contracts import (
    BuildDestination,
    BuildLease,
    FileBuildCache,
    ProgramRunner,
    PromptFileBuilder,
    PromptSnapshot,
    PromptSource,
    ReviewedBuild,
)
from aiscript.runner import run_script


def _snapshot(path: Path) -> PromptSnapshot:
    try:
        source = path.resolve(strict=True)
        if not source.is_file():
            raise AiscriptError(f"Not a regular prompt file: {path}")
        with source.open(encoding="utf-8", newline="") as handle:
            prompt = handle.read()
    except (OSError, UnicodeError, RuntimeError) as exc:
        raise AiscriptError(f"Cannot read prompt file {path}: {exc}") from exc
    if prompt.startswith("#!"):
        prompt = prompt.partition("\n")[2]
    if not prompt.strip():
        raise AiscriptError(f"Prompt file is empty: {path}")
    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    return PromptSnapshot(source, prompt, digest)


@contextlib.contextmanager
def _lock(path: Path) -> Generator[None, None, None]:
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            # LK_LOCK has a finite retry limit, so use blocking OS-level locking below.
            import ctypes
            from ctypes import wintypes

            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("Internal", ctypes.c_size_t),
                    ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            overlap = Overlapped()
            raw = msvcrt.get_osfhandle(handle.fileno())  # type: ignore[attr-defined]
            if not kernel.LockFileEx(wintypes.HANDLE(raw), 2, 0, 1, 0, ctypes.byref(overlap)):
                raise OSError("Could not acquire prompt file cache lock")
            try:
                yield
            finally:
                if not kernel.UnlockFileEx(wintypes.HANDLE(raw), 0, 1, 0, ctypes.byref(overlap)):
                    raise OSError("Could not release prompt file cache lock")
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _build(snapshot: PromptSnapshot, destination: Path, settings: Settings) -> Path:
    name = "prompt-file"
    script = builder.generate_reviewed(name, snapshot.prompt, settings)
    if script.dependencies:
        target = destination / "main.py"
        target.write_text(script.code, encoding="utf-8", newline="\n")
        deps = pysetup._normalise(script.dependencies)
        python = env.find_python()
        uv = env.uv_path()
        print(f"Installing dependencies for {name!r}: {', '.join(deps)}...", file=sys.stderr)
        if uv:
            pysetup._install_uv(uv, name, destination, deps, python)
        else:
            pysetup._install_pip(destination, deps, python)
    else:
        ext = {"python": "py", "powershell": "ps1", "bash": "sh"}[script.language]
        target = destination / f"script.{ext}"
        target.write_text(script.code, encoding="utf-8", newline="\n")
    if not paths.is_windows():
        target.chmod(0o755)
    return target


def _lookup(manifest: Path, snapshot: PromptSnapshot, root: Path) -> Path | None:
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("manifest is not an object")
        relative = data.get(snapshot.digest)
        if relative is None:
            return None
        if not isinstance(relative, str):
            raise ValueError("invalid entrypoint")
        entry = (root / relative).resolve()
        if not entry.is_relative_to(root.resolve()) or not entry.is_file():
            raise ValueError("cached entrypoint is missing or outside cache")
        return entry
    except (OSError, ValueError) as exc:
        raise AiscriptError(f"Cannot read prompt cache: {exc}") from exc


def _publish(manifest: Path, snapshot: PromptSnapshot, root: Path, entry: Path) -> None:
    data: dict[str, str] = {}
    if manifest.exists():
        value = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid cache manifest")
        data = value
    data[snapshot.digest] = str(entry.relative_to(root))
    fd, temporary = tempfile.mkstemp(dir=root, prefix=".manifest-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(temporary, manifest)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def execute(path: Path, args: list[str], settings: Callable[[], Settings]) -> int:
    """Run an explicit prompt file through the approved execution ports."""
    use_case = FileExecution(
        LocalPromptSource(),
        LocalFileBuildCache(),
        LocalPromptFileBuilder(settings),
        LocalProgramRunner(),
    )
    return use_case.execute(path, args)


class LocalPromptSource:
    def read(self, path: Path) -> PromptSnapshot:
        return _snapshot(path)


class LocalBuildLease:
    def __init__(self, root: Path) -> None:
        self.root = root

    def find(self, snapshot: PromptSnapshot) -> ReviewedBuild | None:
        entry = _lookup(self.root / "manifest.json", snapshot, self.root)
        return ReviewedBuild(snapshot.digest, entry) if entry is not None else None

    def allocate(self) -> BuildDestination:
        return BuildDestination(Path(tempfile.mkdtemp(prefix="version-", dir=self.root)))

    def publish(
        self, snapshot: PromptSnapshot, destination: BuildDestination, entrypoint: Path
    ) -> ReviewedBuild:
        if not entrypoint.resolve().is_relative_to(destination.version_dir.resolve()):
            raise AiscriptError("Built entrypoint is outside its version directory")
        _publish(self.root / "manifest.json", snapshot, self.root, entrypoint)
        return ReviewedBuild(snapshot.digest, entrypoint)

    def discard(self, destination: BuildDestination) -> None:
        shutil.rmtree(destination.version_dir, ignore_errors=True)


class LocalFileBuildCache:
    @contextlib.contextmanager
    def acquire(self, source: Path) -> Generator[BuildLease, None, None]:
        identity = hashlib.sha256(os.fsencode(str(source))).hexdigest()
        root = paths.aiscript_home() / "file-cache" / identity
        root.mkdir(parents=True, exist_ok=True)
        with _lock(root / ".lock"):
            yield LocalBuildLease(root)


class LocalPromptFileBuilder:
    def __init__(self, settings: Callable[[], Settings]) -> None:
        self.settings = settings

    def build(self, snapshot: PromptSnapshot, destination: BuildDestination) -> Path:
        return _build(snapshot, destination.version_dir, self.settings())


class LocalProgramRunner:
    def run(self, build: ReviewedBuild, args: Sequence[str]) -> int:
        return run_script(build.entrypoint, list(args))


class FileExecution:
    def __init__(
        self,
        source: PromptSource,
        cache: FileBuildCache,
        builder_port: PromptFileBuilder,
        runner: ProgramRunner,
    ) -> None:
        self.source = source
        self.cache = cache
        self.builder = builder_port
        self.runner = runner

    def execute(self, path: Path, args: Sequence[str]) -> int:
        snapshot = self.source.read(path)
        try:
            with self.cache.acquire(snapshot.source) as lease:
                build = lease.find(snapshot)
                if build is None:
                    destination = lease.allocate()
                    try:
                        entry = self.builder.build(snapshot, destination)
                        build = lease.publish(snapshot, destination, entry)
                    except BaseException:
                        lease.discard(destination)
                        raise
            return self.runner.run(build, args)
        except (OSError, ValueError) as exc:
            raise AiscriptError(f"Prompt file cache error: {exc}") from exc
