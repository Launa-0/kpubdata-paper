# appendix_perturbation

변형 51개 (P: 의미 보존 31, B: 의미 파괴 20). fixture는 원천의 계통 추출 약 5,000행.

| mutation | dataset | kind | n_cells_mutated | observed | verdict | failure_stage | contract_class |
|---|---|---|---|---|---|---|---|
| T-P00 | trades | P | 4,971 | accept_equiv | correct_accept | — | — |
| T-P01 | trades | P | 4,971 | accept_equiv | correct_accept | — | — |
| T-P02 | trades | P | 4,971 | accept_equiv | correct_accept | — | — |
| T-P03 | trades | P | 2,486 | reject | false_reject | silver/tabularize | — |
| T-P04 | trades | P | 4,971 | accept_equiv | correct_accept | — | — |
| T-P05 | trades | P | 2,486 | reject | false_reject | silver/tabularize | — |
| T-P06 | trades | P | 14,913 | accept_equiv | correct_accept | — | — |
| T-P07 | trades | P | 4,971 | accept_equiv | correct_accept | — | — |
| T-P08 | trades | P | 9,942 | accept_equiv | correct_accept | — | — |
| T-P09 | trades | P | 3,725 | accept_equiv | correct_accept | — | — |
| T-P10 | trades | P | 28,777 | accept_nonequiv | silent_corruption | — | — |
| T-P11 | trades | P | 4,971 | accept_equiv | correct_accept | — | — |
| T-P12 | trades | P | 4,971 | accept_equiv_warn | correct_accept | — | — |
| T-B01 | trades | B | 4,971 | reject | correct_reject | silver/rename | declared_or_covered |
| T-B02 | trades | B | 4,971 | reject | correct_reject | silver/rename | declared_or_covered |
| T-B03 | trades | B | 4,971 | reject | correct_reject | silver/rename | declared_or_covered |
| T-B04 | trades | B | 4,971 | accept_nonequiv | false_accept | — | undeclared_but_expressible |
| T-B05 | trades | B | 4,971 | accept_nonequiv | false_accept | — | undeclared_but_expressible |
| T-B06 | trades | B | 4,971 | accept_nonequiv | false_accept | — | undeclared_but_expressible |
| T-B07 | trades | B | 4,971 | reject | correct_reject | silver/cast | declared_or_covered |
| T-B08 | trades | B | 4,971 | reject | correct_reject | silver/rename | declared_or_covered |
| T-B09 | trades | B | 4,804 | reject | correct_reject | silver/derived | declared_or_covered |
| T-B10 | trades | B | 498 | accept_nonequiv | false_accept | — | undeclared_but_expressible |
| B-P00 | bike | P | 4,959 | accept_equiv | correct_accept | — | — |
| B-P01 | bike | P | 1,746 | accept_equiv | correct_accept | — | — |
| B-P02 | bike | P | 828 | accept_equiv | correct_accept | — | — |
| B-P03 | bike | P | 2,594 | accept_equiv | correct_accept | — | — |
| B-P04 | bike | P | 20 | reject | false_reject | silver/cast | — |
| B-P05 | bike | P | 4,958 | accept_equiv | correct_accept | — | — |
| B-P06 | bike | P | 0 | accept_equiv | correct_accept | — | — |
| B-P07 | bike | P | 4,959 | reject | false_reject | silver/zfill | — |
| B-P08 | bike | P | 4,959 | accept_equiv | correct_accept | — | — |
| B-P09 | bike | P | 4,959 | accept_equiv | correct_accept | — | — |
| B-P10 | bike | P | 2,480 | accept_equiv | correct_accept | — | — |
| B-P11 | bike | P | 4,959 | accept_equiv | correct_accept | — | — |
| B-P12 | bike | P | 9,918 | accept_equiv | correct_accept | — | — |
| B-P13 | bike | P | 9,918 | accept_equiv | correct_accept | — | — |
| B-P14 | bike | P | 4,959 | accept_equiv | correct_accept | — | — |
| B-P15 | bike | P | 4,959 | accept_equiv_warn | correct_accept | — | — |
| B-P16 | bike | P | 4,959 | accept_equiv | correct_accept | — | — |
| B-P17 | bike | P | 9,918 | accept_equiv | correct_accept | — | — |
| B-B01 | bike | B | 4,959 | reject | correct_reject | silver/rename | declared_or_covered |
| B-B02 | bike | B | 4,959 | reject | correct_reject | silver/rename | declared_or_covered |
| B-B03 | bike | B | 9,918 | reject | correct_reject | silver/rename | declared_or_covered |
| B-B04 | bike | B | 4,959 | reject | correct_reject | silver/rename | declared_or_covered |
| B-B05 | bike | B | 4,543 | accept_nonequiv | false_accept | — | not_expressible |
| B-B06 | bike | B | 4,955 | accept_nonequiv | false_accept | — | not_expressible |
| B-B07 | bike | B | 4,959 | accept_nonequiv | false_accept | — | not_expressible |
| B-B08 | bike | B | 4,959 | reject | correct_reject | silver/cast | declared_or_covered |
| B-B09 | bike | B | 4,959 | reject | correct_reject | silver/coalesce | declared_or_covered |
| B-B10 | bike | B | 496 | accept_nonequiv | false_accept | — | undeclared_but_expressible |
