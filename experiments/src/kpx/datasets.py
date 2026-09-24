"""계층별 산출물을 읽어 조건 러너에게 넘긴다.

러너는 자기가 읽는 파일이 어디 있는지 몰라야 한다 — 그래야 같은 러너를 다른
스냅샷이나 다른 빌드에 그대로 돌릴 수 있다. 경로를 아는 곳은 여기 한 곳이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from kpx.contract import Layer


class DatasetNotBuilt(FileNotFoundError):
    """요청한 계층이 아직 빌드되지 않았다."""


def read_artifact(path: Path) -> pd.DataFrame:
    """계층 산출물을 저장 형식에 맞게 읽는다.

    Bronze JSONL은 값을 문자열 그대로 둔다 — pandas가 알아서 숫자·날짜로 바꿔 주면
    Bronze 조건의 준비 코드가 해야 할 파싱을 로더가 대신 한 셈이 된다.
    """
    if path.suffix == ".jsonl":
        return pd.read_json(path, lines=True, dtype=False, convert_dates=False)
    return pd.read_parquet(path)


@dataclass(frozen=True)
class LayerStore:
    """``(dataset, layer) -> 파일`` 을 해석하는 resolver.

    과제 실행(T1/T3 네 조건)에서 Bronze는 원천 표현을 그대로 보존한 JSONL이고,
    Silver/Gold는 parquet이다. Bronze를 parquet으로 미리 바꿔 두면 그 변환이 조건의
    준비 코드가 할 일을 대신 하는 셈이 되므로, 저장 형식도 계층의 일부로 둔다.
    실행 시간은 여기서 재지 않는다 — timing은 두 전략이 같은 Bronze Parquet을 읽도록
    ``scripts/_timing.py``가 따로 잰다.
    """

    paths: dict[tuple[str, Layer], Path]

    def load(self, dataset: str, layer: Layer) -> pd.DataFrame:
        return read_artifact(self.path_for(dataset, layer))

    def path_for(self, dataset: str, layer: Layer) -> Path:
        try:
            path = self.paths[(dataset, layer)]
        except KeyError as exc:
            raise DatasetNotBuilt(f"no {layer} artifact registered for {dataset!r}") from exc
        if not path.exists():
            raise DatasetNotBuilt(f"{layer} artifact for {dataset!r} is not built: {path}")
        return path

    def path(self, dataset: str, layer: Layer) -> str:
        """``DatasetResolver`` 계약이 요구하는 문자열 경로."""
        return str(self.path_for(dataset, layer))


def schema_report(frame: pd.DataFrame) -> pd.DataFrame:
    """계층 산출물의 스키마 문서 (#7).

    "Silver에서 정규화했다"는 서술만으로는 독자가 무엇이 어떤 타입이 되었는지 확인할
    수 없다. 컬럼·타입·결측률·실제 값 하나를 같이 적어 Silver 계약이 실제로 적용된
    결과를 그대로 보이게 한다.
    """
    rows = []
    for column in frame.columns:
        values = frame[column]
        present = values.dropna()
        rows.append(
            {
                "Column": column,
                "Type": str(values.dtype),
                "Non-null": len(present) / len(frame) if len(frame) else 0.0,
                "Example": str(present.iloc[0]) if len(present) else "",
            }
        )
    return pd.DataFrame(rows)
