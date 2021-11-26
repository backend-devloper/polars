import warnings
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Type, Union

import numpy as np

from polars import internals as pli
from polars.datatypes import (
    DataType,
    Date,
    Datetime,
    Float32,
    py_type_to_arrow_type,
    py_type_to_dtype,
)
from polars.datatypes_constructor import (
    numpy_type_to_constructor,
    polars_type_to_constructor,
    py_type_to_constructor,
)

try:
    from polars.polars import PyDataFrame, PySeries

    _DOCUMENTING = False
except ImportError:  # pragma: no cover
    _DOCUMENTING = True

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd
    import pyarrow as pa

    _PYARROW_AVAILABLE = True
else:
    try:
        import pyarrow as pa

        _PYARROW_AVAILABLE = True
    except ImportError:  # pragma: no cover
        _PYARROW_AVAILABLE = False

################################
# Series constructor interface #
################################


def series_to_pyseries(
    name: str,
    values: "pli.Series",
) -> "PySeries":
    """
    Construct a PySeries from a Polars Series.
    """
    values.rename(name, in_place=True)
    return values.inner()


def arrow_to_pyseries(name: str, values: "pa.Array") -> "PySeries":
    """
    Construct a PySeries from an Arrow array.
    """
    array = coerce_arrow(values)
    return PySeries.from_arrow(name, array)


def numpy_to_pyseries(
    name: str, values: np.ndarray, strict: bool = True, nan_to_null: bool = False
) -> "PySeries":
    """
    Construct a PySeries from a numpy array.
    """
    if not values.flags["C_CONTIGUOUS"]:
        values = np.array(values)

    if len(values.shape) == 1:
        dtype = values.dtype.type
        constructor = numpy_type_to_constructor(dtype)
        if dtype == np.float32 or dtype == np.float64:
            return constructor(name, values, nan_to_null)
        else:
            return constructor(name, values, strict)
    else:
        return PySeries.new_object(name, values, strict)


def _get_first_non_none(values: Sequence[Optional[Any]]) -> Any:
    """
    Return the first value from a sequence that isn't None.

    If sequence doesn't contain non-None values, return None.
    """
    return next((v for v in values if v is not None), None)


def sequence_to_pyseries(
    name: str,
    values: Sequence[Any],
    dtype: Optional[Type[DataType]] = None,
    strict: bool = True,
) -> "PySeries":
    """
    Construct a PySeries from a sequence.
    """
    # Empty sequence defaults to Float32 type
    if not values and dtype is None:
        dtype = Float32

    if dtype is not None:
        constructor = polars_type_to_constructor(dtype)
        pyseries = constructor(name, values, strict)
        if dtype == Date:
            pyseries = pyseries.cast(str(Date), True)
        elif dtype == Datetime:
            pyseries = pyseries.cast(str(Datetime), True)
        return pyseries

    else:
        value = _get_first_non_none(values)
        dtype_ = type(value) if value is not None else float

        if dtype_ == date or dtype_ == datetime:
            if not _PYARROW_AVAILABLE:  # pragma: no cover
                raise ImportError(
                    "'pyarrow' is required for converting a Sequence of date or datetime values to a PySeries."
                )
            return arrow_to_pyseries(name, pa.array(values))

        elif dtype_ == list or dtype_ == tuple or dtype_ == pli.Series:
            nested_value = _get_first_non_none(value)
            nested_dtype = type(nested_value) if value is not None else float

            if not _PYARROW_AVAILABLE:  # pragma: no cover
                dtype = py_type_to_dtype(nested_dtype)
                return PySeries.new_list(name, values, dtype)

            try:
                nested_arrow_dtype = py_type_to_arrow_type(nested_dtype)
            except ValueError as e:
                raise ValueError(
                    f"Cannot construct Series from sequence of {nested_dtype}."
                ) from e

            try:
                arrow_values = pa.array(values, pa.large_list(nested_arrow_dtype))
                return arrow_to_pyseries(name, arrow_values)
            # failure expected for mixed sequences like `[[12], "foo", 9]`
            except pa.lib.ArrowInvalid:
                return PySeries.new_object(name, values, strict)

        else:
            constructor = py_type_to_constructor(dtype_)
            return constructor(name, values, strict)


