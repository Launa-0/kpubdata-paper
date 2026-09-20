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
"""

from __future__ import annotations

import hashlib
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
        entries = [FileEntry(root.name, file_sha256(root), root.stat().st_size)]
    else:
        entries = [
            FileEntry(
                path=str(child.relative_to(root)),
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
