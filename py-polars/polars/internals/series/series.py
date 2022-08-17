from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Sequence, Union, overload

from polars import internals as pli
from polars.datatypes import (
    Boolean,
    DataType,
    Date,
    Datetime,
    Duration,
    Float32,
    Float64,
    Int8,
    Int16,
    Int32,
    Int64,
    List,
    Object,
    Time,
    UInt8,
    UInt16,
    UInt32,
    UInt64,
    Utf8,
    dtype_to_ctype,
    dtype_to_ffiname,
    get_idx_type,
    maybe_cast,
    numpy_char_code_to_dtype,
    py_type_to_dtype,
    supported_numpy_char_code,
)
from polars.internals.construction import (
    arrow_to_pyseries,
    numpy_to_pyseries,
    pandas_to_pyseries,
    sequence_to_pyseries,
    series_to_pyseries,
)
from polars.internals.series.categorical import CatNameSpace
from polars.internals.series.datetime import DateTimeNameSpace
from polars.internals.series.list import ListNameSpace
from polars.internals.series.string import StringNameSpace
from polars.internals.series.struct import StructNameSpace
from polars.internals.slice import PolarsSlice
from polars.utils import (
    _date_to_pl_date,
    _datetime_to_pl_timestamp,
    _ptr_to_numpy,
    is_bool_sequence,
    is_int_sequence,
    range_to_slice,
)

try:
    from polars.polars import PyDataFrame, PySeries

    _DOCUMENTING = False
except ImportError:
    _DOCUMENTING = True

try:
    import numpy as np

    _NUMPY_AVAILABLE = True
except ImportError:
    _NUMPY_AVAILABLE = False

try:
    import pyarrow as pa

    _PYARROW_AVAILABLE = True
except ImportError:
    _PYARROW_AVAILABLE = False

try:
    import pandas as pd

    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

if TYPE_CHECKING:
    from polars.internals.type_aliases import (
        ComparisonOperator,
        FillNullStrategy,
        InterpolationMethod,
        NullBehavior,
        RankMethod,
        TimeUnit,
    )


def get_ffi_func(
    name: str,
    dtype: type[DataType],
    obj: PySeries,
) -> Callable[..., Any] | None:
    """
    Dynamically obtain the proper ffi function/ method.

    Parameters
    ----------
    name
        function or method name where dtype is replaced by <>
        for example
            "call_foo_<>"
    dtype
        polars dtype.
    obj
        Object to find the method for.

    Returns
    -------
    ffi function, or None if not found

    """
    ffi_name = dtype_to_ffiname(dtype)
    fname = name.replace("<>", ffi_name)
    return getattr(obj, fname, None)


def wrap_s(s: PySeries) -> Series:
    return Series._from_pyseries(s)


ArrayLike = Union[
    Sequence[Any],
    "Series",
    "pa.Array",
    "pa.ChunkedArray",
    "np.ndarray",
    "pd.Series",
    "pd.DatetimeIndex",
]


