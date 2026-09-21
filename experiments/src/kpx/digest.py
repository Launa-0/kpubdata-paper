"""Content addressing for source snapshots and build outputs.

Both reproducibility experiments rest on being able to say "this is the same
bytes as last time":

* **R1** claims identical source + identical code + identical config produce
  identical output. The claim is empty unless "identical source" is checked
  rather than assumed.
* **R2** deliberately varies the source, so it must be able to tell *which*
  source a build used.

A snapshot is rarely one file — a public-data pull is usually a directory of API
responses — so the digest is defined over a whole tree. Each file is hashed, the
``(relative path, hash)`` pairs are sorted, and the digest is the hash of that
manifest. Directory iteration order, which varies between filesystems, therefore
cannot change the result.

Paths go into the manifest, so how a path is *spelled* is part of the digest, and
the spelling has to be a property of the snapshot rather than of the machine
reading it. Two platform differences would otherwise leak in:

* **Separators.** ``str(Path)`` yields ``2020\\01.json`` on Windows and
  ``2020/01.json`` elsewhere.
* **Unicode normalization.** macOS hands back decomposed filenames (NFD) where
  Linux and Windows return what was written (usually NFC), so ``거래금액.json``
  is two different strings depending on where it is read.

Either one would give the same bytes different digests on different machines,
which breaks R1's premise and makes ``kpx snapshot verify`` fail for any reader
who restored the published data on another OS. :func:`manifest_path` fixes both.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_CHUNK = 1 << 20

#: Files that describe a snapshot rather than belong to it.
EXCLUDED_NAMES = frozenset({"metadata.json", ".DS_Store", ".gitkeep"})


@dataclass(frozen=True)
class FileEntry:
    """One file inside a digested tree."""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class TreeDigest:
    """The digest of a file or directory tree."""

    sha256: str
    size_bytes: int
    file_count: int
    files: tuple[FileEntry, ...]

    @property
    def short(self) -> str:
        """First 12 hex characters, used to build readable snapshot ids."""
        return self.sha256[:12]


def manifest_path(path: Path, root: Path | None = None) -> str:
    """Spell a path the way the manifest spells it, on every platform.

    POSIX separators and NFC, so that a digest identifies the snapshot's
    contents rather than the operating system that read them.
    """
    relative = path.relative_to(root) if root is not None else Path(path.name)
    return unicodedata.normalize("NFC", relative.as_posix())


def file_sha256(path: Path) -> str:
    """Stream ``path`` through SHA-256 so that large artifacts do not need RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def digest_tree(root: Path, *, exclude: frozenset[str] = EXCLUDED_NAMES) -> TreeDigest:
    """Digest a file or a directory tree.

    Hidden files and anything named in ``exclude`` are skipped, so writing a
    snapshot's own ``metadata.json`` next to its data does not change the data's
    digest.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"nothing to digest at {root}")

    if root.is_file():
        entries = [FileEntry(manifest_path(root), file_sha256(root), root.stat().st_size)]
    else:
        entries = [
            FileEntry(
                path=manifest_path(child, root),
                sha256=file_sha256(child),
                size_bytes=child.stat().st_size,
            )
            for child in sorted(root.rglob("*"))
            if child.is_file()
            and child.name not in exclude
            and not any(part.startswith(".") for part in child.relative_to(root).parts)
        ]

    if not entries:
        raise ValueError(f"no files to digest under {root}")

    entries.sort(key=lambda entry: entry.path)
    manifest = "\n".join(f"{entry.sha256}  {entry.path}" for entry in entries)
    return TreeDigest(
        sha256=hashlib.sha256(manifest.encode("utf-8")).hexdigest(),
        size_bytes=sum(entry.size_bytes for entry in entries),
        file_count=len(entries),
        files=tuple(entries),
    )