def _pandas_series_to_arrow(
    values: Union["pd.Series", "pd.DatetimeIndex"],
    nan_to_none: bool = True,
    min_len: Optional[int] = None,
) -> "pa.Array":
    """
    Convert a pandas Series to an Arrow Array.

    Parameters
    ----------
    values
        Series to convert to arrow
    nan_to_none
        Interpret `NaN` as missing values
    min_len
        in case of null values, this length will be used to create a dummy f64 array (with all values set to null)

    Returns
    -------
    """
    dtype = values.dtype
    if dtype == "datetime64[ns]":
        # We first cast to ms because that's the unit of Datetime,
        # Then we cast to via int64 to datetime. Casting directly to Datetime lead to
        # loss of time information https://github.com/pola-rs/polars/issues/476
        arr = pa.array(
            np.array(values.values, dtype="datetime64[ms]"), from_pandas=nan_to_none
        )
        arr = pa.compute.cast(arr, pa.int64())
        return pa.compute.cast(arr, pa.timestamp("ms"))
    elif dtype == "object" and len(values) > 0:
        if isinstance(values.iloc[0], str):
            return pa.array(values, pa.large_utf8(), from_pandas=nan_to_none)

        # array is null array, we set to a float64 array
        if values.iloc[0] is None and min_len is not None:
            return pa.nulls(min_len, pa.float64())
        else:
            return pa.array(values, from_pandas=nan_to_none)
    else:
        return pa.array(values, from_pandas=nan_to_none)


def pandas_to_pyseries(
    name: str, values: Union["pd.Series", "pd.DatetimeIndex"], nan_to_none: bool = True
) -> "PySeries":
    """
    Construct a PySeries from a pandas Series or DatetimeIndex.
    """
    if not _PYARROW_AVAILABLE:  # pragma: no cover
        raise ImportError(
            "'pyarrow' is required when constructing a PySeries from a pandas Series."
        )
    # TODO: Change `if not name` to `if name is not None` once name is Optional[str]
    if not name and values.name is not None:
        name = str(values.name)
    return arrow_to_pyseries(
        name, _pandas_series_to_arrow(values, nan_to_none=nan_to_none)
    )


###################################
# DataFrame constructor interface #
###################################


def _handle_columns_arg(
    data: List["PySeries"],
    columns: Optional[Sequence[str]] = None,
) -> List["PySeries"]:
    """
    Rename data according to columns argument.
    """
    if columns is None:
        return data
    else:
        if not data:
            return [pli.Series(c, None).inner() for c in columns]
        elif len(data) == len(columns):
            for i, c in enumerate(columns):
                data[i].rename(c)
            return data
        else:
            raise ValueError("Dimensions of columns arg must match data dimensions.")


def dict_to_pydf(
    data: Dict[str, Sequence[Any]],
    columns: Optional[Sequence[str]] = None,
) -> "PyDataFrame":
    """
    Construct a PyDataFrame from a dictionary of sequences.
    """
    data_series = [pli.Series(name, values).inner() for name, values in data.items()]
    data_series = _handle_columns_arg(data_series, columns=columns)
    return PyDataFrame(data_series)


def numpy_to_pydf(
    data: np.ndarray,
    columns: Optional[Sequence[str]] = None,
    orient: Optional[str] = None,
) -> "PyDataFrame":
    """
    Construct a PyDataFrame from a numpy ndarray.
    """
    shape = data.shape

    if shape == (0,):
        data_series = []

    elif len(shape) == 1:
        s = pli.Series("column_0", data).inner()
        data_series = [s]

    elif len(shape) == 2:
        # Infer orientation
        if orient is None:
            warnings.warn(
                "Default orientation for constructing DataFrame from numpy "
                'array will change from "row" to "column" in a future version. '
                "Specify orientation explicitly to silence this warning.",
                DeprecationWarning,
                stacklevel=2,
            )
            orient = "row"
        # Exchange if-block above for block below when removing warning
        # if orientation is None and columns is not None:
        #     orientation = "col" if len(columns) == shape[0] else "row"

        if orient == "row":
            data_series = [
                pli.Series(f"column_{i}", data[:, i]).inner() for i in range(shape[1])
            ]
        else:
            data_series = [
                pli.Series(f"column_{i}", data[i]).inner() for i in range(shape[0])
            ]
    else:
        raise ValueError("A numpy array should not have more than two dimensions.")

    data_series = _handle_columns_arg(data_series, columns=columns)

    return PyDataFrame(data_series)