class Series:
    """
    A Series represents a single column in a polars DataFrame.

    Parameters
    ----------
    name : str, default None
        Name of the series. Will be used as a column name when used in a DataFrame.
        When not specified, name is set to an empty string.
    values : ArrayLike, default None
        One-dimensional data in various forms. Supported are: Sequence, Series,
        pyarrow Array, and numpy ndarray.
    dtype : DataType, default None
        Polars dtype of the Series data. If not specified, the dtype is inferred.
    strict
        Throw error on numeric overflow
    nan_to_null
        In case a numpy arrow is used to create this Series, indicate how to deal with
        np.nan

    Examples
    --------
    Constructing a Series by specifying name and values positionally:

    >>> s = pl.Series("a", [1, 2, 3])
    >>> s
    shape: (3,)
    Series: 'a' [i64]
    [
            1
            2
            3
    ]

    Notice that the dtype is automatically inferred as a polars Int64:

    >>> s.dtype
    <class 'polars.datatypes.Int64'>

    Constructing a Series with a specific dtype:

    >>> s2 = pl.Series("a", [1, 2, 3], dtype=pl.Float32)
    >>> s2
    shape: (3,)
    Series: 'a' [f32]
    [
        1.0
        2.0
        3.0
    ]

    It is possible to construct a Series with values as the first positional argument.
    This syntax considered an anti-pattern, but it can be useful in certain
    scenarios. You must specify any other arguments through keywords.

    >>> s3 = pl.Series([1, 2, 3])
    >>> s3
    shape: (3,)
    Series: '' [i64]
    [
            1
            2
            3
    ]

    """

    def __init__(
        self,
        name: str | ArrayLike | None = None,
        values: ArrayLike | Sequence[Any] | None = None,
        dtype: type[DataType] | DataType | None = None,
        strict: bool = True,
        nan_to_null: bool = False,
    ):

        # Handle case where values are passed as the first argument
        if name is not None and not isinstance(name, str):
            if values is None:
                values = name
                name = None
            else:
                raise ValueError("Series name must be a string.")

        if name is None:
            name = ""

        if values is None:
            self._s = sequence_to_pyseries(name, [], dtype=dtype)
        elif isinstance(values, Series):
            self._s = series_to_pyseries(name, values)
        elif _PYARROW_AVAILABLE and isinstance(values, (pa.Array, pa.ChunkedArray)):
            self._s = arrow_to_pyseries(name, values)
        elif _NUMPY_AVAILABLE and isinstance(values, np.ndarray):
            self._s = numpy_to_pyseries(name, values, strict, nan_to_null)
            if dtype is not None:
                self._s = self.cast(dtype, strict=True)._s
        elif isinstance(values, Sequence):
            self._s = sequence_to_pyseries(name, values, dtype=dtype, strict=strict)
        elif _PANDAS_AVAILABLE and isinstance(values, (pd.Series, pd.DatetimeIndex)):
            self._s = pandas_to_pyseries(name, values)
        else:
            raise ValueError("Series constructor not called properly.")

    @classmethod
    def _from_pyseries(cls, pyseries: PySeries) -> Series:
        series = cls.__new__(cls)
        series._s = pyseries
        return series

    @classmethod
    def _repeat(
        cls, name: str, val: int | float | str | bool, n: int, dtype: type[DataType]
    ) -> Series:
        return cls._from_pyseries(PySeries.repeat(name, val, n, dtype))

    @classmethod
    def _from_arrow(cls, name: str, values: pa.Array, rechunk: bool = True) -> Series:
        """Construct a Series from an Arrow Array."""
        return cls._from_pyseries(arrow_to_pyseries(name, values, rechunk))

    @classmethod
    def _from_pandas(
        cls,
        name: str,
        values: pd.Series | pd.DatetimeIndex,
        nan_to_none: bool = True,
    ) -> Series:
        """Construct a Series from a pandas Series or DatetimeIndex."""
        return cls._from_pyseries(
            pandas_to_pyseries(name, values, nan_to_none=nan_to_none)
        )

    def inner(self) -> PySeries:
        return self._s

    def __getstate__(self) -> Any:
        return self._s.__getstate__()

    def __setstate__(self, state: Any) -> None:
        self._s = sequence_to_pyseries("", [], Float32)
        self._s.__setstate__(state)

    def __str__(self) -> str:
        return self._s.as_str()

    def __repr__(self) -> str:
        return self.__str__()

    def __and__(self, other: Series) -> Series:
        if not isinstance(other, Series):
            other = Series([other])
        return wrap_s(self._s.bitand(other._s))

    def __rand__(self, other: Series) -> Series:
        return self.__and__(other)

    def __or__(self, other: Series) -> Series:
        if not isinstance(other, Series):
            other = Series([other])
        return wrap_s(self._s.bitor(other._s))

    def __ror__(self, other: Series) -> Series:
        return self.__or__(other)

    def __xor__(self, other: Series) -> Series:
        if not isinstance(other, Series):
            other = Series([other])
        return wrap_s(self._s.bitxor(other._s))

    def __rxor__(self, other: Series) -> Series:
        return self.__xor__(other)

    def _comp(self, other: Any, op: ComparisonOperator) -> Series:
        if isinstance(other, datetime) and self.dtype == Datetime:
            ts = _datetime_to_pl_timestamp(other, self.time_unit)
            f = get_ffi_func(op + "_<>", Int64, self._s)
            assert f is not None
            return wrap_s(f(ts))
        if isinstance(other, date) and self.dtype == Date:
            d = _date_to_pl_date(other)
            f = get_ffi_func(op + "_<>", Int32, self._s)
            assert f is not None
            return wrap_s(f(d))

        if isinstance(other, Sequence) and not isinstance(other, str):
            other = Series("", other)
        if isinstance(other, Series):
            return wrap_s(getattr(self._s, op)(other._s))
        other = maybe_cast(other, self.dtype, self.time_unit)
        f = get_ffi_func(op + "_<>", self.dtype, self._s)
        if f is None:
            return NotImplemented
        return wrap_s(f(other))

    def __eq__(self, other: Any) -> Series:  # type: ignore[override]
        return self._comp(other, "eq")

    def __ne__(self, other: Any) -> Series:  # type: ignore[override]
        return self._comp(other, "neq")

    def __gt__(self, other: Any) -> Series:
        return self._comp(other, "gt")

    def __lt__(self, other: Any) -> Series:
        return self._comp(other, "lt")

    def __ge__(self, other: Any) -> Series:
        return self._comp(other, "gt_eq")

    def __le__(self, other: Any) -> Series:
        return self._comp(other, "lt_eq")

    def _arithmetic(self, other: Any, op_s: str, op_ffi: str) -> Series:
        if isinstance(other, Series):
            return wrap_s(getattr(self._s, op_s)(other._s))
        if isinstance(other, float) and not self.is_float():
            _s = sequence_to_pyseries("", [other])
            if "rhs" in op_ffi:
                return wrap_s(getattr(_s, op_s)(self._s))
            else:
                return wrap_s(getattr(self._s, op_s)(_s))
        else:
            other = maybe_cast(other, self.dtype, self.time_unit)
            f = get_ffi_func(op_ffi, self.dtype, self._s)
        if f is None:
            raise ValueError(
                f"cannot do arithmetic with series of dtype: {self.dtype} and argument"
                f" of type: {type(other)}"
            )
        return wrap_s(f(other))

    def __add__(self, other: Any) -> Series:
        if isinstance(other, str):
            other = Series("", [other])
        return self._arithmetic(other, "add", "add_<>")

    def __sub__(self, other: Any) -> Series:
        return self._arithmetic(other, "sub", "sub_<>")

    def __truediv__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError("first cast to integer before dividing datelike dtypes")

        # this branch is exactly the floordiv function without rounding the floats
        if self.is_float():
            return self._arithmetic(other, "div", "div_<>")

        return self.cast(Float64) / other

    def __floordiv__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError("first cast to integer before dividing datelike dtypes")
        result = self._arithmetic(other, "div", "div_<>")
        # todo! in place, saves allocation
        if self.is_float() or isinstance(other, float):
            result = result.floor()
        return result

    def __mul__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError("first cast to integer before multiplying datelike dtypes")
        return self._arithmetic(other, "mul", "mul_<>")

    def __mod__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError(
                "first cast to integer before applying modulo on datelike dtypes"
            )
        return self._arithmetic(other, "rem", "rem_<>")

    def __rmod__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError(
                "first cast to integer before applying modulo on datelike dtypes"
            )
        return self._arithmetic(other, "rem", "rem_<>_rhs")

    def __radd__(self, other: Any) -> Series:
        return self._arithmetic(other, "add", "add_<>_rhs")

    def __rsub__(self, other: Any) -> Series:
        return self._arithmetic(other, "sub", "sub_<>_rhs")

    def __invert__(self) -> Series:
        if self.dtype == Boolean:
            return wrap_s(self._s._not())
        return NotImplemented

    def __rtruediv__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError("first cast to integer before dividing datelike dtypes")
        if self.is_float():
            self.__rfloordiv__(other)

        if isinstance(other, int):
            other = float(other)

        return self.cast(Float64).__rfloordiv__(other)

    def __rfloordiv__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError("first cast to integer before dividing datelike dtypes")
        return self._arithmetic(other, "div", "div_<>_rhs")

    def __rmul__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError("first cast to integer before multiplying datelike dtypes")
        return self._arithmetic(other, "mul", "mul_<>")

    def __pow__(self, power: int | float | Series) -> Series:
        if self.is_datelike():
            raise ValueError(
                "first cast to integer before raising datelike dtypes to a power"
            )
        return self.to_frame().select(pli.col(self.name).pow(power)).to_series()

    def __rpow__(self, other: Any) -> Series:
        if self.is_datelike():
            raise ValueError(
                "first cast to integer before raising datelike dtypes to a power"
            )
        return self.to_frame().select(other ** pli.col(self.name)).to_series()

    def __neg__(self) -> Series:
        return 0 - self

    def _pos_idxs(self, idxs: np.ndarray[Any, Any] | Series) -> Series:
        # pl.UInt32 (polars) or pl.UInt64 (polars_u64_idx).
        idx_type = get_idx_type()

        if isinstance(idxs, Series):
            if idxs.dtype == idx_type:
                return idxs
            if idxs.dtype in {
                UInt8,
                UInt16,
                UInt64 if idx_type == UInt32 else UInt32,
                Int8,
                Int16,
                Int32,
                Int64,
            }:
                if idx_type == UInt32:
                    if idxs.dtype in {Int64, UInt64}:
                        if idxs.max() >= 2**32:  # type: ignore[operator]
                            raise ValueError(
                                "Index positions should be smaller than 2^32."
                            )
                    if idxs.dtype == Int64:
                        if idxs.min() < -(2**32):  # type: ignore[operator]
                            raise ValueError(
                                "Index positions should be bigger than -2^32 + 1."
                            )
                if idxs.dtype in {Int8, Int16, Int32, Int64}:
                    if idxs.min() < 0:  # type: ignore[operator]
                        if idx_type == UInt32:
                            if idxs.dtype in {Int8, Int16}:
                                idxs = idxs.cast(Int32)
                        else:
                            if idxs.dtype in {Int8, Int16, Int32}:
                                idxs = idxs.cast(Int64)

                        idxs = pli.select(
                            pli.when(pli.lit(idxs) < 0)
                            .then(self.len() + pli.lit(idxs))
                            .otherwise(pli.lit(idxs))
                        ).to_series()

                return idxs.cast(idx_type)

        if _NUMPY_AVAILABLE and isinstance(idxs, np.ndarray):
            if idxs.ndim != 1:
                raise ValueError("Only 1D numpy array is supported as index.")
            if idxs.dtype.kind in ("i", "u"):
                # Numpy array with signed or unsigned integers.

                if idx_type == UInt32:
                    if idxs.dtype in {np.int64, np.uint64} and idxs.max() >= 2**32:
                        raise ValueError("Index positions should be smaller than 2^32.")
                    if idxs.dtype == np.int64 and idxs.min() < -(2**32):
                        raise ValueError(
                            "Index positions should be bigger than -2^32 + 1."
                        )
                if idxs.dtype.kind == "i" and idxs.min() < 0:
                    if idx_type == UInt32:
                        if idxs.dtype in (np.int8, np.int16):
                            idxs = idxs.astype(np.int32)
                    else:
                        if idxs.dtype in (np.int8, np.int16, np.int32):
                            idxs = idxs.astype(np.int64)

                    # Update negative indexes to absolute indexes.
                    idxs = np.where(idxs < 0, self.len() + idxs, idxs)

                return Series("", idxs, dtype=idx_type)

        raise NotImplementedError("Unsupported idxs datatype.")

    def __getitem__(
        self,
        item: int
        | Series
        | range
        | slice
        | np.ndarray[Any, Any]
        | list[int]
        | list[bool],
    ) -> Any:
        if isinstance(item, int):
            if item < 0:
                item = self.len() + item
            if self.dtype in (List, Object):
                f = get_ffi_func("get_<>", self.dtype, self._s)
                if f is None:
                    return NotImplemented
                out = f(item)
                if self.dtype == List:
                    if out is None:
                        return None
                    return wrap_s(out)
                return out

            return self._s.get_idx(item)

        if _NUMPY_AVAILABLE and isinstance(item, np.ndarray):
            if item.ndim != 1:
                raise ValueError("Only a 1D-Numpy array is supported as index.")
            if item.dtype.kind in ("i", "u"):
                # Numpy array with signed or unsigned integers.
                return wrap_s(self._s.take_with_series(self._pos_idxs(item).inner()))
            if item.dtype == bool:
                return wrap_s(self._s.filter(pli.Series("", item).inner()))

        if is_bool_sequence(item) or is_int_sequence(item):
            item = Series("", item)  # fall through to next if isinstance

        if isinstance(item, Series):
            if item.dtype == Boolean:
                return wrap_s(self._s.filter(item._s))
            if item.dtype == UInt32:
                return wrap_s(self._s.take_with_series(item.inner()))
            if item.dtype in {UInt8, UInt16, UInt64, Int8, Int16, Int32, Int64}:
                return wrap_s(self._s.take_with_series(self._pos_idxs(item).inner()))

        if isinstance(item, range):
            return self[range_to_slice(item)]

        # slice
        if isinstance(item, slice):
            return PolarsSlice(self).apply(item)

        raise ValueError(
            f"Cannot __getitem__ on Series of dtype: '{self.dtype}' "
            f"with argument: '{item}' of type: '{type(item)}'."
        )

    def __setitem__(
        self,
        key: int | Series | np.ndarray[Any, Any] | Sequence[object] | tuple[object],
        value: Any,
    ) -> None:
        if isinstance(value, Sequence) and not isinstance(value, str):
            if self.is_numeric() or self.is_datelike():
                self.set_at_idx(key, value)  # type: ignore[arg-type]
                return None
            raise ValueError(
                f"cannot set Series of dtype: {self.dtype} with list/tuple as value;"
                " use a scalar value"
            )
        if isinstance(key, Series):
            if key.dtype == Boolean:
                self._s = self.set(key, value)._s
            elif key.dtype == UInt64:
                self._s = self.set_at_idx(key.cast(UInt32), value)._s
            elif key.dtype == UInt32:
                self._s = self.set_at_idx(key, value)._s
        # TODO: implement for these types without casting to series
        elif _NUMPY_AVAILABLE and isinstance(key, np.ndarray) and key.dtype == np.bool_:
            # boolean numpy mask
            self._s = self.set_at_idx(np.argwhere(key)[:, 0], value)._s
        elif _NUMPY_AVAILABLE and isinstance(key, np.ndarray):
            s = wrap_s(PySeries.new_u32("", np.array(key, np.uint32), True))
            self.__setitem__(s, value)
        elif isinstance(key, (list, tuple)):
            s = wrap_s(sequence_to_pyseries("", key, dtype=UInt32))
            self.__setitem__(s, value)
        elif isinstance(key, int) and not isinstance(key, bool):
            self.__setitem__([key], value)
        else:
            raise ValueError(f'cannot use "{key}" for indexing')

    @property
    def flags(self) -> dict[str, bool]:
        """
        Get flags that are set on the Series

        Returns
        -------
        Dictionary containing the flag name and the value

        """
        return {
            "SORTED_ASC": self._s.is_sorted_flag(),
            "SORTED_DESC": self._s.is_sorted_reverse_flag(),
        }

    def estimated_size(self) -> int:
        """
        Return an estimation of the total (heap) allocated size of the `Series` in
        bytes.

        This estimation is the sum of the size of its buffers, validity, including
        nested arrays. Multiple arrays may share buffers and bitmaps. Therefore, the
        size of 2 arrays is not the sum of the sizes computed from this function. In
        particular, [`StructArray`]'s size is an upper bound.

        When an array is sliced, its allocated size remains constant because the buffer
        unchanged. However, this function will yield a smaller number. This is because
        this function returns the visible size of the buffer, not its total capacity.

        FFI buffers are included in this estimation.

        """
        return self._s.estimated_size()

    def sqrt(self) -> Series:
        """
        Compute the square root of the elements

        Syntactic sugar for

        >>> pl.Series([1, 2]) ** 0.5
        shape: (2,)
        Series: '' [f64]
        [
            1.0
            1.414214
        ]

        """
        return self**0.5

    def any(self) -> bool:
        """
        Check if any boolean value in the column is `True`

        Returns
        -------
        Boolean literal

        """
        return self.to_frame().select(pli.col(self.name).any()).to_series()[0]

    def all(self) -> bool:
        """
        Check if all boolean values in the column are `True`

        Returns
        -------
        Boolean literal

        """
        return self.to_frame().select(pli.col(self.name).all()).to_series()[0]

    def log(self, base: float = math.e) -> Series:
        """Compute the logarithm to a given base."""
        return self.to_frame().select(pli.col(self.name).log(base)).to_series()

    def log10(self) -> Series:
        """Compute the base 10 logarithm of the input array, element-wise."""
        return self.log(10.0)

    def exp(self) -> Series:
        """Compute the exponential, element-wise."""
        return self.to_frame().select(pli.col(self.name).exp()).to_series()

    def drop_nulls(self) -> Series:
        """Create a new Series that copies data from this Series without null values."""
        return wrap_s(self._s.drop_nulls())

    def drop_nans(self) -> Series:
        """Drop NaN values."""
        return self.filter(self.is_not_nan())

    def to_frame(self) -> pli.DataFrame:
        """
        Cast this Series to a DataFrame.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> df = s.to_frame()
        >>> df
        shape: (3, 1)
        ┌─────┐
        │ a   │
        │ --- │
        │ i64 │
        ╞═════╡
        │ 1   │
        ├╌╌╌╌╌┤
        │ 2   │
        ├╌╌╌╌╌┤
        │ 3   │
        └─────┘

        >>> type(df)
        <class 'polars.internals.dataframe.frame.DataFrame'>

        """
        return pli.wrap_df(PyDataFrame([self._s]))

    @property
    def dtype(self) -> type[DataType]:
        """
        Get the data type of this Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.dtype
        <class 'polars.datatypes.Int64'>

        """
        return self._s.dtype()

    @property
    def inner_dtype(self) -> type[DataType] | None:
        """
        Get the inner dtype in of a List typed Series

        Returns
        -------
        DataType

        """
        return self._s.inner_dtype()

    def describe(self) -> pli.DataFrame:
        """
        Quick summary statistics of a series. Series with mixed datatypes will return
        summary statistics for the datatype of the first value.

        Returns
        -------
        Dictionary with summary statistics of a Series.

        Examples
        --------
        >>> series_num = pl.Series([1, 2, 3, 4, 5])
        >>> series_num.describe()
        shape: (6, 2)
        ┌────────────┬──────────┐
        │ statistic  ┆ value    │
        │ ---        ┆ ---      │
        │ str        ┆ f64      │
        ╞════════════╪══════════╡
        │ min        ┆ 1.0      │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌┤
        │ max        ┆ 5.0      │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌┤
        │ null_count ┆ 0.0      │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌┤
        │ mean       ┆ 3.0      │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌┤
        │ std        ┆ 1.581139 │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌╌╌╌┤
        │ count      ┆ 5.0      │
        └────────────┴──────────┘

        >>> series_str = pl.Series(["a", "a", None, "b", "c"])
        >>> series_str.describe()
        shape: (3, 2)
        ┌────────────┬───────┐
        │ statistic  ┆ value │
        │ ---        ┆ ---   │
        │ str        ┆ i64   │
        ╞════════════╪═══════╡
        │ unique     ┆ 4     │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌┤
        │ null_count ┆ 1     │
        ├╌╌╌╌╌╌╌╌╌╌╌╌┼╌╌╌╌╌╌╌┤
        │ count      ┆ 5     │
        └────────────┴───────┘

        """
        stats: dict[str, float | None | int | str | date | datetime | timedelta]

        if self.len() == 0:
            raise ValueError("Series must contain at least one value")
        elif self.is_numeric():
            s = self.cast(Float64)
            stats = {
                "min": s.min(),
                "max": s.max(),
                "null_count": s.null_count(),
                "mean": s.mean(),
                "std": s.std(),
                "count": s.len(),
            }
        elif self.is_boolean():
            stats = {
                "sum": self.sum(),
                "null_count": self.null_count(),
                "count": self.len(),
            }
        elif self.is_utf8():
            stats = {
                "unique": len(self.unique()),
                "null_count": self.null_count(),
                "count": self.len(),
            }
        elif self.is_datelike():
            # we coerce all to string, because a polars column
            # only has a single dtype and dates: datetime and count: int don't match
            stats = {
                "min": str(self.dt.min()),
                "max": str(self.dt.max()),
                "null_count": str(self.null_count()),
                "count": str(self.len()),
            }
        else:
            raise TypeError("This type is not supported")

        return pli.DataFrame(
            {"statistic": list(stats.keys()), "value": list(stats.values())}
        )

    def sum(self) -> int | float:
        """
        Reduce this Series to the sum value.

        Notes
        -----
        Dtypes in {Int8, UInt8, Int16, UInt16} are cast to
        Int64 before summing to prevent overflow issues.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.sum()
        6

        """
        return self._s.sum()

    def mean(self) -> int | float:
        """
        Reduce this Series to the mean value.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.mean()
        2.0

        """
        return self._s.mean()

    def product(self) -> int | float:
        """Reduce this Series to the product value."""
        return self.to_frame().select(pli.col(self.name).product()).to_series()[0]

    def min(self) -> int | float | date | datetime | timedelta:
        """
        Get the minimal value in this Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.min()
        1

        """
        return self._s.min()

    def max(self) -> int | float | date | datetime | timedelta:
        """
        Get the maximum value in this Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.max()
        3

        """
        return self._s.max()

    def std(self, ddof: int = 1) -> float | None:
        """
        Get the standard deviation of this Series.

        Parameters
        ----------
        ddof
            “Delta Degrees of Freedom”: the divisor used in the calculation is N - ddof,
            where N represents the number of elements.
            By default ddof is 1.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.std()
        1.0

        """
        if not self.is_numeric():
            return None
        if ddof == 1:
            return self.to_frame().select(pli.col(self.name).std()).to_series()[0]
        if not _NUMPY_AVAILABLE:
            raise ImportError("'numpy' is required for this functionality.")
        return np.std(self.drop_nulls().view(), ddof=ddof)

    def var(self, ddof: int = 1) -> float | None:
        """
        Get variance of this Series.

        Parameters
        ----------
        ddof
            “Delta Degrees of Freedom”: the divisor used in the calculation is N - ddof,
            where N represents the number of elements.
            By default ddof is 1.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.var()
        1.0

        """
        if not self.is_numeric():
            return None
        if ddof == 1:
            return self.to_frame().select(pli.col(self.name).var()).to_series()[0]
        if not _NUMPY_AVAILABLE:
            raise ImportError("'numpy' is required for this functionality.")
        return np.var(self.drop_nulls().view(), ddof=ddof)

    def median(self) -> float:
        """
        Get the median of this Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.median()
        2.0

        """
        return self._s.median()

    def quantile(
        self, quantile: float, interpolation: InterpolationMethod = "nearest"
    ) -> float:
        """
        Get the quantile value of this Series.

        Parameters
        ----------
        quantile
            Quantile between 0.0 and 1.0.
        interpolation : {'nearest', 'higher', 'lower', 'midpoint', 'linear'}
            Interpolation method.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.quantile(0.5)
        2.0

        """
        return self._s.quantile(quantile, interpolation)

    def to_dummies(self) -> pli.DataFrame:
        """
        Get dummy variables.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.to_dummies()
        shape: (3, 3)
        ┌─────┬─────┬─────┐
        │ a_1 ┆ a_2 ┆ a_3 │
        │ --- ┆ --- ┆ --- │
        │ u8  ┆ u8  ┆ u8  │
        ╞═════╪═════╪═════╡
        │ 1   ┆ 0   ┆ 0   │
        ├╌╌╌╌╌┼╌╌╌╌╌┼╌╌╌╌╌┤
        │ 0   ┆ 1   ┆ 0   │
        ├╌╌╌╌╌┼╌╌╌╌╌┼╌╌╌╌╌┤
        │ 0   ┆ 0   ┆ 1   │
        └─────┴─────┴─────┘

        """
        return pli.wrap_df(self._s.to_dummies())

    def value_counts(self, sort: bool = False) -> pli.DataFrame:
        """
        Count the unique values in a Series.

        Parameters
        ----------
        sort:
            Ensure the output is sorted from most values to least.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 2, 3])
        >>> s.value_counts().sort(by="a")
        shape: (3, 2)
        ┌─────┬────────┐
        │ a   ┆ counts │
        │ --- ┆ ---    │
        │ i64 ┆ u32    │
        ╞═════╪════════╡
        │ 1   ┆ 1      │
        ├╌╌╌╌╌┼╌╌╌╌╌╌╌╌┤
        │ 2   ┆ 2      │
        ├╌╌╌╌╌┼╌╌╌╌╌╌╌╌┤
        │ 3   ┆ 1      │
        └─────┴────────┘

        """
        return pli.wrap_df(self._s.value_counts(sort))

    def unique_counts(self) -> Series:
        """
        Return a count of the unique values in the order of appearance.

        Examples
        --------
        >>> s = pl.Series("id", ["a", "b", "b", "c", "c", "c"])
        >>> s.unique_counts()
        shape: (3,)
        Series: 'id' [u32]
        [
            1
            2
            3
        ]

        """
        return pli.select(pli.lit(self).unique_counts()).to_series()

    def entropy(self, base: float = math.e, normalize: bool = False) -> float | None:
        """
        Compute the entropy as `-sum(pk * log(pk)`.
        where `pk` are discrete probabilities.

        This routine will normalize pk if they don’t sum to 1.

        Parameters
        ----------
        base
            Given base, defaults to `e`
        normalize
            Normalize pk if it doesn't sum to 1.

        Examples
        --------
        >>> a = pl.Series([0.99, 0.005, 0.005])
        >>> a.entropy(normalize=True)
        0.06293300616044681
        >>> b = pl.Series([0.65, 0.10, 0.25])
        >>> b.entropy(normalize=True)
        0.8568409950394724

        """
        return pli.select(pli.lit(self).entropy(base, normalize)).to_series()[0]

    def cumulative_eval(
        self, expr: pli.Expr, min_periods: int = 1, parallel: bool = False
    ) -> Series:
        """
        Run an expression over a sliding window that increases `1` slot every iteration.

        .. warning::
            This can be really slow as it can have `O(n^2)` complexity. Don't use this
            for operations that visit all elements.

        .. warning::
            This API is experimental and may change without it being considered a
            breaking change.

        Parameters
        ----------
        expr
            Expression to evaluate
        min_periods
            Number of valid values there should be in the window before the expression
            is evaluated. valid values = `length - null_count`
        parallel
            Run in parallel. Don't do this in a groupby or another operation that
            already has much parallelization.

        Examples
        --------
        >>> s = pl.Series("values", [1, 2, 3, 4, 5])
        >>> s.cumulative_eval(pl.element().first() - pl.element().last() ** 2)
        shape: (5,)
        Series: 'values' [f64]
        [
            0.0
            -3.0
            -8.0
            -15.0
            -24.0
        ]

        """
        return pli.select(
            pli.lit(self).cumulative_eval(expr, min_periods, parallel)
        ).to_series()

    @property
    def name(self) -> str:
        """Get the name of this Series."""
        return self._s.name()

    def alias(self, name: str) -> Series:
        """
        Return a copy of the Series with a new alias/name.

        Parameters
        ----------
        name
            New name.

        Examples
        --------
        >>> srs = pl.Series("x", [1, 2, 3])
        >>> new_aliased_srs = srs.alias("y")

        """
        s = self.clone()
        s._s.rename(name)
        return s

    @overload
    def rename(self, name: str, in_place: Literal[False] = ...) -> Series:
        ...

    @overload
    def rename(self, name: str, in_place: Literal[True]) -> None:
        ...

    @overload
    def rename(self, name: str, in_place: bool) -> Series | None:
        ...

    def rename(self, name: str, in_place: bool = False) -> Series | None:
        """
        Rename this Series.

        Parameters
        ----------
        name
            New name.
        in_place
            Modify the Series in-place.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.rename("b")
        shape: (3,)
        Series: 'b' [i64]
        [
                1
                2
                3
        ]

        """
        if in_place:
            self._s.rename(name)
            return None
        else:
            return self.alias(name)

    def chunk_lengths(self) -> list[int]:
        """Get the length of each individual chunk."""
        return self._s.chunk_lengths()

    def n_chunks(self) -> int:
        """Get the number of chunks that this Series contains."""
        return self._s.n_chunks()

    def cumsum(self, reverse: bool = False) -> Series:
        """
        Get an array with the cumulative sum computed at every element.

        Parameters
        ----------
        reverse
            reverse the operation.

        Notes
        -----
        Dtypes in {Int8, UInt8, Int16, UInt16} are cast to
        Int64 before summing to prevent overflow issues.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.cumsum()
        shape: (3,)
        Series: 'a' [i64]
        [
            1
            3
            6
        ]

        """
        return wrap_s(self._s.cumsum(reverse))

    def cummin(self, reverse: bool = False) -> Series:
        """
        Get an array with the cumulative min computed at every element.

        Parameters
        ----------
        reverse
            reverse the operation.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.cummin()
        shape: (3,)
        Series: 'a' [i64]
        [
            1
            1
            1
        ]

        """
        return wrap_s(self._s.cummin(reverse))

    def cummax(self, reverse: bool = False) -> Series:
        """
        Get an array with the cumulative max computed at every element.

        Parameters
        ----------
        reverse
            reverse the operation.

        Examples
        --------
        >>> s = pl.Series("a", [3, 5, 1])
        >>> s.cummax()
        shape: (3,)
        Series: 'a' [i64]
        [
            3
            5
            5
        ]

        """
        return wrap_s(self._s.cummax(reverse))

    def cumprod(self, reverse: bool = False) -> Series:
        """
        Get an array with the cumulative product computed at every element.

        Parameters
        ----------
        reverse
            reverse the operation.

        Notes
        -----
        Dtypes in {Int8, UInt8, Int16, UInt16} are cast to
        Int64 before summing to prevent overflow issues.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.cumprod()
        shape: (3,)
        Series: 'a' [i64]
        [
            1
            2
            6
        ]

        """
        return wrap_s(self._s.cumprod(reverse))

    def limit(self, num_elements: int = 10) -> Series:
        """
        Take n elements from this Series.

        Parameters
        ----------
        num_elements
            Amount of elements to take.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.limit(2)
        shape: (2,)
        Series: 'a' [i64]
        [
                1
                2
        ]

        """
        return wrap_s(self._s.limit(num_elements))

    def slice(self, offset: int, length: int | None = None) -> Series:
        """
        Get a slice of this Series.

        Parameters
        ----------
        offset
            Offset index.
        length
            Length of the slice.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.slice(1, 2)
        shape: (2,)
        Series: 'a' [i64]
        [
                2
                3
        ]

        """
        return wrap_s(self._s.slice(offset, length))

    def append(self, other: Series, append_chunks: bool = True) -> None:
        """
        Append a Series to this one.

        Parameters
        ----------
        other
            Series to append.
        append_chunks
            If set to `True` the append operation will add the chunks from `other` to
            self. This is super cheap.

            If set to `False` the append operation will do the same as
            `DataFrame.extend` which extends the memory backed by this `Series` with
            the values from `other`.

            Different from `append chunks`, `extent` appends the data from `other` to
            the underlying memory locations and thus may cause a reallocation (which are
            expensive).

            If this does not cause a reallocation, the resulting data structure will not
            have any extra chunks and thus will yield faster queries.

            Prefer `extend` over `append_chunks` when you want to do a query after a
            single append. For instance during online operations where you add `n` rows
            and rerun a query.

            Prefer `append_chunks` over `extend` when you want to append many times
            before doing a query. For instance when you read in multiple files and when
            to store them in a single `Series`. In the latter case, finish the sequence
            of `append_chunks` operations with a `rechunk`.


        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s2 = pl.Series("b", [4, 5, 6])
        >>> s.append(s2)
        >>> s
        shape: (6,)
        Series: 'a' [i64]
        [
            1
            2
            3
            4
            5
            6
        ]

        """
        try:
            if append_chunks:
                self._s.append(other._s)
            else:
                self._s.extend(other._s)
        except RuntimeError as e:
            if str(e) == "Already mutably borrowed":
                return self.append(other.clone(), append_chunks)
            else:
                raise e

    def filter(self, predicate: Series | list[bool]) -> Series:
        """
        Filter elements by a boolean mask.

        Parameters
        ----------
        predicate
            Boolean mask.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> mask = pl.Series("", [True, False, True])
        >>> s.filter(mask)
        shape: (2,)
        Series: 'a' [i64]
        [
                1
                3
        ]

        """
        if isinstance(predicate, list):
            predicate = Series("", predicate)
        return wrap_s(self._s.filter(predicate._s))

    def head(self, length: int | None = None) -> Series:
        """
        Get first N elements as Series.

        Parameters
        ----------
        length
            Length of the head.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.head(2)
        shape: (2,)
        Series: 'a' [i64]
        [
                1
                2
        ]

        """
        return wrap_s(self._s.head(length))

    def tail(self, length: int | None = None) -> Series:
        """
        Get last N elements as Series.

        Parameters
        ----------
        length
            Length of the tail.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.tail(2)
        shape: (2,)
        Series: 'a' [i64]
        [
                2
                3
        ]

        """
        return wrap_s(self._s.tail(length))

    def take_every(self, n: int) -> Series:
        """
        Take every nth value in the Series and return as new Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3, 4])
        >>> s.take_every(2)
        shape: (2,)
        Series: 'a' [i64]
        [
            1
            3
        ]

        """
        return wrap_s(self._s.take_every(n))

    @overload
    def sort(self, reverse: bool = False, *, in_place: Literal[False] = ...) -> Series:
        ...

    @overload
    def sort(self, reverse: bool = False, *, in_place: Literal[True]) -> None:
        ...

    @overload
    def sort(self, reverse: bool = False, *, in_place: bool = False) -> Series | None:
        ...

    def sort(self, reverse: bool = False, *, in_place: bool = False) -> Series | None:
        """
        Sort this Series.

        Parameters
        ----------
        reverse
            Reverse sort.
        in_place
            Sort in place.

        Examples
        --------
        >>> s = pl.Series("a", [1, 3, 4, 2])
        >>> s.sort()
        shape: (4,)
        Series: 'a' [i64]
        [
                1
                2
                3
                4
        ]
        >>> s.sort(reverse=True)
        shape: (4,)
        Series: 'a' [i64]
        [
                4
                3
                2
                1
        ]

        """
        if in_place:
            self._s = self._s.sort(reverse)
            return None
        else:
            return wrap_s(self._s.sort(reverse))

    def argsort(self, reverse: bool = False, nulls_last: bool = False) -> Series:
        """
        Index location of the sorted variant of this Series.

        Returns
        -------
        indexes
            Indexes that can be used to sort this array.
        nulls_last
            Place null values last.

        Examples
        --------
        >>> s = pl.Series("a", [5, 3, 4, 1, 2])
        >>> s.argsort()
        shape: (5,)
        Series: 'a' [u32]
        [
            3
            4
            1
            2
            0
        ]

        """
        return wrap_s(self._s.argsort(reverse, nulls_last))

    def arg_unique(self) -> Series:
        """Get unique index as Series."""
        return wrap_s(self._s.arg_unique())

    def arg_min(self) -> int | None:
        """Get the index of the minimal value."""
        return self._s.arg_min()

    def arg_max(self) -> int | None:
        """Get the index of the maximal value."""
        return self._s.arg_max()

    def search_sorted(self, element: int | float) -> int:
        """
        Find indices where elements should be inserted to maintain order.

        .. math:: a[i-1] < v <= a[i]

        Parameters
        ----------
        element
            Expression or scalar value.

        """
        return pli.select(pli.lit(self).search_sorted(element))[0, 0]

    def unique(self, maintain_order: bool = False) -> Series:
        """
        Get unique elements in series.

        Parameters
        ----------
        maintain_order
            Maintain order of data. This requires more work.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 2, 3])
        >>> s.unique().sort()
        shape: (3,)
        Series: 'a' [i64]
        [
            1
            2
            3
        ]

        """
        if maintain_order:
            return pli.select(pli.lit(self).unique(maintain_order)).to_series()
        return wrap_s(self._s.unique())

    def take(self, indices: np.ndarray[Any, Any] | list[int] | pli.Expr) -> Series:
        """
        Take values by index.

        Parameters
        ----------
        indices
            Index location used for selection.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3, 4])
        >>> s.take([1, 3])
        shape: (2,)
        Series: 'a' [i64]
        [
                2
                4
        ]

        """
        if isinstance(indices, pli.Expr):
            return pli.select(pli.lit(self).take(indices)).to_series()
        return wrap_s(self._s.take(indices))

    def null_count(self) -> int:
        """Count the null values in this Series."""
        return self._s.null_count()

    def has_validity(self) -> bool:
        """
        Return True if the Series has a validity bitmask.

        If there is none, it means that there are no null values.
        Use this to swiftly assert a Series does not have null values.

        """
        return self._s.has_validity()

    def is_empty(self) -> bool:
        """
        Check if the Series is empty.

        Examples
        --------
        >>> s = pl.Series("a", [], dtype=pl.Float32)
        >>> s.is_empty()
        True

        """
        return self.len() == 0

    def is_null(self) -> Series:
        """
        Get mask of null values.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 2.0, 3.0, None])
        >>> s.is_null()
        shape: (4,)
        Series: 'a' [bool]
        [
            false
            false
            false
            true
        ]

        """
        return wrap_s(self._s.is_null())

    def is_not_null(self) -> Series:
        """
        Get mask of non null values.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 2.0, 3.0, None])
        >>> s.is_not_null()
        shape: (4,)
        Series: 'a' [bool]
        [
            true
            true
            true
            false
        ]

        """
        return wrap_s(self._s.is_not_null())

    def is_finite(self) -> Series:
        """
        Get mask of finite values if Series dtype is Float.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> import numpy as np
        >>> s = pl.Series("a", [1.0, 2.0, np.inf])
        >>> s.is_finite()
        shape: (3,)
        Series: 'a' [bool]
        [
                true
                true
                false
        ]

        """
        return wrap_s(self._s.is_finite())

    def is_infinite(self) -> Series:
        """
        Get mask of infinite values if Series dtype is Float.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> import numpy as np
        >>> s = pl.Series("a", [1.0, 2.0, np.inf])
        >>> s.is_infinite()
        shape: (3,)
        Series: 'a' [bool]
        [
                false
                false
                true
        ]

        """
        return wrap_s(self._s.is_infinite())

    def is_nan(self) -> Series:
        """
        Get mask of NaN values if Series dtype is Float.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> import numpy as np
        >>> s = pl.Series("a", [1.0, 2.0, 3.0, np.NaN])
        >>> s.is_nan()
        shape: (4,)
        Series: 'a' [bool]
        [
                false
                false
                false
                true
        ]

        """
        return wrap_s(self._s.is_nan())

    def is_not_nan(self) -> Series:
        """
        Get negated mask of NaN values if Series dtype is_not Float.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> import numpy as np
        >>> s = pl.Series("a", [1.0, 2.0, 3.0, np.NaN])
        >>> s.is_not_nan()
        shape: (4,)
        Series: 'a' [bool]
        [
                true
                true
                true
                false
        ]

        """
        return wrap_s(self._s.is_not_nan())

    def is_in(self, other: Series | Sequence[object]) -> Series:
        """
        Check if elements of this Series are in the other Series, or
        if this Series is itself a member of the other Series.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s2 = pl.Series("b", [2, 4])
        >>> s2.is_in(s)
        shape: (2,)
        Series: 'b' [bool]
        [
                true
                false
        ]

        >>> # check if some values are a member of sublists
        >>> sets = pl.Series("sets", [[1, 2, 3], [1, 2], [9, 10]])
        >>> optional_members = pl.Series("optional_members", [1, 2, 3])
        >>> print(sets)
        shape: (3,)
        Series: 'sets' [list]
        [
            [1, 2, 3]
            [1, 2]
            [9, 10]
        ]
        >>> print(optional_members)
        shape: (3,)
        Series: 'optional_members' [i64]
        [
            1
            2
            3
        ]
        >>> optional_members.is_in(sets)
        shape: (3,)
        Series: 'optional_members' [bool]
        [
            true
            true
            false
        ]

        """
        if isinstance(other, str):
            raise TypeError("'other' parameter expects non-string sequence data")
        elif isinstance(other, Sequence):
            other = Series("", other)
        return wrap_s(self._s.is_in(other._s))

    def arg_true(self) -> Series:
        """
        Get index values where Boolean Series evaluate True.

        Returns
        -------
        UInt32 Series

        """
        return pli.arg_where(self, eager=True)

    def is_unique(self) -> Series:
        """
        Get mask of all unique values.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 2, 3])
        >>> s.is_unique()
        shape: (4,)
        Series: 'a' [bool]
        [
                true
                false
                false
                true
        ]

        """
        return wrap_s(self._s.is_unique())

    def is_first(self) -> Series:
        """
        Get a mask of the first unique value.

        Returns
        -------
        Boolean Series

        """
        return wrap_s(self._s.is_first())

    def is_duplicated(self) -> Series:
        """
        Get mask of all duplicated values.

        Returns
        -------
        Boolean Series

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 2, 3])
        >>> s.is_duplicated()
        shape: (4,)
        Series: 'a' [bool]
        [
                false
                true
                true
                false
        ]

        """
        return wrap_s(self._s.is_duplicated())

    def explode(self) -> Series:
        """
        Explode a list or utf8 Series.

        This means that every item is expanded to a new row.

        Examples
        --------
        >>> s = pl.Series("a", [[1, 2], [3, 4], [9, 10]])
        >>> s.explode()
        shape: (6,)
        Series: 'a' [i64]
        [
                1
                2
                3
                4
                9
                10
        ]

        Returns
        -------
        Exploded Series of same dtype

        """
        return wrap_s(self._s.explode())

    def series_equal(
        self, other: Series, null_equal: bool = False, strict: bool = False
    ) -> bool:
        """
        Check if series is equal with another Series.

        Parameters
        ----------
        other
            Series to compare with.
        null_equal
            Consider null values as equal.
        strict
            Don't allow different numerical dtypes, e.g. comparing `pl.UInt32` with a
            `pl.Int64` will return `False`.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s2 = pl.Series("b", [4, 5, 6])
        >>> s.series_equal(s)
        True
        >>> s.series_equal(s2)
        False

        """
        return self._s.series_equal(other._s, null_equal, strict)

    def len(self) -> int:
        """
        Length of this Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.len()
        3

        """
        return self._s.len()

    @property
    def shape(self) -> tuple[int]:
        """Shape of this Series."""
        return (self._s.len(),)

    def __len__(self) -> int:
        return self.len()

    def cast(
        self,
        dtype: (
            type[DataType] | type[int] | type[float] | type[str] | type[bool] | DataType
        ),
        strict: bool = True,
    ) -> Series:
        """
        Cast between data types.

        Parameters
        ----------
        dtype
            DataType to cast to
        strict
            Throw an error if a cast could not be done for instance due to an overflow

        Examples
        --------
        >>> s = pl.Series("a", [True, False, True])
        >>> s
        shape: (3,)
        Series: 'a' [bool]
        [
            true
            false
            true
        ]

        >>> s.cast(pl.UInt32)
        shape: (3,)
        Series: 'a' [u32]
        [
            1
            0
            1
        ]

        """
        pl_dtype = py_type_to_dtype(dtype)
        return wrap_s(self._s.cast(pl_dtype, strict))

    def to_physical(self) -> Series:
        """
        Cast to physical representation of the logical dtype.

        - :func:`polars.datatypes.Date` -> :func:`polars.datatypes.Int32`
        - :func:`polars.datatypes.Datetime` -> :func:`polars.datatypes.Int64`
        - :func:`polars.datatypes.Time` -> :func:`polars.datatypes.Int64`
        - :func:`polars.datatypes.Duration` -> :func:`polars.datatypes.Int64`
        - :func:`polars.datatypes.Categorical` -> :func:`polars.datatypes.UInt32`
        - Other data types will be left unchanged.

        Examples
        --------
        Replicating the pandas
        `pd.Series.factorize
        <https://pandas.pydata.org/docs/reference/api/pandas.Series.factorize.html>`_
        method.

        >>> s = pl.Series("values", ["a", None, "x", "a"])
        >>> s.cast(pl.Categorical).to_physical()
        shape: (4,)
        Series: 'values' [u32]
        [
            0
            null
            1
            0
        ]

        """
        return wrap_s(self._s.to_physical())

    def to_list(self, use_pyarrow: bool = False) -> list[Any | None]:
        """
        Convert this Series to a Python List. This operation clones data.

        Parameters
        ----------
        use_pyarrow
            Use pyarrow for the conversion.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.to_list()
        [1, 2, 3]
        >>> type(s.to_list())
        <class 'list'>

        """
        if use_pyarrow:
            return self.to_arrow().to_pylist()
        return self._s.to_list()

    def __iter__(self) -> SeriesIter:
        return SeriesIter(self.len(), self)

    @overload
    def rechunk(self, in_place: Literal[False] = ...) -> Series:
        ...

    @overload
    def rechunk(self, in_place: Literal[True]) -> None:
        ...

    @overload
    def rechunk(self, in_place: bool) -> Series | None:
        ...

    def rechunk(self, in_place: bool = False) -> Series | None:
        """
        Create a single chunk of memory for this Series.

        Parameters
        ----------
        in_place
            In place or not.

        """
        opt_s = self._s.rechunk(in_place)
        if in_place:
            return None
        else:
            return wrap_s(opt_s)

    def reverse(self) -> Series:
        """
        Return Series in reverse order.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3], dtype=pl.Int8)
        >>> s.reverse()
        shape: (3,)
        Series: 'a' [i8]
        [
            3
            2
            1
        ]

        """
        return wrap_s(self._s.reverse())

    def is_numeric(self) -> bool:
        """
        Check if this Series datatype is numeric.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.is_numeric()
        True

        """
        return self.dtype in (
            Int8,
            Int16,
            Int32,
            Int64,
            UInt8,
            UInt16,
            UInt32,
            UInt64,
            Float32,
            Float64,
        )

    def is_datelike(self) -> bool:
        """
        Check if this Series datatype is datelike.

        Examples
        --------
        >>> from datetime import date
        >>> s = pl.Series([date(2021, 1, 1), date(2021, 1, 2), date(2021, 1, 3)])
        >>> s.is_datelike()
        True

        """
        return self.dtype in (Date, Datetime, Duration, Time)

    def is_float(self) -> bool:
        """
        Check if this Series has floating point numbers.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 2.0, 3.0])
        >>> s.is_float()
        True

        """
        return self.dtype in (Float32, Float64)

    def is_boolean(self) -> bool:
        """
        Check if this Series is a Boolean.

        Examples
        --------
        >>> s = pl.Series("a", [True, False, True])
        >>> s.is_boolean()
        True

        """
        return self.dtype is Boolean

    def is_utf8(self) -> bool:
        """
        Check if this Series datatype is a Utf8.

        Examples
        --------
        >>> s = pl.Series("x", ["a", "b", "c"])
        >>> s.is_utf8()
        True

        """
        return self.dtype is Utf8

    def view(self, ignore_nulls: bool = False) -> np.ndarray[Any, Any]:
        """
        Get a view into this Series data with a numpy array. This operation doesn't
        clone data, but does not include missing values. Don't use this unless you know
        what you are doing.

        .. warning::

            This function can lead to undefined behavior in the following cases:

            Returns a view to a piece of memory that is already dropped:

            >>> pl.Series([1, 3, 5]).sort().view()  # doctest: +IGNORE_RESULT

            Sums invalid data that is missing:

            >>> pl.Series([1, 2, None]).view().sum()  # doctest: +SKIP

        """
        if not ignore_nulls:
            assert not self.has_validity()

        ptr_type = dtype_to_ctype(self.dtype)
        ptr = self._s.as_single_ptr()
        array = _ptr_to_numpy(ptr, self.len(), ptr_type)
        array.setflags(write=False)
        return array

    def __array__(self, dtype: Any = None) -> np.ndarray[Any, Any]:
        if dtype:
            return self.to_numpy().__array__(dtype)
        else:
            return self.to_numpy().__array__()

    def __array_ufunc__(
        self,
        ufunc: np.ufunc,
        method: str,
        *inputs: Any,
        **kwargs: Any,
    ) -> Series:
        """Numpy universal functions."""
        if not _NUMPY_AVAILABLE:
            raise ImportError("'numpy' is required for this functionality.")

        if self._s.n_chunks() > 1:
            self._s.rechunk(in_place=True)

        s = self._s

        if method == "__call__":
            if not ufunc.nout == 1:
                raise NotImplementedError(
                    "Only ufuncs that return one 1D array, are supported."
                )

            args: list[int | float | np.ndarray[Any, Any]] = []

            for arg in inputs:
                if isinstance(arg, (int, float, np.ndarray)):
                    args.append(arg)
                elif isinstance(arg, Series):
                    args.append(arg.view(ignore_nulls=True))
                else:
                    raise ValueError(f"Unsupported type {type(arg)} for {arg}.")

            # Get minimum dtype needed to be able to cast all input arguments to the
            # same dtype.
            dtype_char_minimum = np.result_type(*args).char

            # Get all possible output dtypes for ufunc.
            # Input dtypes and output dtypes seem to always match for ufunc.types,
            # so pick all the different output dtypes.
            dtypes_ufunc = [
                input_output_type[-1]
                for input_output_type in ufunc.types
                if supported_numpy_char_code(input_output_type[-1])
            ]

            # Get the first ufunc dtype from all possible ufunc dtypes for which
            # the input arguments can be safely cast to that ufunc dtype.
            for dtype_ufunc in dtypes_ufunc:
                if np.can_cast(dtype_char_minimum, dtype_ufunc):
                    dtype_char_minimum = dtype_ufunc
                    break

            # Override minimum dtype if requested.
            dtype = (
                np.dtype(kwargs.pop("dtype")).char
                if "dtype" in kwargs
                else dtype_char_minimum
            )

            f = get_ffi_func(
                "apply_ufunc_<>", numpy_char_code_to_dtype(dtype_char_minimum), s
            )

            if f is None:
                raise NotImplementedError(
                    f"Could not find `apply_ufunc_{numpy_char_code_to_dtype(dtype)}`."
                )

            series = f(lambda out: ufunc(*args, out=out, **kwargs))
            return wrap_s(series)
        else:
            raise NotImplementedError(
                "Only `__call__` is implemented for numpy ufuncs on a Series, got"
                f" `{method}`."
            )

    def to_numpy(
        self, *args: Any, zero_copy_only: bool = False, **kwargs: Any
    ) -> np.ndarray[Any, Any]:
        """
        Convert this Series to numpy. This operation clones data but is completely safe.

        If you want a zero-copy view and know what you are doing, use `.view()`.

        Notes
        -----
        If you are attempting to convert Utf8 to an array you'll need to install
        `pyarrow`.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> arr = s.to_numpy()
        >>> arr  # doctest: +IGNORE_RESULT
        array([1, 2, 3], dtype=int64)
        >>> type(arr)
        <class 'numpy.ndarray'>

        Parameters
        ----------
        args
            args will be sent to pyarrow.Array.to_numpy.
        zero_copy_only
            If True, an exception will be raised if the conversion to a numpy
            array would require copying the underlying data (e.g. in presence
            of nulls, or for non-primitive types).
        kwargs
            kwargs will be sent to pyarrow.Array.to_numpy

        """

        def convert_to_date(arr: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
            if self.dtype == Date:
                tp = "datetime64[D]"
            elif self.dtype == Duration:
                tp = f"timedelta64[{self.time_unit}]"
            else:
                tp = f"datetime64[{self.time_unit}]"
            return arr.astype(tp)

        if _PYARROW_AVAILABLE and not self.is_datelike():
            return self.to_arrow().to_numpy(
                *args, zero_copy_only=zero_copy_only, **kwargs
            )
        else:
            if not self.has_validity():
                if self.is_datelike():
                    return convert_to_date(self.view(ignore_nulls=True))
                return self.view(ignore_nulls=True)
            if self.is_datelike():
                return convert_to_date(self._s.to_numpy())
            return self._s.to_numpy()

    def to_arrow(self) -> pa.Array:
        """
        Get the underlying Arrow Array. If the Series contains only a single chunk
        this operation is zero copy.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s = s.to_arrow()
        >>> s  # doctest: +ELLIPSIS
        <pyarrow.lib.Int64Array object at ...>
        [
          1,
          2,
          3
        ]

        """
        return self._s.to_arrow()

    def to_pandas(self) -> pd.Series:
        """Convert this Series to a pandas Series."""
        if not _PYARROW_AVAILABLE:  # pragma: no cover
            raise ImportError(
                "'pyarrow' is required for converting a 'polars' Series to a 'pandas'"
                " Series."
            )
        return self.to_arrow().to_pandas()

    def set(self, filter: Series, value: int | float | str) -> Series:
        """
        Set masked values.

        .. note::
            Using this is an anti-pattern.
            Always prefer: `pl.when(predicate).then(value).otherwise(self)`

        Parameters
        ----------
        filter
            Boolean mask.
        value
            Value to replace the the masked values with.

        """
        f = get_ffi_func("set_with_mask_<>", self.dtype, self._s)
        if f is None:
            return NotImplemented
        return wrap_s(f(filter._s, value))

    def set_at_idx(
        self,
        idx: Series | np.ndarray[Any, Any] | list[int] | tuple[int],
        value: int
        | float
        | str
        | bool
        | Sequence[int]
        | Sequence[float]
        | Sequence[date]
        | Sequence[datetime]
        | date
        | datetime
        | Series,
    ) -> Series:
        """
        Set values at the index locations.

        .. note::
            Using this is an anti-pattern.
            Always prefer: `pl.when(predicate).then(value).otherwise(self)`

        Parameters
        ----------
        idx
            Integers representing the index locations.
        value
            replacement values.

        Returns
        -------
        the series mutated

        """
        if self.is_numeric() or self.is_datelike():
            idx = Series("", idx)
            if isinstance(value, (int, float, bool)):
                value = Series("", [value])

                # if we need to set more than a single value, we extend it
                if len(idx) > 0:
                    value = value.extend_constant(value[0], len(idx) - 1)
            elif not isinstance(value, Series):
                value = Series("", value)
            self._s.set_at_idx(idx._s, value._s)
            return self

        # the set_at_idx function expects a np.array of dtype u32
        f = get_ffi_func("set_at_idx_<>", self.dtype, self._s)
        if f is None:
            raise ValueError(
                "could not find the FFI function needed to set at idx for series"
                f" {self._s}"
            )
        if isinstance(idx, Series):
            # make sure the dtype matches
            idx = idx.cast(UInt32)
            idx_array = idx.view()
        elif _NUMPY_AVAILABLE and isinstance(idx, np.ndarray):
            if not idx.data.c_contiguous:
                idx_array = np.ascontiguousarray(idx, dtype=np.uint32)
            else:
                idx_array = idx
                if idx_array.dtype != np.uint32:
                    idx_array = np.array(idx_array, np.uint32)

        else:
            if not _NUMPY_AVAILABLE:
                raise ImportError("'numpy' is required for this functionality.")
            idx_array = np.array(idx, dtype=np.uint32)

        self._s = f(idx_array, value)
        return self

    def cleared(self) -> Series:
        """
        Create an empty copy of the current Series, with identical name/dtype but no
        data.

        See Also
        --------
        clone : Cheap deepcopy/clone.

        Examples
        --------
        >>> s = pl.Series("a", [None, True, False])
        >>> s.cleared()
        shape: (0,)
        Series: 'a' [bool]
        [
        ]

        """
        return self.limit(0) if len(self) > 0 else self.clone()

    def clone(self) -> Series:
        """
        Very cheap deepcopy/clone.

        See Also
        --------
        cleared : Create an empty copy of the current Series, with identical
            schema but no data.

        """
        return wrap_s(self._s.clone())

    def __copy__(self) -> Series:
        return self.clone()

    def __deepcopy__(self, memo: None = None) -> Series:
        return self.clone()

    def fill_nan(self, fill_value: str | int | float | bool | pli.Expr) -> Series:
        """Fill floating point NaN value with a fill value."""
        return (
            self.to_frame().select(pli.col(self.name).fill_nan(fill_value)).to_series()
        )

    def fill_null(
        self,
        value: Any | None = None,
        strategy: FillNullStrategy | None = None,
        limit: int | None = None,
    ) -> Series:
        """
        Fill null values using the specified value or strategy.

        Parameters
        ----------
        value
            Value used to fill null values.
        strategy : {None, 'forward', 'backward', 'min', 'max', 'mean', 'zero', 'one'}
            Strategy used to fill null values.
        limit
            Number of consecutive null values to fill when using the 'forward' or
            'backward' strategy.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3, None])
        >>> s.fill_null(strategy="forward")
        shape: (4,)
        Series: 'a' [i64]
        [
            1
            2
            3
            3
        ]
        >>> s.fill_null(strategy="min")
        shape: (4,)
        Series: 'a' [i64]
        [
            1
            2
            3
            1
        ]
        >>> s = pl.Series("b", ["x", None, "z"])
        >>> s.fill_null(pl.lit(""))
        shape: (3,)
        Series: 'b' [str]
        [
            "x"
            ""
            "z"
        ]

        """
        return self.to_frame().select(
            pli.col(self.name).fill_null(value, strategy, limit)
        )[self.name]

    def floor(self) -> Series:
        """
        Floor underlying floating point array to the lowest integers smaller or equal to
        the float value.

        Only works on floating point Series

        """
        return wrap_s(self._s.floor())

    def ceil(self) -> Series:
        """
        Ceil underlying floating point array to the highest integers smaller or equal to
        the float value.

        Only works on floating point Series

        """
        return self.to_frame().select(pli.col(self.name).ceil()).to_series()

    def round(self, decimals: int) -> Series:
        """
        Round underlying floating point data by `decimals` digits.

        Examples
        --------
        >>> s = pl.Series("a", [1.12345, 2.56789, 3.901234])
        >>> s.round(2)
        shape: (3,)
        Series: 'a' [f64]
        [
                1.12
                2.57
                3.9
        ]

        Parameters
        ----------
        decimals
            number of decimals to round by.

        """
        return wrap_s(self._s.round(decimals))

    def dot(self, other: Series) -> float | None:
        """
        Compute the dot/inner product between two Series

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s2 = pl.Series("b", [4.0, 5.0, 6.0])
        >>> s.dot(s2)
        32.0

        Parameters
        ----------
        other
            Series to compute dot product with

        """
        return self._s.dot(other._s)

    def mode(self) -> Series:
        """
        Compute the most occurring value(s). Can return multiple Values

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 2, 3])
        >>> s.mode()
        shape: (1,)
        Series: 'a' [i64]
        [
                2
        ]

        """
        return wrap_s(self._s.mode())

    def sign(self) -> Series:
        """
        Compute the element-wise indication of the sign.

        Examples
        --------
        >>> s = pl.Series("a", [-9.0, -0.0, 0.0, 4.0, None])
        >>> s.sign()
        shape: (5,)
        Series: 'a' [i64]
        [
                -1
                0
                0
                1
                null
        ]

        """
        return self.to_frame().select(pli.col(self.name).sign()).to_series()

    def sin(self) -> Series:
        """
        Compute the element-wise value for the sine.

        Examples
        --------
        >>> import math
        >>> s = pl.Series("a", [0.0, math.pi / 2.0, math.pi])
        >>> s.sin()
        shape: (3,)
        Series: 'a' [f64]
        [
            0.0
            1.0
            1.2246e-16
        ]

        """
        return self.to_frame().select(pli.col(self.name).sin()).to_series()

    def cos(self) -> Series:
        """
        Compute the element-wise value for the cosine.

        Examples
        --------
        >>> import math
        >>> s = pl.Series("a", [0.0, math.pi / 2.0, math.pi])
        >>> s.cos()
        shape: (3,)
        Series: 'a' [f64]
        [
            1.0
            6.1232e-17
            -1.0
        ]

        """
        return self.to_frame().select(pli.col(self.name).cos()).to_series()

    def tan(self) -> Series:
        """
        Compute the element-wise value for the tangent.

        Examples
        --------
        >>> import math
        >>> s = pl.Series("a", [0.0, math.pi / 2.0, math.pi])
        >>> s.tan()
        shape: (3,)
        Series: 'a' [f64]
        [
            0.0
            1.6331e16
            -1.2246e-16
        ]

        """
        return self.to_frame().select(pli.col(self.name).tan()).to_series()

    def arcsin(self) -> Series:
        """
        Compute the element-wise value for the inverse sine.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.arcsin()
        shape: (3,)
        Series: 'a' [f64]
        [
            1.570796
            0.0
            -1.570796
        ]

        """
        return self.to_frame().select(pli.col(self.name).arcsin()).to_series()

    def arccos(self) -> Series:
        """
        Compute the element-wise value for the inverse cosine.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.arccos()
        shape: (3,)
        Series: 'a' [f64]
        [
            0.0
            1.570796
            3.141593
        ]

        """
        return self.to_frame().select(pli.col(self.name).arccos()).to_series()

    def arctan(self) -> Series:
        """
        Compute the element-wise value for the inverse tangent.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.arctan()
        shape: (3,)
        Series: 'a' [f64]
        [
            0.785398
            0.0
            -0.785398
        ]

        """
        return self.to_frame().select(pli.col(self.name).arctan()).to_series()

    def arcsinh(self) -> Series:
        """
        Compute the element-wise value for the inverse hyperbolic sine.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.arcsinh()
        shape: (3,)
        Series: 'a' [f64]
        [
            0.881374
            0.0
            -0.881374
        ]

        """
        return self.to_frame().select(pli.col(self.name).arcsinh()).to_series()

    def arccosh(self) -> Series:
        """
        Compute the element-wise value for the inverse hyperbolic cosine.

        Examples
        --------
        >>> s = pl.Series("a", [5.0, 1.0, 0.0, -1.0])
        >>> s.arccosh()
        shape: (4,)
        Series: 'a' [f64]
        [
            2.292432
            0.0
            NaN
            NaN
        ]

        """
        return self.to_frame().select(pli.col(self.name).arccosh()).to_series()

    def arctanh(self) -> Series:
        """
        Compute the element-wise value for the inverse hyperbolic tangent.

        Examples
        --------
        >>> s = pl.Series("a", [2.0, 1.0, 0.5, 0.0, -0.5, -1.0, -1.1])
        >>> s.arctanh()
        shape: (7,)
        Series: 'a' [f64]
        [
            NaN
            inf
            0.549306
            0.0
            -0.549306
            -inf
            NaN
        ]

        """
        return self.to_frame().select(pli.col(self.name).arctanh()).to_series()

    def sinh(self) -> Series:
        """
        Compute the element-wise value for the hyperbolic sine.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.sinh()
        shape: (3,)
        Series: 'a' [f64]
        [
            1.175201
            0.0
            -1.175201
        ]

        """
        return self.to_frame().select(pli.col(self.name).sinh()).to_series()

    def cosh(self) -> Series:
        """
        Compute the element-wise value for the hyperbolic cosine.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.cosh()
        shape: (3,)
        Series: 'a' [f64]
        [
            1.543081
            1.0
            1.543081
        ]

        """
        return self.to_frame().select(pli.col(self.name).cosh()).to_series()

    def tanh(self) -> Series:
        """
        Compute the element-wise value for the hyperbolic tangent.

        Examples
        --------
        >>> s = pl.Series("a", [1.0, 0.0, -1.0])
        >>> s.tanh()
        shape: (3,)
        Series: 'a' [f64]
        [
            0.761594
            0.0
            -0.761594
        ]

        """
        return self.to_frame().select(pli.col(self.name).tanh()).to_series()

    def apply(
        self,
        func: Callable[[Any], Any],
        return_dtype: type[DataType] | None = None,
    ) -> Series:
        """
        Apply a function over elements in this Series and return a new Series.

        If the function returns another datatype, the return_dtype arg should be set,
        otherwise the method will fail.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.apply(lambda x: x + 10)
        shape: (3,)
        Series: 'a' [i64]
        [
                11
                12
                13
        ]

        Parameters
        ----------
        func
            function or lambda.
        return_dtype
            Output datatype. If none is given, the same datatype as this Series will be
            used.

        Returns
        -------
        Series

        """
        if return_dtype is None:
            pl_return_dtype = None
        else:
            pl_return_dtype = py_type_to_dtype(return_dtype)
        return wrap_s(self._s.apply_lambda(func, pl_return_dtype))

    def shift(self, periods: int = 1) -> Series:
        """
        Shift the values by a given period and fill the parts that will be empty due to
        this operation with `Nones`.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.shift(periods=1)
        shape: (3,)
        Series: 'a' [i64]
        [
                null
                1
                2
        ]
        >>> s.shift(periods=-1)
        shape: (3,)
        Series: 'a' [i64]
        [
                2
                3
                null
        ]

        Parameters
        ----------
        periods
            Number of places to shift (may be negative).

        """
        return wrap_s(self._s.shift(periods))

    def shift_and_fill(self, periods: int, fill_value: int | pli.Expr) -> Series:
        """
        Shift the values by a given period and fill the parts that will be empty due to
        this operation with the result of the `fill_value` expression.

        Parameters
        ----------
        periods
            Number of places to shift (may be negative).
        fill_value
            Fill None values with the result of this expression.

        """
        return self.to_frame().select(
            pli.col(self.name).shift_and_fill(periods, fill_value)
        )[self.name]

    def zip_with(self, mask: Series, other: Series) -> Series:
        """
        Where mask evaluates true, take values from self. Where mask evaluates false,
        take values from other.

        Parameters
        ----------
        mask
            Boolean Series.
        other
            Series of same type.

        Returns
        -------
        New Series

        Examples
        --------
        >>> s1 = pl.Series([1, 2, 3, 4, 5])
        >>> s2 = pl.Series([5, 4, 3, 2, 1])
        >>> s1.zip_with(s1 < s2, s2)
        shape: (5,)
        Series: '' [i64]
        [
                1
                2
                3
                2
                1
        ]
        >>> mask = pl.Series([True, False, True, False, True])
        >>> s1.zip_with(mask, s2)
        shape: (5,)
        Series: '' [i64]
        [
                1
                4
                3
                2
                5
        ]

        """
        return wrap_s(self._s.zip_with(mask._s, other._s))

    def rolling_min(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Apply a rolling min (moving min) over the values in this array.

        A window of length `window_size` will traverse the array. The values that fill
        this window will (optionally) be multiplied with the weights given by the
        `weight` vector. The resulting values will be aggregated to their sum.

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        Examples
        --------
        >>> s = pl.Series("a", [100, 200, 300, 400, 500])
        >>> s.rolling_min(window_size=3)
        shape: (5,)
        Series: 'a' [i64]
        [
            null
            null
            100
            200
            300
        ]

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_min(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_max(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Apply a rolling max (moving max) over the values in this array.

        A window of length `window_size` will traverse the array. The values that fill
        this window will (optionally) be multiplied with the weights given by the
        `weight` vector. The resulting values will be aggregated to their sum.

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        Examples
        --------
        >>> s = pl.Series("a", [100, 200, 300, 400, 500])
        >>> s.rolling_max(window_size=2)
        shape: (5,)
        Series: 'a' [i64]
        [
            null
            200
            300
            400
            500
        ]

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_max(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_mean(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Apply a rolling mean (moving mean) over the values in this array.
        A window of length `window_size` will traverse the array. The values that fill
        this window will (optionally) be multiplied with the weights given by the
        `weight` vector. The resulting values will be aggregated to their sum.

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        Examples
        --------
        >>> s = pl.Series("a", [100, 200, 300, 400, 500])
        >>> s.rolling_mean(window_size=2)
        shape: (5,)
        Series: 'a' [f64]
        [
            null
            150.0
            250.0
            350.0
            450.0
        ]

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_mean(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_sum(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Apply a rolling sum (moving sum) over the values in this array.
        A window of length `window_size` will traverse the array. The values that fill
        this window will (optionally) be multiplied with the weights given by the
        `weight` vector. The resulting values will be aggregated to their sum.

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length of the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3, 4, 5])
        >>> s.rolling_sum(window_size=2)
        shape: (5,)
        Series: 'a' [i64]
        [
                null
                3
                5
                7
                9
        ]

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_sum(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_std(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Compute a rolling std dev

        A window of length `window_size` will traverse the array. The values that fill
        this window will (optionally) be multiplied with the weights given by the
        `weight` vector. The resulting values will be aggregated to their sum.

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_std(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_var(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Compute a rolling variance.

        A window of length `window_size` will traverse the array. The values that fill
        this window will (optionally) be multiplied with the weights given by the
        `weight` vector. The resulting values will be aggregated to their sum.

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_var(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_apply(
        self,
        function: Callable[[pli.Series], Any],
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> pli.Series:
        """
        Apply a custom rolling window function.

        Prefer the specific rolling window functions over this one, as they are faster:

            * rolling_min
            * rolling_max
            * rolling_mean
            * rolling_sum

        Parameters
        ----------
        function
            Aggregation function
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        Examples
        --------
        >>> s = pl.Series("A", [1.0, 2.0, 9.0, 2.0, 13.0])
        >>> s.rolling_apply(function=lambda s: s.std(), window_size=3)
        shape: (5,)
        Series: 'A' [f64]
        [
            null
            null
            4.358899
            4.041452
            5.567764
        ]

        """
        if min_periods is None:
            min_periods = window_size
        return self.to_frame().select(
            pli.col(self.name).rolling_apply(
                function, window_size, weights, min_periods, center
            )
        )[self.name]

    def rolling_median(
        self,
        window_size: int,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Compute a rolling median

        Parameters
        ----------
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        """
        if min_periods is None:
            min_periods = window_size

        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_median(
                    window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_quantile(
        self,
        quantile: float,
        interpolation: InterpolationMethod = "nearest",
        window_size: int = 2,
        weights: list[float] | None = None,
        min_periods: int | None = None,
        center: bool = False,
    ) -> Series:
        """
        Compute a rolling quantile

        Parameters
        ----------
        quantile
            Quantile between 0.0 and 1.0.
        interpolation : {'nearest', 'higher', 'lower', 'midpoint', 'linear'}
            Interpolation method.
        window_size
            The length of the window.
        weights
            An optional slice with the same length as the window that will be multiplied
            elementwise with the values in the window.
        min_periods
            The number of values in the window that should be non-null before computing
            a result. If None, it will be set equal to window size.
        center
            Set the labels at the center of the window

        """
        if min_periods is None:
            min_periods = window_size

        return (
            self.to_frame()
            .select(
                pli.col(self.name).rolling_quantile(
                    quantile, interpolation, window_size, weights, min_periods, center
                )
            )
            .to_series()
        )

    def rolling_skew(self, window_size: int, bias: bool = True) -> Series:
        """
        Compute a rolling skew

        Parameters
        ----------
        window_size
            Size of the rolling window
        bias
            If False, then the calculations are corrected for statistical bias.

        """
        return self.to_frame().select(
            pli.col(self.name).rolling_skew(window_size, bias)
        )[self.name]

    def sample(
        self,
        n: int | None = None,
        frac: float | None = None,
        with_replacement: bool = False,
        shuffle: bool = False,
        seed: int | None = None,
    ) -> Series:
        """
        Sample from this Series by setting either `n` or `frac`.

        Parameters
        ----------
        n
            Number of samples < self.len().
        frac
            Fraction between 0.0 and 1.0 .
        with_replacement
            sample with replacement.
        shuffle
            Shuffle the order of sampled data points.
        seed
            Initialization seed. If None is given a random seed is used.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3, 4, 5])
        >>> s.sample(2, seed=0)  # doctest: +IGNORE_RESULT
        shape: (2,)
        Series: 'a' [i64]
        [
            1
            5
        ]

        """
        if n is not None and frac is not None:
            raise ValueError("n and frac were both supplied")

        if n is None and frac is not None:
            return wrap_s(self._s.sample_frac(frac, with_replacement, shuffle, seed))

        if n is None:
            n = 1

        return wrap_s(self._s.sample_n(n, with_replacement, shuffle, seed))

    def peak_max(self) -> Series:
        """
        Get a boolean mask of the local maximum peaks.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3, 4, 5])
        >>> s.peak_max()
        shape: (5,)
        Series: '' [bool]
        [
                false
                false
                false
                false
                true
        ]

        """
        return wrap_s(self._s.peak_max())

    def peak_min(self) -> Series:
        """
        Get a boolean mask of the local minimum peaks.

        Examples
        --------
        >>> s = pl.Series("a", [4, 1, 3, 2, 5])
        >>> s.peak_min()
        shape: (5,)
        Series: '' [bool]
        [
            false
            true
            false
            true
            false
        ]

        """
        return wrap_s(self._s.peak_min())

    def n_unique(self) -> int:
        """
        Count the number of unique values in this Series.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 2, 3])
        >>> s.n_unique()
        3

        """
        return self._s.n_unique()

    @overload
    def shrink_to_fit(self, in_place: Literal[False] = ...) -> Series:
        ...

    @overload
    def shrink_to_fit(self, in_place: Literal[True]) -> None:
        ...

    @overload
    def shrink_to_fit(self, in_place: bool = False) -> Series | None:
        ...

    def shrink_to_fit(self, in_place: bool = False) -> Series | None:
        """
        Shrink memory usage of this Series to fit the exact capacity needed to hold the
        data.
        """
        if in_place:
            self._s.shrink_to_fit()
            return None
        else:
            series = self.clone()
            series._s.shrink_to_fit()
            return series

    def hash(
        self,
        seed: int = 0,
        seed_1: int | None = None,
        seed_2: int | None = None,
        seed_3: int | None = None,
    ) -> pli.Series:
        """
        Hash the Series.

        The hash value is of type `UInt64`.

        Parameters
        ----------
        seed
            Random seed parameter. Defaults to 0.
        seed_1
            Random seed parameter. Defaults to `seed` if not set.
        seed_2
            Random seed parameter. Defaults to `seed` if not set.
        seed_3
            Random seed parameter. Defaults to `seed` if not set.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, 3])
        >>> s.hash(seed=42)
        shape: (3,)
        Series: 'a' [u64]
        [
            89438004737668041
            14107061265552512458
            15437026767517145468
        ]

        """
        k0 = seed
        k1 = seed_1 if seed_1 is not None else seed
        k2 = seed_2 if seed_2 is not None else seed
        k3 = seed_3 if seed_3 is not None else seed
        return wrap_s(self._s.hash(k0, k1, k2, k3))

    def reinterpret(self, signed: bool = True) -> Series:
        """
        Reinterpret the underlying bits as a signed/unsigned integer.

        This operation is only allowed for 64bit integers. For lower bits integers,
        you can safely use that cast operation.

        Parameters
        ----------
        signed
            If True, reinterpret as `pl.Int64`. Otherwise, reinterpret as `pl.UInt64`.

        """
        return wrap_s(self._s.reinterpret(signed))

    def interpolate(self) -> Series:
        """
        Interpolate intermediate values. The interpolation method is linear.

        Examples
        --------
        >>> s = pl.Series("a", [1, 2, None, None, 5])
        >>> s.interpolate()
        shape: (5,)
        Series: 'a' [i64]
        [
            1
            2
            3
            4
            5
        ]

        """
        return wrap_s(self._s.interpolate())

    def abs(self) -> Series:
        """Compute absolute values."""
        return wrap_s(self._s.abs())

    def rank(self, method: RankMethod = "average", reverse: bool = False) -> Series:
        """
        Assign ranks to data, dealing with ties appropriately.

        Parameters
        ----------
        method : {'average', 'min', 'max', 'dense', 'ordinal', 'random'}
            The method used to assign ranks to tied elements.
            The following methods are available (default is 'average'):

            - 'average' : The average of the ranks that would have been assigned to
              all the tied values is assigned to each value.
            - 'min' : The minimum of the ranks that would have been assigned to all
              the tied values is assigned to each value. (This is also referred to
              as "competition" ranking.)
            - 'max' : The maximum of the ranks that would have been assigned to all
              the tied values is assigned to each value.
            - 'dense' : Like 'min', but the rank of the next highest element is
              assigned the rank immediately after those assigned to the tied
              elements.
            - 'ordinal' : All values are given a distinct rank, corresponding to
              the order that the values occur in the Series.
            - 'random' : Like 'ordinal', but the rank for ties is not dependent
              on the order that the values occur in the Series.
        reverse
            Reverse the operation.

        Examples
        --------
        The 'average' method:

        >>> s = pl.Series("a", [3, 6, 1, 1, 6])
        >>> s.rank()
        shape: (5,)
        Series: 'a' [f32]
        [
            3.0
            4.5
            1.5
            1.5
            4.5
        ]

        The 'ordinal' method:

        >>> s = pl.Series("a", [3, 6, 1, 1, 6])
        >>> s.rank("ordinal")
        shape: (5,)
        Series: 'a' [u32]
        [
            3
            4
            1
            2
            5
        ]

        """
        return wrap_s(self._s.rank(method, reverse))

    def diff(self, n: int = 1, null_behavior: NullBehavior = "ignore") -> Series:
        """
        Calculate the n-th discrete difference.

        Parameters
        ----------
        n
            Number of slots to shift.
        null_behavior : {'ignore', 'drop'}
            How to handle null values.

        """
        return wrap_s(self._s.diff(n, null_behavior))

    def pct_change(self, n: int = 1) -> Series:
        """
        Percentage change (as fraction) between current element and most-recent
        non-null element at least n period(s) before the current element.

        Computes the change from the previous row by default.

        Parameters
        ----------
        n
            periods to shift for forming percent change.

        >>> pl.Series(range(10)).pct_change()
        shape: (10,)
        Series: '' [f64]
        [
            null
            inf
            1.0
            0.5
            0.333333
            0.25
            0.2
            0.166667
            0.142857
            0.125
        ]

        >>> pl.Series([1, 2, 4, 8, 16, 32, 64, 128, 256, 512]).pct_change(2)
        shape: (10,)
        Series: '' [f64]
        [
            null
            null
            3.0
            3.0
            3.0
            3.0
            3.0
            3.0
            3.0
            3.0
        ]

        """
        return self.to_frame().select(pli.col(self.name).pct_change(n)).to_series()

    def skew(self, bias: bool = True) -> float | None:
        r"""
        Compute the sample skewness of a data set.

        For normally distributed data, the skewness should be about zero. For
        unimodal continuous distributions, a skewness value greater than zero means
        that there is more weight in the right tail of the distribution. The
        function `skewtest` can be used to determine if the skewness value
        is close enough to zero, statistically speaking.


        See scipy.stats for more information.

        Parameters
        ----------
        bias : bool, optional
            If False, then the calculations are corrected for statistical bias.

        Notes
        -----
        The sample skewness is computed as the Fisher-Pearson coefficient
        of skewness, i.e.

        .. math:: g_1=\frac{m_3}{m_2^{3/2}}

        where

        .. math:: m_i=\frac{1}{N}\sum_{n=1}^N(x[n]-\bar{x})^i

        is the biased sample :math:`i\texttt{th}` central moment, and
        :math:`\bar{x}` is
        the sample mean.  If ``bias`` is False, the calculations are
        corrected for bias and the value computed is the adjusted
        Fisher-Pearson standardized moment coefficient, i.e.

        .. math::
            G_1 = \frac{k_3}{k_2^{3/2}} = \frac{\sqrt{N(N-1)}}{N-2}\frac{m_3}{m_2^{3/2}}

        """
        return self._s.skew(bias)

    def kurtosis(self, fisher: bool = True, bias: bool = True) -> float | None:
        """
        Compute the kurtosis (Fisher or Pearson) of a dataset.

        Kurtosis is the fourth central moment divided by the square of the
        variance. If Fisher's definition is used, then 3.0 is subtracted from
        the result to give 0.0 for a normal distribution.
        If bias is False then the kurtosis is calculated using k statistics to
        eliminate bias coming from biased moment estimators

        See scipy.stats for more information

        Parameters
        ----------
        fisher : bool, optional
            If True, Fisher's definition is used (normal ==> 0.0). If False,
            Pearson's definition is used (normal ==> 3.0).
        bias : bool, optional
            If False, then the calculations are corrected for statistical bias.

        """
        return self._s.kurtosis(fisher, bias)

    def clip(self, min_val: int | float, max_val: int | float) -> Series:
        """
        Clip (limit) the values in an array to any value that fits in 64 floating point
        range.

        Only works for the following dtypes: {Int32, Int64, Float32, Float64, UInt32}.

        If you want to clip other dtypes, consider writing a "when, then, otherwise"
        expression. See :func:`when` for more information.

        Parameters
        ----------
        min_val
            Minimum value.
        max_val
            Maximum value.

        Examples
        --------
        >>> s = pl.Series("foo", [-50, 5, None, 50])
        >>> s.clip(1, 10)
        shape: (4,)
        Series: 'foo' [i64]
        [
            1
            5
            null
            10
        ]

        """
        return self.to_frame().select(pli.col(self.name).clip(min_val, max_val))[
            self.name
        ]

    def reshape(self, dims: tuple[int, ...]) -> Series:
        """
        Reshape this Series to a flat series, shape: (len,)
        or a List series, shape: (rows, cols)

        if a -1 is used in any of the dimensions, that dimension is inferred.

        Parameters
        ----------
        dims
            Tuple of the dimension sizes

        Returns
        -------
        Series

        """
        return wrap_s(self._s.reshape(dims))

    def shuffle(self, seed: int = 0) -> Series:
        """
        Shuffle the contents of this Series.

        Parameters
        ----------
        seed
            Seed initialization

        """
        return wrap_s(self._s.shuffle(seed))

    def ewm_mean(
        self,
        com: float | None = None,
        span: float | None = None,
        half_life: float | None = None,
        alpha: float | None = None,
        adjust: bool = True,
        min_periods: int = 1,
    ) -> Series:
        r"""
        Exponentially-weighted moving average.

        Parameters
        ----------
        com
            Specify decay in terms of center of mass, :math:`\gamma`, with

                .. math::
                    \alpha = \frac{1}{1 + \gamma} \; \forall \; \gamma \geq 0
        span
            Specify decay in terms of span, :math:`\theta`, with

                .. math::
                    \alpha = \frac{2}{\theta + 1} \; \forall \; \theta \geq 1
        half_life
            Specify decay in terms of half-life, :math:`\lambda`, with

                .. math::
                    \alpha = 1 - \exp \left\{ \frac{ -\ln(2) }{ \lambda } \right\} \;
                    \forall \; \lambda > 0
        alpha
            Specify smoothing factor alpha directly, :math:`0 < \alpha < 1`.
        adjust
            Divide by decaying adjustment factor in beginning periods to account for
            imbalance in relative weightings

                - When ``adjust=True`` the EW function is calculated
                  using weights :math:`w_i = (1 - \alpha)^i`
                - When ``adjust=False`` the EW function is calculated
                  recursively by

                  .. math::
                    y_0 &= x_0 \\
                    y_t &= (1 - \alpha)y_{t - 1} + \alpha x_t
        min_periods
            Minimum number of observations in window required to have a value
            (otherwise result is null).

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).ewm_mean(
                    com, span, half_life, alpha, adjust, min_periods
                )
            )
            .to_series()
        )

    def ewm_std(
        self,
        com: float | None = None,
        span: float | None = None,
        half_life: float | None = None,
        alpha: float | None = None,
        adjust: bool = True,
        min_periods: int = 1,
    ) -> Series:
        r"""
        Exponentially-weighted moving standard deviation.

        Parameters
        ----------
        com
            Specify decay in terms of center of mass, :math:`\gamma`, with

                .. math::
                    \alpha = \frac{1}{1 + \gamma} \; \forall \; \gamma \geq 0
        span
            Specify decay in terms of span, :math:`\theta`, with

                .. math::
                    \alpha = \frac{2}{\theta + 1} \; \forall \; \theta \geq 1
        half_life
            Specify decay in terms of half-life, :math:`\lambda`, with

                .. math::
                    \alpha = 1 - \exp \left\{ \frac{ -\ln(2) }{ \lambda } \right\} \;
                    \forall \; \lambda > 0
        alpha
            Specify smoothing factor alpha directly, :math:`0 < \alpha < 1`.
        adjust
            Divide by decaying adjustment factor in beginning periods to account for
            imbalance in relative weightings

                - When ``adjust=True`` the EW function is calculated
                  using weights :math:`w_i = (1 - \alpha)^i`
                - When ``adjust=False`` the EW function is calculated
                  recursively by

                  .. math::
                    y_0 &= x_0 \\
                    y_t &= (1 - \alpha)y_{t - 1} + \alpha x_t
        min_periods
            Minimum number of observations in window required to have a value
            (otherwise result is null).

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).ewm_std(
                    com, span, half_life, alpha, adjust, min_periods
                )
            )
            .to_series()
        )

    def ewm_var(
        self,
        com: float | None = None,
        span: float | None = None,
        half_life: float | None = None,
        alpha: float | None = None,
        adjust: bool = True,
        min_periods: int = 1,
    ) -> Series:
        r"""
        Exponentially-weighted moving variance.

        Parameters
        ----------
        com
            Specify decay in terms of center of mass, :math:`\gamma`, with

                .. math::
                    \alpha = \frac{1}{1 + \gamma} \; \forall \; \gamma \geq 0
        span
            Specify decay in terms of span, :math:`\theta`, with

                .. math::
                    \alpha = \frac{2}{\theta + 1} \; \forall \; \theta \geq 1
        half_life
            Specify decay in terms of half-life, :math:`\lambda`, with

                .. math::
                    \alpha = 1 - \exp \left\{ \frac{ -\ln(2) }{ \lambda } \right\} \;
                    \forall \; \lambda > 0
        alpha
            Specify smoothing factor alpha directly, :math:`0 < \alpha < 1`.
        adjust
            Divide by decaying adjustment factor in beginning periods to account for
            imbalance in relative weightings

                - When ``adjust=True`` the EW function is calculated
                  using weights :math:`w_i = (1 - \alpha)^i`
                - When ``adjust=False`` the EW function is calculated
                  recursively by

                  .. math::
                    y_0 &= x_0 \\
                    y_t &= (1 - \alpha)y_{t - 1} + \alpha x_t
        min_periods
            Minimum number of observations in window required to have a value
            (otherwise result is null).

        """
        return (
            self.to_frame()
            .select(
                pli.col(self.name).ewm_var(
                    com, span, half_life, alpha, adjust, min_periods
                )
            )
            .to_series()
        )

    def extend_constant(self, value: int | float | str | bool | None, n: int) -> Series:
        """
        Extend the Series with given number of values.

        Parameters
        ----------
        value
            The value to extend the Series with. This value may be None to fill with
            nulls.
        n
            The number of values to extend.

        Examples
        --------
        >>> s = pl.Series([1, 2, 3])
        >>> s.extend_constant(99, n=2)
        shape: (5,)
        Series: '' [i64]
        [
                1
                2
                3
                99
                99
        ]

        """
        return wrap_s(self._s.extend_constant(value, n))

    def set_sorted(self, reverse: bool = False) -> Series:
        """
        Set this `Series` as `sorted` so that downstream code can use
        fast paths for sorted arrays.

        .. warning::
            This can lead to incorrect results if this `Series` is not sorted!!
            Use with care!

        Parameters
        ----------
        reverse
            If the `Series` order is reversed, e.g. descending.

        """
        return wrap_s(self._s.set_sorted(reverse))

    @property
    def time_unit(self) -> TimeUnit | None:
        """Get the time unit of underlying Datetime Series as {"ns", "us", "ms"}."""
        return self._s.time_unit()

    # Below are the namespaces defined. Do not move these up in the definition of
    # Series, as it confuses mypy between the type annotation `str` and the
    # namespace `str`

    @property
    def dt(self) -> DateTimeNameSpace:
        """Create an object namespace of all datetime related methods."""
        return DateTimeNameSpace(self)

    @property
    def arr(self) -> ListNameSpace:
        """Create an object namespace of all list related methods."""
        return ListNameSpace(self)

    @property
    def str(self) -> StringNameSpace:
        """Create an object namespace of all string related methods."""
        return StringNameSpace(self)

    @property
    def cat(self) -> CatNameSpace:
        """Create an object namespace of all categorical related methods."""
        return CatNameSpace(self)

    @property
    def struct(self) -> StructNameSpace:
        """Create an object namespace of all struct related methods."""
        return StructNameSpace(self)


class SeriesIter:
    """Utility class that allows slow iteration over a `Series`."""

    def __init__(self, length: int, s: Series):
        self.len = length
        self.i = 0
        self.s = s

    def __iter__(self) -> SeriesIter:
        return self

    def __next__(self) -> Any:
        if self.i < self.len:
            i = self.i
            self.i += 1
            return self.s[i]
        else:
            raise StopIteration
