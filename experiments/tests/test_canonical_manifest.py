"""canonical manifest 가 커밋된 결과 파일과 일치하는지 (#51 후속).

``scripts/paper_tables.py:check_manifest`` 가 이 대조를 표 생성 **전에** 한다 —
표와 그림이 오래된 결과를 읽지 못하게 하는 장치다. 그런데 그 게이트는 표를 만들
때만 돈다. manifest 가 틀어져 있으면 아무도 표를 만들지 않는 동안에는 조용하고,
다음 사람이 만들려는 순간 멈춘다.

실제로 그런 일이 있었다. ``perturbation_counterfactual.json`` 의 해시가 결과
최초 커밋(99ab145)부터 어긋나 있었다 — 파일은 그 뒤로 한 번도 바뀌지 않았으므로
manifest 쪽이 처음부터 틀린 것이다. 그 사이 커밋된 표는 이 게이트를 통과해 만들어질
수 없었다.

테스트로 옮겨 CI 가 매번 확인하게 한다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

_RESULTS = Path(__file__).resolve().parents[1] / "results"
_MANIFEST = _RESULTS / "canonical_manifest.json"


def _manifest() -> dict[str, object]:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_every_recorded_file_exists() -> None:
    missing = [name for name in _manifest()["results"] if not (_RESULTS / name).is_file()]

    assert not missing, f"manifest 에 있으나 파일이 없다: {missing}"


def test_every_recorded_hash_matches_the_file() -> None:
    stale = []
    for name, recorded in _manifest()["results"].items():
        actual = hashlib.sha256((_RESULTS / name).read_bytes()).hexdigest()
        if actual != recorded:
            stale.append((name, recorded[:12], actual[:12]))

    assert not stale, f"manifest 와 다른 결과 파일 (name, recorded, actual): {stale}"


def test_the_canonical_pair_is_recorded() -> None:
    # 어느 paper 커밋과 어느 builder 로 만든 결과인지가 남아 있어야, 표에 실린
    # 숫자가 무엇을 잰 것인지 나중에도 말할 수 있다.
    manifest = _manifest()

    assert len(str(manifest["paper_sha"])) == 40
    assert len(str(manifest["builder_sha"])) == 40
    assert str(manifest["builder_identity"]).startswith("0.4.0.dev0+")


def test_the_counterfactual_file_agrees_with_the_manifest_provenance() -> None:
    """이 파일은 자기 안에 builder/paper 신원을 담는다 — 교차 확인한다.

    manifest 해시가 틀렸을 때 "파일이 낡은 것인가, manifest 가 틀린 것인가" 를
    가르는 근거가 이것이었다.
    """
    manifest = _manifest()
    counterfactual = _RESULTS / "perturbation_counterfactual.json"
    payload = json.loads(counterfactual.read_text(encoding="utf-8"))

    assert payload["paper_sha"] == manifest["paper_sha"]
    assert payload["builder"] == manifest["builder_identity"]
