"""스냅샷 바이트를 빌더에 넘기는 파일 기반 upload store.

빌더가 딸려 보내는 ``SQLiteUploadRepository``는 content를 BLOB으로 넣는다. SQLite의
기본 ``SQLITE_MAX_LENGTH``가 10억 바이트(약 953 MiB)라서, 그보다 큰 스냅샷은
``sqlite3.DataError: string or blob too big``으로 **빌드가 시작되기도 전에** 멈춘다.
따릉이 T4 통합본(1,444 MiB)이 실제로 거기서 걸렸다.

빌더를 고칠 일은 아니다. 서비스는 업로드 크기에 상한을 두는 것이 맞고, 여기서 다루는
것은 사용자 업로드가 아니라 **우리가 얼려 둔 실험 원천**이다. ``UploadRepository``가
Protocol이므로 저장 방식만 바꿔 끼운다 — 빌더 코드도, Silver 계약도 건드리지 않는다.

바이트는 파일 하나로 두고 메타데이터만 JSON으로 옆에 둔다. content를 한 번 더 복사해
들고 있지 않으므로 큰 스냅샷에서 SQLite 경로보다 메모리도 덜 쓴다.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

# 빌더 import는 호출 시점으로 미룬다. 이 레포의 다른 빌드 스크립트와 같은 규약이고,
# kpubdata-builder가 없는 환경에서도 모듈이 import는 되게 한다.
if TYPE_CHECKING:
    from kpubdata_builder.uploads.models import UploadMetadata


class FileUploadRepository:
    """``UploadRepository`` Protocol의 파일 기반 구현.

    owner_id마다 디렉터리를 하나 쓴다. 빌더의 계약과 달리 크기 상한이 없다 — 원천은
    이미 스냅샷으로 얼려 검증된 바이트라서, 여기서 다시 거를 것이 없다.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _dir(self, owner_id: str) -> Path:
        # owner_id를 경로로 그대로 쓰지 않는다. 호출자가 정하는 값이고, 경로
        # 구분자가 섞이면 root 밖으로 샌다.
        digest = hashlib.sha256(owner_id.encode("utf-8")).hexdigest()[:16]
        return self._root / digest

    def _paths(self, owner_id: str, upload_id: str) -> tuple[Path, Path]:
        base = self._dir(owner_id)
        return base / f"{upload_id}.bin", base / f"{upload_id}.json"

    def put(
        self,
        owner_id: str,
        *,
        content: bytes,
        format: str,  # noqa: A002 - 빌더의 계약 필드명과 맞춘다
        encoding: str,
        original_filename: str | None,
        max_bytes: int | None = None,
    ) -> UploadMetadata:
        if max_bytes is not None and len(content) > max_bytes:
            raise ValueError(f"upload exceeds {max_bytes} bytes")
        from kpubdata_builder.uploads.models import UploadMetadata

        upload_id = f"upl_{secrets.token_hex(16)}"
        metadata = UploadMetadata(
            upload_id=upload_id,
            format=format,
            encoding=encoding,
            size_bytes=len(content),
            original_filename=original_filename,
            created_at=datetime.now(UTC).isoformat(),
        )
        blob, meta = self._paths(owner_id, upload_id)
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(content)
        meta.write_text(json.dumps(metadata.__dict__), encoding="utf-8")
        return metadata

    def get_metadata(self, owner_id: str, upload_id: str) -> UploadMetadata | None:
        _, meta = self._paths(owner_id, upload_id)
        if not meta.exists():
            return None
        from kpubdata_builder.uploads.models import UploadMetadata

        payload: dict[str, Any] = json.loads(meta.read_text(encoding="utf-8"))
        return UploadMetadata(**payload)

    def get_content(self, owner_id: str, upload_id: str) -> bytes | None:
        blob, _ = self._paths(owner_id, upload_id)
        return blob.read_bytes() if blob.exists() else None

    def delete(self, owner_id: str, upload_id: str) -> bool:
        blob, meta = self._paths(owner_id, upload_id)
        if not meta.exists():
            return False
        blob.unlink(missing_ok=True)
        meta.unlink()
        return True

    def list_for_owner(self, owner_id: str) -> list[UploadMetadata]:
        from kpubdata_builder.uploads.models import UploadMetadata

        base = self._dir(owner_id)
        if not base.exists():
            return []
        return [
            UploadMetadata(**json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(base.glob("*.json"))
        ]
