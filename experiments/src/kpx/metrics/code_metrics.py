"""Code metrics for RQ2/H2: what a condition costs to prepare data with.

H2 predicts Bronze > Silver > Gold in preparation cost. The obvious way to
measure that — count the lines of the script — is also the easiest way to get a
result that means nothing, for two reasons:

* **The boundary moves.** If "preparation" is decided after the numbers are in,
  ``preprocessing_loc`` measures the author's sense of what should count.
* **LOC alone is not effort.** Four lines of dense pandas are not cheaper than
  eight readable ones.

The contract fixes the first: preparation is :meth:`ConditionRunner.prepare` and
the private helpers it calls, so the boundary is a method boundary that was
declared before any measurement (Construct Validity). This module fixes the
second by reporting four numbers, not one — lines, functions, logical steps, and
complexity as a secondary indicator.

What is measured
----------------

Starting from ``prepare``, the *reference* graph is followed through
**module-private functions and private methods of the runner class**. Everything
reachable that way is preparation code and is counted.

References, not calls: ``df["거래금액"].map(parse_price)`` never calls
``parse_price`` syntactically, it hands it to pandas, and that is the idiomatic
way a transformation is applied here. Following call targets alone would miss
most of them.

Two kinds of reference are deliberately *not* followed:

* **Library access** (``df.groupby``, ``pd.to_datetime``). Not code the
  condition had to write. Counting it would measure pandas.
* **Shared transformation helpers** imported from the task's ``transforms``
  module. Their *bodies* are not counted, but each distinct one used adds to
  ``function_count``.

The second rule is what makes the conditions comparable. Every condition draws
on the same helper module, and the monolithic baseline is required to
(``docs/monolithic-baseline.md``), so counting helper bodies would charge a
condition for code it shares with every other condition. What differs between
conditions — and what H2 is about — is how much a condition has to *do* with
those helpers before the analysis can start.

Counting rules for LOC
----------------------

Lines are counted from the token stream rather than by pattern-matching text, so
the rules hold exactly:

* blank lines are not counted
* comment lines are not counted
* the function's docstring is not counted
* a statement spanning several physical lines counts as each line it covers
* the ``def`` line and any decorators are counted — a signature is code

These rules are applied identically to all four conditions. That is the point:
an absolute LOC figure means little, but a ratio between conditions measured the
same way is what H2 needs.
"""

from __future__ import annotations

import ast
import inspect
import io
import tokenize
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import ModuleType
from typing import Any

import pandas as pd
from radon.complexity import cc_visit

from kpx.contract import CONDITIONS, Condition

PREPARE = "prepare"

#: Columns of Table 3, in the order the paper prints them.
TABLE3_METRICS: tuple[str, ...] = (
    "preprocessing_loc",
    "function_count",
    "transformation_steps",
    "cyclomatic_complexity",
)


class CodeMetricsError(RuntimeError):
    """Raised when a runner's preparation code cannot be measured."""


@dataclass(frozen=True)
class CodeMetrics:
    """What one condition's preparation costs.

    ``transformation_steps`` is ``None`` until a run records it: steps are
    counted by :class:`~kpx.steps.StepRecorder` as the preparation executes,
    not read out of the source, because a loop that normalizes twelve columns
    is one logical step however it is written.
    """

    preprocessing_loc: int
    function_count: int
    cyclomatic_complexity: int
    measured: tuple[str, ...] = ()
    transformations: tuple[str, ...] = ()
    transformation_steps: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """The result-schema fields this measurement fills in."""
        return {
            "preprocessing_loc": self.preprocessing_loc,
            "function_count": self.function_count,
            "transformation_steps": self.transformation_steps,
        }


def effective_loc(source: str) -> int:
    """Lines of ``source`` that carry code, under the module's counting rules.

    Blank lines, comments and the leading docstring do not count; a statement
    spread over several lines counts once per line it occupies.
    """
    docstring_lines = _docstring_lines(source)
    lines: set[int] = set()
    skip = {
        tokenize.COMMENT,
        tokenize.NL,
        tokenize.NEWLINE,
        tokenize.INDENT,
        tokenize.DEDENT,
        tokenize.ENDMARKER,
        tokenize.ENCODING,
    }
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in skip:
            continue
        covered = set(range(token.start[0], token.end[0] + 1))
        lines.update(covered - docstring_lines)
    return len(lines)


