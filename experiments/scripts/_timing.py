"""timing 프로토콜 — 두 엔진 러너가 공유한다 (표준 라이브러리만 쓴다).

pandas 러너는 harness 가상환경, polars 러너는 builder 가상환경에서 돈다. 두 환경에
공통으로 있는 것은 표준 라이브러리뿐이라, 무엇을 몇 번 어떤 순서로 재는지는 여기
한 곳에만 둔다. 엔진은 같은 여섯 함수(``read``/``write``/``contract``/``gold``/
``analyze``/``digest``)만 채운다.

## 두 전략

같은 엔진 함수를 쓰고, **계층을 저장했다가 다시 읽는가**만 다르다.

- ``materialized`` — 시나리오가 무효화한 계층부터 다시 만들고 기록한 뒤 다음 계층이
  그것을 읽는다. 무효화되지 않은 계층은 저장된 것을 읽는다.
- ``monolithic`` — 매번 Bronze에서 계약·Gold 변환·분석까지 메모리에서 간다. 아무것도
  기록하지 않는다.

계약은 축약이 아니라 **전체 계약**(``*_spec.SPEC["contract"]``)이다.

## 시나리오 (무엇이 바뀌었나 → materialized가 어디부터 다시 하나)

- S1 분석만 바뀜 → 저장된 Gold를 읽어 분석
- S2 Gold 수준 변경 → 저장된 Silver에서 Gold를 다시 만들고 기록
- S3 계약/Silver 수준 변경 → Bronze에서 과제가 읽는 모든 Silver와 Gold를 다시 만들고 기록
- S4 원천 변경 → 새 Bronze에서 과제가 읽는 모든 Silver와 Gold를 다시 만들고 기록

S3와 S4는 materialized가 하는 일이 같다. builder에 증분 경로가 없어 원천이 바뀌어도
Silver 전체를 다시 만들기 때문이다. 둘은 무효화 사유(계약 대 스냅샷)가 달라 따로
보고하되, 숫자가 같게 나오는 것이 예상이다. T3에서 한 원천만 바뀌어 다른 Silver를
재사용하는 경우는 재지 않는다.

변경의 **내용**은 넣지 않는다. 모든 셀이 기준 recipe를 실행해 같은 분석 결과를 내야
하고, 그래서 매 실행의 결과가 기준과 같은지(``equivalent``)로 정합성을 본다. 시나리오가
정하는 것은 어느 계층부터 다시 계산하는가다.

pandas는 결과가 바이트 단위로 결정적이라 ``output_hash``가 Gold 조건의 기준 해시와 같아야
한다. polars는 병렬 group-by가 합산 순서를 매번 바꿔 부동소수 마지막 자리가 흔들린다 —
T3에서 실제로 실행마다 해시가 달랐다. 그래서 polars는 준비 실행 결과와 키는 정확히,
값은 상대오차 ``RTOL`` 안에서 같은지를 본다. ``output_hash``는 두 엔진 모두 그대로 남긴다.

## 타이머 안과 밖

안: 그 시나리오에 필요한 read, 변환, materialization write, 분석.
밖: 결과 해시, 로그, 결과 파일 기록, provenance·identity 계산.

## 입력

두 전략이 같은 Bronze Parquet을 읽는다. 원천 JSONL을 Bronze Parquet으로 적재하는 일
(builder의 ``records_to_dataframe``과 ``read_as``)은 두 전략 모두 밖에 둔다 — 적재 비용과
JSONL 파싱 엔진 차이가 계층 효과와 섞였던 것이 이전 측정의 문제였다.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import platform
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

EXPERIMENTS = Path(__file__).resolve().parents[1]
WORK = EXPERIMENTS / ".build" / "timing"
RESULTS = EXPERIMENTS / "results"

TRADES = "seoul-apartment-trades"
RENTS = "seoul-apartment-rent"

#: 과제마다 읽는 데이터셋.
TASKS: dict[str, tuple[str, ...]] = {"task01": (TRADES,), "task03": (TRADES, RENTS)}
SCENARIOS: tuple[str, ...] = ("S1", "S2", "S3", "S4")
STRATEGIES: tuple[str, ...] = ("materialized", "monolithic")

#: materialized가 다시 만들기 시작하는 계층.
REBUILD_FROM: dict[str, str] = {"S1": "gold", "S2": "silver", "S3": "bronze", "S4": "bronze"}

WARMUP_RUNS = 1
MEASURED_RUNS = 5
INPUT_FORMAT = "parquet"

#: 엔진 간, polars 실행 간 수치 비교의 상대 허용오차.
RTOL = 1e-9

#: 실제 Gold 조건으로 낸 분석 결과의 digest (``kpx.results.output_digest``). pandas
#: 엔진의 모든 실행이 이것과 같아야 한다.
REFERENCE_HASH: dict[str, str] = {
    "task01": "bc8896c454ab10a4a66ed2db37d4e2c600babc96de43351beb15f059254470b6",
    "task03": "607132358d10a8c87949e604a774e42798c073b4cac227798bd198d446693351",
}


class Engine(Protocol):
    name: str

    def read(self, path: Path) -> Any: ...
    def write(self, frame: Any, path: Path) -> None: ...
    def contract(self, bronze: Any, dataset: str) -> Any: ...
    def gold(self, task: str, silvers: dict[str, Any]) -> Any: ...
    def analyze(self, task: str, gold: Any) -> Any: ...
    def digest(self, result: Any) -> str: ...


@dataclass(frozen=True)
class Layout:
    """엔진 하나가 읽고 쓰는 파일. Bronze는 두 엔진이 같은 파일을 읽는다."""

    root: Path

    def bronze(self, dataset: str) -> Path:
        return self.root / "bronze" / f"{dataset}.parquet"

    def silver(self, engine: str, dataset: str) -> Path:
        return self.root / engine / "silver" / f"{dataset}.parquet"

    def gold(self, engine: str, task: str) -> Path:
        return self.root / engine / "gold" / f"{task}.parquet"


def materialized(engine: Engine, layout: Layout, task: str, scenario: str) -> Any:
    start = REBUILD_FROM[scenario]
    datasets = TASKS[task]
    if start == "bronze":
        for dataset in datasets:
            silver = engine.contract(engine.read(layout.bronze(dataset)), dataset)
            engine.write(silver, layout.silver(engine.name, dataset))
    if start in ("bronze", "silver"):
        silvers = {d: engine.read(layout.silver(engine.name, d)) for d in datasets}
        engine.write(engine.gold(task, silvers), layout.gold(engine.name, task))
    return engine.analyze(task, engine.read(layout.gold(engine.name, task)))


def monolithic(engine: Engine, layout: Layout, task: str, scenario: str) -> Any:
    del scenario  # 무엇이 바뀌었든 매번 처음부터 한다.
    silvers = {d: engine.contract(engine.read(layout.bronze(d)), d) for d in TASKS[task]}
    return engine.analyze(task, engine.gold(task, silvers))


STRATEGY: dict[str, Callable[[Engine, Layout, str, str], Any]] = {
    "materialized": materialized,
    "monolithic": monolithic,
}


@dataclass(frozen=True)
class Slot:
    task: str
    scenario: str
    strategy: str
    round: int  # 0 = warm-up
    order_position: int

    @property
    def warmup(self) -> bool:
        return self.round == 0


def schedule(
    tasks: tuple[str, ...] = tuple(TASKS),
    scenarios: tuple[str, ...] = SCENARIOS,
    repeats: int = MEASURED_RUNS,
) -> Iterator[Slot]:
    """셀(task × scenario)마다 warm-up 한 round, 측정 ``repeats`` round.

    round 안에서 두 전략을 번갈아 돌리고, 홀수 round와 짝수 round의 순서를 뒤집는다
    (AB, BA, AB, …). 시간에 따라 기계 상태가 흘러도 한 전략에만 쌓이지 않게 하기
    위해서다. 무작위가 아니라 고정 순서라 다시 돌려도 같다.
    """
    for task in tasks:
        for scenario in scenarios:
            for round_ in range(1 - WARMUP_RUNS, repeats + 1):
                order = STRATEGIES if round_ % 2 == 1 or round_ <= 0 else STRATEGIES[::-1]
                for position, strategy in enumerate(order):
                    yield Slot(task, scenario, strategy, max(round_, 0), position)


def time_once(fn: Callable[[], Any]) -> tuple[float, Any]:
    """``kpx.metrics.runtime._time_once``와 같은 방식 — gc를 비우고 wall time 한 번."""
    gc.collect()
    started = time.perf_counter()
    value = fn()
    return time.perf_counter() - started, value


def measure(
    engine: Engine,
    layout: Layout,
    slots: Iterator[Slot],
    fixed: dict[str, Any],
    equivalent: Callable[[str, Any], bool],
) -> list[dict[str, Any]]:
    """``equivalent(task, result)``는 타이머 밖에서 그 실행의 결과가 기준과 같은지 본다."""
    rows = []
    for slot in slots:
        seconds, result = time_once(
            lambda s=slot: STRATEGY[s.strategy](engine, layout, s.task, s.scenario)
        )
        rows.append(
            {
                "task": slot.task,
                "engine": engine.name,
                "scenario": slot.scenario,
                "strategy": slot.strategy,
                "round": slot.round,
                "warmup": slot.warmup,
                "order_position": slot.order_position,
                "seconds": seconds,
                "input_format": INPUT_FORMAT,
                "output_hash": engine.digest(result),
                "equivalent": equivalent(slot.task, result),
                **fixed,
            }
        )
        print(
            f"{slot.task} {slot.scenario} r{slot.round} {slot.strategy:<12} {seconds:8.3f}s",
            flush=True,
        )
    return rows


def git_head(repo: Path) -> tuple[str, bool]:
    """``(commit, dirty)``. dirty는 추적 중인 파일의 변경만 본다."""

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        ).stdout.strip()

    return git("rev-parse", "HEAD"), bool(git("status", "--porcelain", "--untracked-files=no"))


def environment(**engine_versions: str) -> tuple[str, dict[str, Any]]:
    """기계를 가리키는 ``environment_id``와 그 내용.

    id에는 기계만 넣는다 — 두 엔진 러너가 같은 기계에서 돌았는지를 이것으로 본다.
    엔진·파이썬 버전은 내용에만 적는다.
    """
    machine = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
    }
    digest = hashlib.sha256(json.dumps(machine, sort_keys=True).encode()).hexdigest()[:12]
    return digest, {**machine, "python": platform.python_version(), **engine_versions}
