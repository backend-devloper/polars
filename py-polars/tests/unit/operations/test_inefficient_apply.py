from __future__ import annotations

from typing import Any, Callable

import numpy
import numpy as np
import pytest

import polars as pl
from polars.exceptions import PolarsInefficientApplyWarning
from polars.testing import assert_frame_equal
from polars.utils.udfs import BytecodeParser

MY_CONSTANT = 3


@pytest.mark.parametrize(
    "func",
    [
        np.sin,
        lambda x, y: x + y,
        lambda x: x[0] + 1,
        lambda x: x,
        lambda x: x > 0 and (x < 100 or (x % 2 == 0)),
    ],
)
def test_non_simple_function(func: Callable[[Any], Any]) -> None:
    assert not BytecodeParser(func, apply_target="expr").can_rewrite()


@pytest.mark.parametrize(
    ("col", "func"),
    [
        ("a", lambda x: x + 1 - (2 / 3)),
        ("a", lambda x: x // 1 % 2),
        ("a", lambda x: x & True),
        ("a", lambda x: x | False),
        ("a", lambda x: x != 3),
        ("a", lambda x: x > 1),
        ("a", lambda x: not (x > 1) or x == 2),
        ("a", lambda x: x is None),
        ("a", lambda x: x is not None),
        ("a", lambda x: ((x * -x) ** x) * 1.0),
        ("a", lambda x: 1.0 * (x * (x**x))),
        ("a", lambda x: (x / x) + ((x * x) - x)),
        ("a", lambda x: (10 - x) / (((x * 4) - x) // (2 + (x * (x - 1))))),
        ("a", lambda x: x in (2, 3, 4)),
        ("a", lambda x: x not in (2, 3, 4)),
        ("a", lambda x: x in (1, 2, 3, 4, 3) and x % 2 == 0 and x > 0),
        ("a", lambda x: MY_CONSTANT + x),
        ("a", lambda x: 0 + numpy.cbrt(x)),
        ("a", lambda x: np.sin(x) + 1),
        ("b", lambda x: x.title()),
        ("b", lambda x: x.lower() + x.upper()),
    ],
)
def test_expr_apply_produces_warning(col: str, func: Callable[[Any], Any]) -> None:
    with pytest.warns(
        PolarsInefficientApplyWarning, match="In this case, you can replace"
    ):
        parser = BytecodeParser(func, apply_target="expr")
        suggested_expression = parser.to_expression(col=col)
        assert suggested_expression is not None

        df = pl.DataFrame(
            {
                "a": [1, 2, 3],
                "b": ["AB", "cd", "eF"],
            }
        )
        result = df.select(
            x=col,
            y=eval(suggested_expression),
        )
        expected = df.select(
            x=pl.col(col),
            y=pl.col(col).apply(func),
        )
        assert_frame_equal(result, expected)


def test_expr_apply_parsing_misc() -> None:
    # note: can also identify inefficient functions and methods as well as lambdas
    class Test:
        def x10(self, x: pl.Expr) -> pl.Expr:
            return x * 10

    parser = BytecodeParser(Test().x10, apply_target="expr")
    suggested_expression = parser.to_expression(col="colx")
    assert suggested_expression == 'pl.col("colx") * 10'

    # note: all constants - should not create a warning/suggestion
    suggested_expression = BytecodeParser(
        lambda x: MY_CONSTANT + 42, apply_target="expr"
    ).to_expression(col="colx")
    assert suggested_expression is None
