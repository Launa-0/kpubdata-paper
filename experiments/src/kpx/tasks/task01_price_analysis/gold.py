"""Task 1 / Gold 조건 — 과제용으로 이미 집계된 데이터셋에서 시작한다.

Gold는 자치구 × 월 집계까지만 담는다. 추세·YoY·순위는 담지 않는다 — 담으면 Gold
조건이 "정답을 미리 저장해 둔" 셈이 되어 비교가 무의미해진다 (Internal Validity).
"""

from __future__ import annotations

from kpx.contract import AnalysisInput, RunContext


class Runner:
    TASK = "task01"
    CONDITION = "gold"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        return AnalysisInput(frame=ctx.load("seoul-apartment-trades"))
