"""Task 3 — 매매·전월세 통합 및 전세가율 분석 (#15).

논문의 핵심 integration experiment다. Task 1이 한 데이터셋 안에서의 정제 비용을
잰다면, 여기서는 **두 데이터셋을 잇는 비용**을 잰다.

매칭률에 대하여 — 여기서 재는 것과 재지 않는 것
--------------------------------------------

이슈 #15는 Bronze에서 단지명 표준화가 없어 매칭률이 떨어질 것으로 예상했다.
그렇게 구현하지 **않았다.**

Bronze 조건도 ``normalize_apt_name`` 을 호출한다. 부르지 않으면 raw 단지명으로
조인하게 되어 매칭률이 실제로 떨어지지만, 그것은 데이터 계층의 효과가 아니라
**baseline을 일부러 못 하게 만든 것**이다. 정제 규칙을 조건마다 다르게 두지
않는다는 것이 이 연구의 통제 조건이고 (#12), 그 통제는 monolithic에만 적용되는
것이 아니다.

그래서 Bronze / Silver / Monolithic의 ``join_matching_rate`` 는 **설계상 같아야
한다.** 같지 않게 나오면 세 조건이 서로 다른 정제를 한 것이므로 버그다 — 테스트가
그것을 고정한다.

그러면 Task 3가 재는 차이는 무엇인가:

* **RQ2 (비용).** 올바른 조인에 도달하기까지의 전처리 비용. Bronze는 두 데이터셋의
  키를 모두 직접 만들어야 하고, Silver는 파생값과 조인만, Gold는 아무것도 하지
  않는다. 조인이 있는 과제에서 계층의 효과가 가장 크게 벌어질 자리다.
* **RQ3 (정확성).** 네 조건이 **같은 전세가율에 도달하는가**. Gold는 조인이
  파이프라인 시점에 일어났으므로, Gold의 값이 나머지와 어긋난다면 그것은 파이프라인이
  분석과 다른 규칙으로 조인했다는 뜻이다. 계층화가 조용히 결과를 바꿀 수 있는
  지점이고, 이것이 이 과제의 실질적 correctness 발견이 된다.
* **invalid key rate.** Bronze와 Monolithic은 조인 키를 만들지 못한 행을 스스로
  찾아 버려야 한다. Silver는 계층이 이미 보장한다.

매칭률이 조건 간에 같다는 것은 null result이지만 정직한 null result이고, 논문의
Threats to Validity에서 baseline bias를 다룰 때 그대로 쓸 수 있다.
"""

from __future__ import annotations

from kpx.runner import Task
from kpx.tasks.task03_join import analysis, bronze, gold, monolithic, silver
from kpx.tasks.task03_join import transforms as transforms_module

TASK = Task(
    name="task03",
    dataset="seoul-apartment-trades+seoul-apartment-rent",
    analyze=analysis.analyze,
    runners={
        "bronze": bronze.Runner(),
        "silver": silver.Runner(),
        "gold": gold.Runner(),
        "monolithic": monolithic.Runner(),
    },
    transforms=transforms_module,
)

__all__ = ["TASK", "analysis", "bronze", "gold", "monolithic", "silver"]
