"""빌드를 실행한 빌더 코드의 신원.

패키지 버전만으로는 실행 코드를 식별할 수 없다. 실제로 그랬다 — 기존 빌드 세 건의
manifest가 ``builder_version: 0.1.0``을 적었는데, 설치 메타데이터가 editable 설치에서
낡아 있었기 때문이다. 같은 환경을 재설치하니 ``0.4.0.dev0``이 나왔다. 즉 두 값이
가리키는 코드는 같은데 기록은 달랐고, 반대로 **다른 코드가 같은 버전을 적을 수도**
있다. 지금 쓰는 기능(``read_as``/``null_tokens``/``float_comma``)이 아직 병합되지
않은 브랜치에 있어서 더 그렇다 — main을 받은 독자는 같은 ``pipeline_version``으로
빌드에 실패한다.

그래서 커밋을 기록한다.

    0.4.0.dev0+518fe2f0312f              clean
    0.4.0.dev0+518fe2f0312f.dirty.a1b2…  작업 트리가 커밋과 다름

이 문자열은 이제 "버전"이 아니라 **빌더 코드의 신원**이다. ``BuildInputs``의 필드명은
``pipeline_version``으로 두되, 문서에서는 그렇게 부른다.

## dirty 판정

``git status --porcelain``의 결과가 한 줄이라도 있으면 dirty다. 이 명령은
``.gitignore``와 ``.git/info/exclude``를 이미 존중하므로, 빌드와 무관한 로컬 산출물은
거기에 등록해 두면 신원이 흔들리지 않는다.

diff 해시에는 **추적되지 않는 파일의 내용도 넣는다.** ``git diff HEAD``만 쓰면 새로
만든 파이썬 파일 하나가 import되는데 해시에는 안 잡히는 구멍이 생긴다.

## 최종 실험에서는 dirty를 허용하지 않는다

``.dirty.<hash>``는 파일럿과 조사를 추적하기 위한 장치다. 논문에 싣는 R1/R2는
clean commit에서 다시 만든다 — 해시는 무엇이 달랐는지 복원해 주지 않는다.

## 기록하지 않는 것

시각, 절대경로, hostname. 같은 코드에서 매번 달라지는 값이 들어가면 스냅샷과 빌드의
digest가 흔들려 R1이 재려는 결정성을 스스로 깬다.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

FILENAME = "builder_identity.json"

#: dirty 표시에 붙이는 diff 해시 길이. snapshot id·config hash와 같은 폭이다.
DIGEST_PREFIX = 12


def _git(repo: Path, *args: str) -> str:
    # UTF-8을 명시한다. text=True만 주면 Windows에서 locale(cp949)로 디코드하다
    # 한국어 diff에서 reader 스레드가 죽고 stdout이 None이 된다.
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


def _repo_of(module: Any) -> Path | None:
    """editable 설치라면 그 레포. 아니면 ``None``."""
    path = Path(module.__file__).resolve()
    for candidate in [path, *path.parents]:
        if (candidate / ".git").exists():
            return candidate
    return None


def _worktree_digest(repo: Path, status: str) -> str:
    """커밋과 작업 트리의 차이를 한 해시로.

    추적된 변경은 ``git diff HEAD``가, 추적되지 않은 파일은 그 내용이 들어간다.
    경로는 git이 주는 상대경로 그대로라 기계가 달라져도 같은 값이 나온다.
    """
    hasher = hashlib.sha256()
    hasher.update(_git(repo, "diff", "HEAD").encode("utf-8", "replace"))
    for line in sorted(status.splitlines()):
        if not line.startswith("??"):
            continue
        name = line[3:].strip().strip('"')
        target = repo / name
        for file in sorted(target.rglob("*")) if target.is_dir() else [target]:
            if file.is_file():
                hasher.update(file.relative_to(repo).as_posix().encode("utf-8"))
                hasher.update(file.read_bytes())
    return hasher.hexdigest()


def capture() -> dict[str, Any]:
    """지금 import된 빌더가 어느 코드인지.

    빌더 환경에서 호출한다 — ``kpubdata_builder``를 import할 수 있어야 한다.
    """
    from importlib import metadata

    import kpubdata_builder

    try:
        version = metadata.version("kpubdata-builder")
    except metadata.PackageNotFoundError:
        version = getattr(kpubdata_builder, "__version__", "unknown")

    repo = _repo_of(kpubdata_builder)
    if repo is None:
        # 게시된 패키지를 설치한 경우다. 버전이 곧 신원이다.
        return {
            "package_version": version,
            "git_commit": None,
            "git_dirty": False,
            "git_diff_sha256": None,
        }

    commit = _git(repo, "rev-parse", "HEAD").strip() or None
    status = _git(repo, "status", "--porcelain")
    dirty = bool(status.strip())
    return {
        "package_version": version,
        "git_commit": commit,
        "git_dirty": dirty,
        "git_diff_sha256": _worktree_digest(repo, status) if dirty else None,
    }


def write(run_dir: Path) -> dict[str, Any]:
    """빌드 산출물 옆에 신원을 남긴다."""
    identity = capture()
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / FILENAME).write_text(
        json.dumps(identity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return identity


def read(run_dir: Path) -> dict[str, Any] | None:
    path = Path(run_dir) / FILENAME
    if not path.exists():
        return None
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def as_version(identity: dict[str, Any] | None) -> str | None:
    """``PipelineVersion``에 넘길 문자열. 신원을 모르면 ``None``."""
    if not identity:
        return None
    version = str(identity.get("package_version") or "unknown")
    commit = identity.get("git_commit")
    if not commit:
        return version
    suffix = f"+{str(commit)[:DIGEST_PREFIX]}"
    if identity.get("git_dirty"):
        digest = str(identity.get("git_diff_sha256") or "")[:DIGEST_PREFIX]
        suffix += f".dirty.{digest}" if digest else ".dirty"
    return version + suffix


def version_of(run_dir: Path) -> str:
    """측정할 빌드 디렉터리가 어느 빌더로 만들어졌는지. 모르면 멈춘다.

    체크섬만으로는 빌더를 가를 수 없다 — ``date_parts`` 수정 전후 빌더가 byte 단위로
    같은 Silver를 냈다. 측정이 어느 빌더의 빌드를 읽었는지 말하려면 이 신원이 있어야
    하고, ``record_builds.py``가 ``pipeline_version``을 만들 때 쓴 것과 같은 문자열이어야
    기록과 맞춰 볼 수 있다.
    """
    version = as_version(read(run_dir))
    if version is None:
        raise SystemExit(
            f"{run_dir}에 {FILENAME}이 없다 — 어느 빌더가 만든 산출물인지 말할 수 없다. "
            "scripts/build_silver.py로 다시 빌드하라."
        )
    return version
