# kpubdata-paper

한국 공공데이터에 Medallion 파이프라인(Bronze → Silver → Gold)을 적용했을 때를 평가한
ACK 2026 논문의 실험 저장소다.

- 계약 기반 표준화가 원천 표현을 무엇으로 바꾸는가 (RQ1)
- 계층 materialization이 준비 코드와 재계산 비용을 어떻게 바꾸는가 (RQ2)
- 고정 계약이 무엇을 재현하고 어디서 멈추는가 (RQ3)

실험 설계, 데이터, 결과, provenance, 재현 절차는 [`experiments/README.md`](experiments/README.md)에
있다. 논문의 모든 숫자는 `experiments/results/`에서, 표와 그림은 `experiments/tables/`,
`experiments/figures/`에서 나온다.