def measure_preparation(
    runner: object,
    *,
    transforms: ModuleType | None = None,
    steps: int | None = None,
) -> CodeMetrics:
    """Measure the preparation surface of one condition runner.

    ``runner`` may be an instance or the class itself. ``transforms`` is the
    task's shared helper module; calls into it are counted as transformations
    without their bodies being charged to this condition. ``steps`` is the
    recorded top-level step count from a run, if one has happened.
    """
    runner_class = runner if inspect.isclass(runner) else type(runner)
    module = inspect.getmodule(runner_class)
    if module is None:
        raise CodeMetricsError(f"cannot locate the module defining {runner_class!r}")

    source = inspect.getsource(module)
    tree = ast.parse(source)
    class_node = _find_class(tree, runner_class.__name__, module)
    prepare = _find_method(class_node, PREPARE, runner_class.__name__)

    shared = _public_callables(transforms) if transforms is not None else frozenset()
    module_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    class_methods = {
        node.name: node
        for node in class_node.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }

    measured: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {PREPARE: prepare}
    transformations: set[str] = set()
    pending: list[ast.FunctionDef | ast.AsyncFunctionDef] = [prepare]

    while pending:
        for name in _referenced_names(pending.pop()):
            if name in shared:
                transformations.add(name)
                continue
            if name in measured or not name.startswith("_"):
                continue
            helper = class_methods.get(name) or module_functions.get(name)
            if helper is None:
                continue
            measured[name] = helper
            pending.append(helper)

    segments = [_segment(source, node) for node in measured.values()]
    helpers = tuple(sorted(name for name in measured if name != PREPARE))

    return CodeMetrics(
        preprocessing_loc=sum(effective_loc(segment) for segment in segments),
        function_count=len(helpers) + len(transformations),
        cyclomatic_complexity=sum(_complexity(segment) for segment in segments),
        measured=(PREPARE, *helpers),
        transformations=tuple(sorted(transformations)),
        transformation_steps=steps,
    )


def table3(metrics: Mapping[tuple[str, Condition], CodeMetrics]) -> pd.DataFrame:
    """Table 3 (Analytical Effort), keyed by ``(task, condition)``.

    Conditions appear in Medallion order so that ``monolithic`` reads as the
    baseline rather than sorting between gold and silver.
    """
    if not metrics:
        return pd.DataFrame(columns=["task", "condition", *TABLE3_METRICS])

    rows = [
        {
            "task": task,
            "condition": condition,
            "preprocessing_loc": measurement.preprocessing_loc,
            "function_count": measurement.function_count,
            "transformation_steps": measurement.transformation_steps,
            "cyclomatic_complexity": measurement.cyclomatic_complexity,
        }
        for (task, condition), measurement in metrics.items()
    ]
    frame = pd.DataFrame(rows)
    order = {condition: index for index, condition in enumerate(CONDITIONS)}
    frame["_order"] = frame["condition"].map(order)
    frame = frame.sort_values(["task", "_order"]).drop(columns="_order")
    return frame.reset_index(drop=True)


# -- internals -------------------------------------------------------------


def _docstring_lines(source: str) -> set[int]:
    """Line numbers occupied by the leading docstring, if there is one."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    body = tree.body
    if len(body) == 1 and isinstance(
        body[0], ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ):
        body = body[0].body
    if not body:
        return set()
    first = body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)):
        return set()
    if not isinstance(first.value.value, str):
        return set()
    return set(range(first.lineno, (first.end_lineno or first.lineno) + 1))


def _find_class(tree: ast.Module, name: str, module: ModuleType) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise CodeMetricsError(f"{name} is not defined at module level in {module.__name__}")


def _find_method(
    class_node: ast.ClassDef, name: str, class_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in class_node.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name:
            return node
    raise CodeMetricsError(
        f"{class_name} does not define {name}(); a condition runner must implement it"
    )


def _referenced_names(node: ast.AST) -> Iterable[str]:
    """Names ``node`` refers to: bare names and ``self.x`` attributes.

    References, not calls. ``df["거래금액"].map(parse_price)`` never calls
    ``parse_price`` syntactically — it hands it to pandas — and that is the
    idiomatic way a transformation is applied here, so counting only call
    targets would miss most of them.

    Attributes of anything other than ``self`` are library access (``df.groupby``,
    ``pd.to_datetime``) and are skipped; they are not code the condition wrote.
    Names that resolve to neither a shared transformation nor a private helper
    are dropped by the caller, so locals and module aliases cost nothing here.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            yield child.id
        elif (
            isinstance(child, ast.Attribute)
            and isinstance(child.value, ast.Name)
            and child.value.id == "self"
        ):
            yield child.attr


def _public_callables(module: ModuleType) -> frozenset[str]:
    return frozenset(
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and callable(value)
        and getattr(value, "__module__", None) == module.__name__
    )


def _segment(source: str, node: ast.AST) -> str:
    segment = ast.get_source_segment(source, node, padded=False)
    if segment is None:
        raise CodeMetricsError("could not recover the source of a measured function")
    return segment


def _complexity(source: str) -> int:
    return sum(block.complexity for block in cc_visit(source))
