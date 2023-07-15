from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Callable, Iterable

from polars import functions as F
from polars.utils._parse_expr_input import parse_as_list_of_expressions
from polars.utils._wrap import wrap_ldf
from polars.utils.various import find_stacklevel

if TYPE_CHECKING:
    from polars import DataFrame, LazyFrame
    from polars.polars import PyLazyGroupBy
    from polars.type_aliases import IntoExpr, RollingInterpolationMethod, SchemaDict


class LazyGroupBy:
    """
    Utility class for performing a groupby operation over a lazy dataframe.

    Generated by calling ``df.lazy().groupby(...)``.
    """

    def __init__(self, lgb: PyLazyGroupBy) -> None:
        self.lgb = lgb

    def agg(
        self,
        *aggs: IntoExpr | Iterable[IntoExpr],
        **named_aggs: IntoExpr,
    ) -> LazyFrame:
        """
        Compute aggregations for each group of a groupby operation.

        Parameters
        ----------
        *aggs
            Aggregations to compute for each group of the groupby operation,
            specified as positional arguments.
            Accepts expression input. Strings are parsed as column names.
        **named_aggs
            Additional aggregations, specified as keyword arguments.
            The resulting columns will be renamed to the keyword used.

        Examples
        --------
        Compute the aggregation of the columns for each group.

        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": ["a", "b", "a", "b", "c"],
        ...         "b": [1, 2, 1, 3, 3],
        ...         "c": [5, 4, 3, 2, 1],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("a").agg(
        ...     [pl.col("b"), pl.col("c")]
        ... ).collect()  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬───────────┬───────────┐
        │ a   ┆ b         ┆ c         │
        │ --- ┆ ---       ┆ ---       │
        │ str ┆ list[i64] ┆ list[i64] │
        ╞═════╪═══════════╪═══════════╡
        │ a   ┆ [1, 1]    ┆ [5, 3]    │
        ├╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌╌┤
        │ b   ┆ [2, 3]    ┆ [4, 2]    │
        ├╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌╌┤
        │ c   ┆ [3]       ┆ [1]       │
        └─────┴───────────┴───────────┘

        Compute the sum of a column for each group.

        >>> ldf.groupby("a").agg(pl.col("b").sum()).collect()  # doctest: +IGNORE_RESULT
        shape: (3, 2)
        ┌─────┬─────┐
        │ a   ┆ b   │
        │ --- ┆ --- │
        │ str ┆ i64 │
        ╞═════╪═════╡
        │ a   ┆ 2   │
        │ b   ┆ 5   │
        │ c   ┆ 3   │
        └─────┴─────┘

        Compute multiple aggregates at once by passing a list of expressions.

        >>> ldf.groupby("a").agg(
        ...     [pl.sum("b"), pl.mean("c")]
        ... ).collect()  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬─────┬─────┐
        │ a   ┆ b   ┆ c   │
        │ --- ┆ --- ┆ --- │
        │ str ┆ i64 ┆ f64 │
        ╞═════╪═════╪═════╡
        │ c   ┆ 3   ┆ 1.0 │
        │ a   ┆ 2   ┆ 4.0 │
        │ b   ┆ 5   ┆ 3.0 │
        └─────┴─────┴─────┘

        Or use positional arguments to compute multiple aggregations in the same way.

        >>> ldf.groupby("a").agg(
        ...     pl.sum("b").suffix("_sum"),
        ...     (pl.col("c") ** 2).mean().suffix("_mean_squared"),
        ... ).collect()  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬───────┬────────────────┐
        │ a   ┆ b_sum ┆ c_mean_squared │
        │ --- ┆ ---   ┆ ---            │
        │ str ┆ i64   ┆ f64            │
        ╞═════╪═══════╪════════════════╡
        │ a   ┆ 2     ┆ 17.0           │
        │ c   ┆ 3     ┆ 1.0            │
        │ b   ┆ 5     ┆ 10.0           │
        └─────┴───────┴────────────────┘

        Use keyword arguments to easily name your expression inputs.

        >>> ldf.groupby("a").agg(
        ...     b_sum=pl.sum("b"),
        ...     c_mean_squared=(pl.col("c") ** 2).mean(),
        ... ).collect()  # doctest: +IGNORE_RESULT
        shape: (3, 3)
        ┌─────┬───────┬────────────────┐
        │ a   ┆ b_sum ┆ c_mean_squared │
        │ --- ┆ ---   ┆ ---            │
        │ str ┆ i64   ┆ f64            │
        ╞═════╪═══════╪════════════════╡
        │ a   ┆ 2     ┆ 17.0           │
        │ c   ┆ 3     ┆ 1.0            │
        │ b   ┆ 5     ┆ 10.0           │
        └─────┴───────┴────────────────┘

        """
        if aggs and isinstance(aggs[0], dict):
            raise ValueError(
                "specifying aggregations as a dictionary is not supported."
                " Try unpacking the dictionary to take advantage of the keyword syntax"
                " of the `agg` method."
            )

        if "aggs" in named_aggs:
            warnings.warn(
                "passing expressions to `agg` using the keyword argument `aggs` is"
                " deprecated. Use positional syntax instead.",
                DeprecationWarning,
                stacklevel=find_stacklevel(),
            )
            first_input = named_aggs.pop("aggs")
            pyexprs = parse_as_list_of_expressions(first_input, *aggs, **named_aggs)
        else:
            pyexprs = parse_as_list_of_expressions(*aggs, **named_aggs)

        return wrap_ldf(self.lgb.agg(pyexprs))

    def apply(
        self,
        function: Callable[[DataFrame], DataFrame],
        schema: SchemaDict | None,
    ) -> LazyFrame:
        """
        Apply a custom/user-defined function (UDF) over the groups as a new DataFrame.

        .. warning::
            This method is much slower than the native expressions API.
            Only use it if you cannot implement your logic otherwise.

        Using this is considered an anti-pattern. This will be very slow because:

        - it forces the engine to materialize the whole `DataFrames` for the groups.
        - it is not parallelized
        - it blocks optimizations as the passed python function is opaque to the
          optimizer

        The idiomatic way to apply custom functions over multiple columns is using:

        `pl.struct([my_columns]).apply(lambda struct_series: ..)`

        Parameters
        ----------
        function
            Function to apply over each group of the `LazyFrame`.
        schema
            Schema of the output function. This has to be known statically. If the
            given schema is incorrect, this is a bug in the caller's query and may
            lead to errors. If set to None, polars assumes the schema is unchanged.


        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "id": [0, 1, 2, 3, 4],
        ...         "color": ["red", "green", "green", "red", "red"],
        ...         "shape": ["square", "triangle", "square", "triangle", "square"],
        ...     }
        ... )
        >>> df
        shape: (5, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 0   ┆ red   ┆ square   │
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        │ 4   ┆ red   ┆ square   │
        └─────┴───────┴──────────┘

        For each color group sample two rows:

        >>> (
        ...     df.lazy()
        ...     .groupby("color")
        ...     .apply(lambda group_df: group_df.sample(2), schema=None)
        ...     .collect()
        ... )  # doctest: +IGNORE_RESULT
        shape: (4, 3)
        ┌─────┬───────┬──────────┐
        │ id  ┆ color ┆ shape    │
        │ --- ┆ ---   ┆ ---      │
        │ i64 ┆ str   ┆ str      │
        ╞═════╪═══════╪══════════╡
        │ 1   ┆ green ┆ triangle │
        │ 2   ┆ green ┆ square   │
        │ 4   ┆ red   ┆ square   │
        │ 3   ┆ red   ┆ triangle │
        └─────┴───────┴──────────┘

        It is better to implement this with an expression:

        >>> (
        ...     df.lazy()
        ...     .filter(pl.int_range(0, pl.count()).shuffle().over("color") < 2)
        ...     .collect()
        ... )  # doctest: +IGNORE_RESULT

        """
        return wrap_ldf(self.lgb.apply(function, schema))

    def head(self, n: int = 5) -> LazyFrame:
        """
        Get the first `n` rows of each group.

        Parameters
        ----------
        n
            Number of rows to return.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "letters": ["c", "c", "a", "c", "a", "b"],
        ...         "nrs": [1, 2, 3, 4, 5, 6],
        ...     }
        ... )
        >>> df
        shape: (6, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ c       ┆ 1   │
        │ c       ┆ 2   │
        │ a       ┆ 3   │
        │ c       ┆ 4   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        └─────────┴─────┘
        >>> df.groupby("letters").head(2).sort("letters")
        shape: (5, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ a       ┆ 3   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        │ c       ┆ 1   │
        │ c       ┆ 2   │
        └─────────┴─────┘

        """
        return wrap_ldf(self.lgb.head(n))

    def tail(self, n: int = 5) -> LazyFrame:
        """
        Get the last `n` rows of each group.

        Parameters
        ----------
        n
            Number of rows to return.

        Examples
        --------
        >>> df = pl.DataFrame(
        ...     {
        ...         "letters": ["c", "c", "a", "c", "a", "b"],
        ...         "nrs": [1, 2, 3, 4, 5, 6],
        ...     }
        ... )
        >>> df
        shape: (6, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ c       ┆ 1   │
        │ c       ┆ 2   │
        │ a       ┆ 3   │
        │ c       ┆ 4   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        └─────────┴─────┘
        >>> df.groupby("letters").tail(2).sort("letters")
         shape: (5, 2)
        ┌─────────┬─────┐
        │ letters ┆ nrs │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ a       ┆ 3   │
        │ a       ┆ 5   │
        │ b       ┆ 6   │
        │ c       ┆ 2   │
        │ c       ┆ 4   │
        └─────────┴─────┘

        """
        return wrap_ldf(self.lgb.tail(n))

    def all(self) -> LazyFrame:
        """
        Aggregate the groups into Series.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": ["one", "two", "one", "two"],
        ...         "b": [1, 2, 3, 4],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("a", maintain_order=True).all().collect()
        shape: (2, 2)
        ┌─────┬───────────┐
        │ a   ┆ b         │
        │ --- ┆ ---       │
        │ str ┆ list[i64] │
        ╞═════╪═══════════╡
        │ one ┆ [1, 3]    │
        │ two ┆ [2, 4]    │
        └─────┴───────────┘

        """
        return self.agg(F.all())

    def count(self) -> LazyFrame:
        """
        Count the number of values in each group.

        .. warning::
            `null` is deemed a value in this context.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).count().collect()
        shape: (3, 2)
        ┌────────┬───────┐
        │ d      ┆ count │
        │ ---    ┆ ---   │
        │ str    ┆ u32   │
        ╞════════╪═══════╡
        │ Apple  ┆ 3     │
        │ Orange ┆ 1     │
        │ Banana ┆ 2     │
        └────────┴───────┘

        """
        return self.agg(F.count())

    def first(self) -> LazyFrame:
        """
        Aggregate the first values in the group.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).first().collect()
        shape: (3, 4)
        ┌────────┬─────┬──────┬───────┐
        │ d      ┆ a   ┆ b    ┆ c     │
        │ ---    ┆ --- ┆ ---  ┆ ---   │
        │ str    ┆ i64 ┆ f64  ┆ bool  │
        ╞════════╪═════╪══════╪═══════╡
        │ Apple  ┆ 1   ┆ 0.5  ┆ true  │
        │ Orange ┆ 2   ┆ 0.5  ┆ true  │
        │ Banana ┆ 4   ┆ 13.0 ┆ false │
        └────────┴─────┴──────┴───────┘

        """
        return self.agg(F.all().first())

    def last(self) -> LazyFrame:
        """
        Aggregate the last values in the group.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).last().collect()
        shape: (3, 4)
        ┌────────┬─────┬──────┬───────┐
        │ d      ┆ a   ┆ b    ┆ c     │
        │ ---    ┆ --- ┆ ---  ┆ ---   │
        │ str    ┆ i64 ┆ f64  ┆ bool  │
        ╞════════╪═════╪══════╪═══════╡
        │ Apple  ┆ 3   ┆ 10.0 ┆ false │
        │ Orange ┆ 2   ┆ 0.5  ┆ true  │
        │ Banana ┆ 5   ┆ 14.0 ┆ true  │
        └────────┴─────┴──────┴───────┘

        """
        return self.agg(F.all().last())

    def max(self) -> LazyFrame:
        """
        Reduce the groups to the maximal value.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).max().collect()
        shape: (3, 4)
        ┌────────┬─────┬──────┬──────┐
        │ d      ┆ a   ┆ b    ┆ c    │
        │ ---    ┆ --- ┆ ---  ┆ ---  │
        │ str    ┆ i64 ┆ f64  ┆ bool │
        ╞════════╪═════╪══════╪══════╡
        │ Apple  ┆ 3   ┆ 10.0 ┆ true │
        │ Orange ┆ 2   ┆ 0.5  ┆ true │
        │ Banana ┆ 5   ┆ 14.0 ┆ true │
        └────────┴─────┴──────┴──────┘

        """
        return self.agg(F.all().max())

    def mean(self) -> LazyFrame:
        """
        Reduce the groups to the mean values.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).mean().collect()
        shape: (3, 4)
        ┌────────┬─────┬──────────┬──────────┐
        │ d      ┆ a   ┆ b        ┆ c        │
        │ ---    ┆ --- ┆ ---      ┆ ---      │
        │ str    ┆ f64 ┆ f64      ┆ f64      │
        ╞════════╪═════╪══════════╪══════════╡
        │ Apple  ┆ 2.0 ┆ 4.833333 ┆ 0.666667 │
        │ Orange ┆ 2.0 ┆ 0.5      ┆ 1.0      │
        │ Banana ┆ 4.5 ┆ 13.5     ┆ 0.5      │
        └────────┴─────┴──────────┴──────────┘

        """
        return self.agg(F.all().mean())

    def median(self) -> LazyFrame:
        """
        Return the median per group.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "d": ["Apple", "Banana", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).median().collect()
        shape: (2, 3)
        ┌────────┬─────┬──────┐
        │ d      ┆ a   ┆ b    │
        │ ---    ┆ --- ┆ ---  │
        │ str    ┆ f64 ┆ f64  │
        ╞════════╪═════╪══════╡
        │ Apple  ┆ 2.0 ┆ 4.0  │
        │ Banana ┆ 4.0 ┆ 13.0 │
        └────────┴─────┴──────┘

        """
        return self.agg(F.all().median())

    def min(self) -> LazyFrame:
        """
        Reduce the groups to the minimal value.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).min().collect()
        shape: (3, 4)
        ┌────────┬─────┬──────┬───────┐
        │ d      ┆ a   ┆ b    ┆ c     │
        │ ---    ┆ --- ┆ ---  ┆ ---   │
        │ str    ┆ i64 ┆ f64  ┆ bool  │
        ╞════════╪═════╪══════╪═══════╡
        │ Apple  ┆ 1   ┆ 0.5  ┆ false │
        │ Orange ┆ 2   ┆ 0.5  ┆ true  │
        │ Banana ┆ 4   ┆ 13.0 ┆ false │
        └────────┴─────┴──────┴───────┘

        """
        return self.agg(F.all().min())

    def n_unique(self) -> LazyFrame:
        """
        Count the unique values per group.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 1, 3, 4, 5],
        ...         "b": [0.5, 0.5, 0.5, 10, 13, 14],
        ...         "d": ["Apple", "Banana", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).n_unique().collect()
        shape: (2, 3)
        ┌────────┬─────┬─────┐
        │ d      ┆ a   ┆ b   │
        │ ---    ┆ --- ┆ --- │
        │ str    ┆ u32 ┆ u32 │
        ╞════════╪═════╪═════╡
        │ Apple  ┆ 2   ┆ 2   │
        │ Banana ┆ 3   ┆ 3   │
        └────────┴─────┴─────┘

        """
        return self.agg(F.all().n_unique())

    def quantile(
        self, quantile: float, interpolation: RollingInterpolationMethod = "nearest"
    ) -> LazyFrame:
        """
        Compute the quantile per group.

        Parameters
        ----------
        quantile
            Quantile between 0.0 and 1.0.
        interpolation : {'nearest', 'higher', 'lower', 'midpoint', 'linear'}
            Interpolation method.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).quantile(1).collect()
        shape: (3, 3)
        ┌────────┬─────┬──────┐
        │ d      ┆ a   ┆ b    │
        │ ---    ┆ --- ┆ ---  │
        │ str    ┆ f64 ┆ f64  │
        ╞════════╪═════╪══════╡
        │ Apple  ┆ 3.0 ┆ 10.0 │
        │ Orange ┆ 2.0 ┆ 0.5  │
        │ Banana ┆ 5.0 ┆ 14.0 │
        └────────┴─────┴──────┘

        """
        return self.agg(F.all().quantile(quantile, interpolation=interpolation))

    def sum(self) -> LazyFrame:
        """
        Reduce the groups to the sum.

        Examples
        --------
        >>> ldf = pl.DataFrame(
        ...     {
        ...         "a": [1, 2, 2, 3, 4, 5],
        ...         "b": [0.5, 0.5, 4, 10, 13, 14],
        ...         "c": [True, True, True, False, False, True],
        ...         "d": ["Apple", "Orange", "Apple", "Apple", "Banana", "Banana"],
        ...     }
        ... ).lazy()
        >>> ldf.groupby("d", maintain_order=True).sum().collect()
        shape: (3, 4)
        ┌────────┬─────┬──────┬─────┐
        │ d      ┆ a   ┆ b    ┆ c   │
        │ ---    ┆ --- ┆ ---  ┆ --- │
        │ str    ┆ i64 ┆ f64  ┆ u32 │
        ╞════════╪═════╪══════╪═════╡
        │ Apple  ┆ 6   ┆ 14.5 ┆ 2   │
        │ Orange ┆ 2   ┆ 0.5  ┆ 1   │
        │ Banana ┆ 9   ┆ 27.0 ┆ 1   │
        └────────┴─────┴──────┴─────┘

        """
        return self.agg(F.all().sum())
