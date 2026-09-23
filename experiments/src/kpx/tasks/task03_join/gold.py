"""Task 3 / Gold 조건 — 조인까지 끝난 자치구 × 월 데이터셋에서 시작한다.

Gold는 매칭된 매매·전세의 자치구 × 월 평균까지만 담는다. 전세가율과 그 추세는
담지 않는다 — 담으면 Gold 조건이 "정답을 미리 저장해 둔" 셈이 되어 비교가
무의미해진다 (Internal Validity).

조인이 파이프라인 쪽으로 넘어갔으므로 이 조건은 조인 진단값을 스스로 만들지
못한다. 그 값은 Gold를 만든 빌드의 provenance에 남는다.
"""

from __future__ import annotations

from kpx.contract import AnalysisInput, RunContext


class Runner:
    TASK = "task03"
    CONDITION = "gold"

    def prepare(self, ctx: RunContext) -> AnalysisInput:
        return AnalysisInput(frame=ctx.load("seoul-apartment-trades-rent-monthly"))
