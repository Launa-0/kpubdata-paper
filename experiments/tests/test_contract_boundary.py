"""RQ3 재현 경로 — perturbation 판정, R2 결과표, storage 통제 조건.

빌드 자체는 builder 환경에서 돌므로 여기서는 판정 규칙과 검증만 고정한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pandas as pd  # noqa: E402
import paper_tables  # noqa: E402
import perturbation  # noqa: E402
import r2_report  # noqa: E402
import storage_footprint  # noqa: E402


class TestPerturbationVerdict:
    @pytest.mark.parametrize(
        ("kind", "observed", "expected"),
        [
            ("P", "accept_equiv", "correct_accept"),
            ("P", "accept_equiv_warn", "correct_accept"),
            ("P", "accept_nonequiv", "silent_corruption"),
            ("P", "reject", "false_reject"),
            ("B", "reject", "correct_reject"),
            ("B", "accept_nonequiv_warn", "warned"),
            ("B", "accept_nonequiv", "false_accept"),
            ("B", "accept_equiv", "false_accept"),
        ],
    )
    def test_verdict(self, kind: str, observed: str, expected: str) -> None:
        assert perturbation.verdict(kind, observed) == expected

    def test_there_are_twenty_semantics_breaking_mutations(self) -> None:
        kinds = [kind for _, kind, _ in perturbation.MUTATIONS.values()]
        assert kinds.count("B") == 20

    def test_a_rejection_is_located_by_its_message(self) -> None:
        message = "coalesce target 'ym_raw' found none of its candidates"
        assert perturbation.classify(message, ("bronze",)) == "silver/coalesce"

    def test_a_mutation_counts_only_the_cells_it_changed(self) -> None:
        rows = [{"dealAmount": "1,000"}, {"dealAmount": "2,000"}, {}]
        changed = perturbation.MUTATIONS["T-P02"][2](rows)
        assert changed == 2
        assert rows[0]["dealAmount"] == "1000"


def _observation(generation: str, **overrides: object) -> dict[str, object]:
    return {
        "generation": generation,
        "snapshot_id": "x",
        "rows_in": 1,
        "status": "ok",
        "failed_stage": None,
        "error": None,
        "rows_out": 1,
        "builder": "0.4.0.dev0+096d023f9546",
        "paper_sha": "abc",
        **overrides,
    }


class TestSourceEvolutionTable:
    def test_every_generation_under_one_contract(self) -> None:
        frame = r2_report.table([_observation(g) for g in r2_report.GENERATIONS])
        assert list(frame["generation"]) == list(r2_report.GENERATIONS)
        assert frame["config_hash"].nunique() == 1

    def test_a_missing_generation_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="세대"):
            r2_report.table([_observation(g) for g in list(r2_report.GENERATIONS)[:-1]])

    def test_generations_built_by_different_builders_are_refused(self) -> None:
        observations = [_observation(g) for g in r2_report.GENERATIONS]
        observations[0]["builder"] = "0.4.0.dev0+5d86eedf3a1a"
        with pytest.raises(SystemExit, match="builder"):
            r2_report.table(observations)


class TestStorageControl:
    def _footer(self, **overrides: object) -> dict[str, object]:
        return {
            "codecs": ["ZSTD"],
            "row_groups": [131_072, 131_072, 5],
            "created_by": "parquet-cpp-arrow version 25.0.1",
            **overrides,
        }

    def test_the_same_writer_codec_and_row_groups_pass(self) -> None:
        footers = {("a", "bronze"): self._footer(), ("a", "silver"): self._footer()}
        assert storage_footprint.check_controlled(footers) == []

    @pytest.mark.parametrize(
        "override",
        [
            {"codecs": ["SNAPPY"]},
            {"row_groups": [100_000, 5]},
            {"created_by": "polars"},
        ],
    )
    def test_a_broken_control_is_refused(self, override: dict[str, object]) -> None:
        footers = {("a", "bronze"): self._footer(), ("a", "silver"): self._footer(**override)}
        assert storage_footprint.check_controlled(footers)


class TestPaperTables:
    def _breaks(self, silent: set[str]) -> pd.DataFrame:
        ids = [f"T-B{i:02d}" for i in range(1, 11)] + [f"B-B{i:02d}" for i in range(1, 11)]
        return pd.DataFrame(
            {
                "mutation": ids,
                "kind": "B",
                "verdict": ["false_accept" if m in silent else "correct_reject" for m in ids],
            }
        )

    def test_silent_passes_are_split_into_the_two_contract_classes(self) -> None:
        breaks = paper_tables.classify_breaks(self._breaks(set(paper_tables.SILENT_PASS)))
        table = paper_tables.rq3_perturbation(breaks).set_index("contract_class")
        assert table.loc["total", "rejected"] == 12
        assert table.loc["undeclared_but_expressible", "silent_pass"] == 5
        assert table.loc["not_expressible", "silent_pass"] == 3

    def test_a_different_silent_set_is_refused(self) -> None:
        silent = set(paper_tables.SILENT_PASS) - {"B-B07"} | {"T-B09"}
        with pytest.raises(SystemExit, match="분류표"):
            paper_tables.classify_breaks(self._breaks(silent))