def sequence_to_pydf(
    data: Sequence[Any],
    columns: Optional[Sequence[str]] = None,
    orient: Optional[str] = None,
) -> "PyDataFrame":
    """
    Construct a PyDataFrame from a sequence.
    """
    data_series: List["PySeries"]
    if len(data) == 0:
        data_series = []

    elif isinstance(data[0], pli.Series):
        data_series = []
        for i, s in enumerate(data):
            if not s.name:  # TODO: Replace by `if s.name is None` once allowed
                s.rename(f"column_{i}", in_place=True)
            data_series.append(s.inner())

    elif isinstance(data[0], dict):
        pydf = PyDataFrame.read_dicts(data)
        if columns is not None:
            pydf.set_column_names(columns)
        return pydf

    elif isinstance(data[0], Sequence) and not isinstance(data[0], str):
        # Infer orientation
        if orient is None and columns is not None:
            orient = "col" if len(columns) == len(data) else "row"

        if orient == "row":
            pydf = PyDataFrame.read_rows(data)
            if columns is not None:
                pydf.set_column_names(columns)
            return pydf
        else:
            data_series = [
                pli.Series(f"column_{i}", data[i]).inner() for i in range(len(data))
            ]

    else:
        s = pli.Series("column_0", data).inner()
        data_series = [s]

    data_series = _handle_columns_arg(data_series, columns=columns)
    return PyDataFrame(data_series)


def arrow_to_pydf(
    data: "pa.Table", columns: Optional[Sequence[str]] = None, rechunk: bool = True
) -> "PyDataFrame":
    """
    Construct a PyDataFrame from an Arrow Table.
    """
    if not _PYARROW_AVAILABLE:  # pragma: no cover
        raise ImportError(
            "'pyarrow' is required when constructing a PyDataFrame from an Arrow Table."
        )
    if columns is not None:
        try:
            data = data.rename_columns(columns)
        except pa.lib.ArrowInvalid as e:
            raise ValueError(
                "Dimensions of columns arg must match data dimensions."
            ) from e

    data_dict = {}
    for i, column in enumerate(data):
        # extract the name before casting
        if column._name is None:
            name = f"column_{i}"
        else:
            name = column._name

        column = coerce_arrow(column)
        data_dict[name] = column

    batches = pa.table(data_dict).to_batches()
    pydf = PyDataFrame.from_arrow_record_batches(batches)
    if rechunk:
        pydf = pydf.rechunk()
    return pydf


def series_to_pydf(
    data: "pli.Series",
    columns: Optional[Sequence[str]] = None,
) -> "PyDataFrame":
    """
    Construct a PyDataFrame from a Polars Series.
    """
    data_series = [data.inner()]
    data_series = _handle_columns_arg(data_series, columns=columns)
    return PyDataFrame(data_series)


def pandas_to_pydf(
    data: "pd.DataFrame",
    columns: Optional[Sequence[str]] = None,
    rechunk: bool = True,
    nan_to_none: bool = True,
) -> "PyDataFrame":
    """
    Construct a PyDataFrame from a pandas DataFrame.
    """
    if not _PYARROW_AVAILABLE:  # pragma: no cover
        raise ImportError(
            "'pyarrow' is required when constructing a PyDataFrame from a pandas DataFrame."
        )
    len = data.shape[0]
    arrow_dict = {
        str(col): _pandas_series_to_arrow(
            data[col], nan_to_none=nan_to_none, min_len=len
        )
        for col in data.columns
    }
    arrow_table = pa.table(arrow_dict)
    return arrow_to_pydf(arrow_table, columns=columns, rechunk=rechunk)


def coerce_arrow(array: "pa.Array") -> "pa.Array":
    # also coerces timezone to naive representation
    # units are accounted for by pyarrow
    if isinstance(array, pa.TimestampArray):
        if array.type.tz is not None:
            warnings.warn(
                "Conversion of timezone aware to naive datetimes. TZ information may be lost",
            )
        ts_ms = pa.compute.cast(array, pa.timestamp("ms"), safe=False)
        ms = pa.compute.cast(ts_ms, pa.int64())
        del ts_ms
        array = pa.compute.cast(ms, pa.timestamp("ms"))
        del ms
    # note: Decimal256 could not be cast to float
    elif isinstance(array.type, pa.Decimal128Type):
        array = pa.compute.cast(array, pa.float64())

    if hasattr(array, "num_chunks") and array.num_chunks > 1:
        # we have to coerce before combining chunks, because pyarrow panics if
        # offsets overflow
        if pa.types.is_string(array.type):
            array = pa.compute.cast(array, pa.large_utf8())
        elif pa.types.is_list(array.type):
            # pyarrow does not seem to support casting from list to largelist
            # so we use convert to large list ourselves and do the re-alloc on polars/arrow side
            chunks = []
            for arr in array.iterchunks():
                chunks.append(pli.Series._from_arrow("", arr).to_arrow())
            array = pa.chunked_array(chunks)

        array = array.combine_chunks()
    return array
