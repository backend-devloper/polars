from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal as D
from typing import Any, NamedTuple

import polars as pl


def permutations_int_dec_none() -> list[tuple[D | int | None, ...]]:
    return list(
        itertools.permutations(
            [
                D("-0.01"),
                D("1.2345678"),
                D("500"),
                -1,
                None,
            ]
        )
    )


def test_series_from_pydecimal_and_ints() -> None:
    # TODO: check what happens if there are strings, floats arrow scalars in the list
    for data in permutations_int_dec_none():
        s = pl.Series("name", data)
        assert s.dtype == pl.Decimal(None, 7)  # inferred scale = 7, precision = None
        assert s.name == "name"
        assert s.null_count() == 1
        for i, d in enumerate(data):
            assert s[i] == d
        assert s.to_list() == [D(x) if x is not None else None for x in data]


def test_frame_from_pydecimal_and_ints(monkeypatch: Any) -> None:
    monkeypatch.setenv("POLARS_ACTIVATE_DECIMAL", "1")

    class X(NamedTuple):
        a: int | D | None

    @dataclass
    class Y:
        a: int | D | None

    for data in permutations_int_dec_none():
        row_data = [(d,) for d in data]
        for cls in (X, Y):
            for ctor in (pl.DataFrame, pl.from_records):
                df = ctor(data=list(map(cls, data)))  # type: ignore[operator]
                assert df.schema == {
                    "a": pl.Decimal(None, 7),
                }
                assert df.rows() == row_data


def test_to_from_pydecimal_and_format() -> None:
    dec_strs = [
        "0",
        "-1",
        "0.01",
        "-1.123801239123981293891283123",
        "12345678901.234567890123458390192857685",
        "-99999999999.999999999999999999999999999",
    ]
    formatted = (
        str(pl.Series(list(map(D, dec_strs))))
        .split("[", 1)[1]
        .split("\n", 1)[1]
        .strip()[1:-1]
        .split()
    )
    assert formatted == dec_strs


def test_init_decimal_dtype() -> None:
    s = pl.Series("a", [D("-0.01"), D("1.2345678"), D("500")], dtype=pl.Decimal)
    assert s.is_numeric()

    df = pl.DataFrame(
        {"a": [D("-0.01"), D("1.2345678"), D("500")]}, schema={"a": pl.Decimal}
    )
    assert df["a"].is_numeric()


def test_decimal_cast() -> None:
    df = pl.DataFrame(
        {
            "decimals": [
                D("2"),
                D("2"),
            ],
        }
    )
    assert df.with_columns(pl.col("decimals").cast(pl.Float32).alias("b2")).to_dict(
        False
    ) == {"decimals": [D("2"), D("2")], "b2": [2.0, 2.0]}


def test_decimal_scale_precision_roundtrip(monkeypatch: Any) -> None:
    monkeypatch.setenv("POLARS_ACTIVATE_DECIMAL", "1")
    assert pl.from_arrow(pl.Series("dec", [D("10.0")]).to_arrow()).item() == D("10.0")


def test_utf8_to_decimal() -> None:
    s = pl.Series(
        ["40.12", "3420.13", "120134.19", "3212.98", "12.90", "143.09", "143.9"]
    ).str.to_decimal()
    assert s.dtype == pl.Decimal(8, 2)

    assert s.to_list() == [
        D("40.12"),
        D("3420.13"),
        D("120134.19"),
        D("3212.98"),
        D("12.90"),
        D("143.09"),
        D("143.90"),
    ]


def test_read_csv_decimal(monkeypatch: Any) -> None:
    monkeypatch.setenv("POLARS_ACTIVATE_DECIMAL", "1")
    csv = """a,b
    123.12,a
    1.1,a
    0.01,a"""

    df = pl.read_csv(csv.encode(), dtypes={"a": pl.Decimal})
    assert df.dtypes == [pl.Decimal(None, 20), pl.Utf8]
    assert df["a"].to_list() == [
        D("123.12000000000000000000"),
        D("1.10000000000000000000"),
        D("0.01000000000000000000"),
    ]


def test_decimal_arithmetic() -> None:
    df = pl.DataFrame(
        {
            "a": [D("0.1"), D("10.1"), D("100.01")],
            "b": [D("20.1"), D("10.19"), D("39.21")],
        }
    )

    out = df.select(
        out1=pl.col("a") * pl.col("b"),
        out2=pl.col("a") + pl.col("b"),
        out3=pl.col("a") / pl.col("b"),
        out4=pl.col("a") - pl.col("b"),
    )
    assert out.dtypes == [
        pl.Decimal(precision=None, scale=2),
        pl.Decimal(precision=None, scale=2),
        pl.Decimal(precision=None, scale=2),
        pl.Decimal(precision=None, scale=2),
    ]

    assert out.to_dict(False) == {
        "out1": [D("2.01"), D("102.91"), D("3921.39")],
        "out2": [D("20.20"), D("20.29"), D("139.22")],
        "out3": [D("0.00"), D("0.99"), D("2.55")],
        "out4": [D("-20.00"), D("-0.09"), D("60.80")],
    }
