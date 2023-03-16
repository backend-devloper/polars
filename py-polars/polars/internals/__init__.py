"""
Core Polars functionality.

The modules within `polars.internals` are interdependent. To prevent cyclical imports,
they all import from each other via this __init__ file using
`from polars import internals as pli`. The imports below are being shared across this
module.
"""
from polars.dataframe import DataFrame, wrap_df
from polars.expr import (
    Expr,
    expr_to_lit_or_expr,
    selection_to_pyexpr_list,
    wrap_expr,
)
from polars.functions.eager import concat, date_range
from polars.functions.lazy import (
    all,
    arange,
    arg_sort_by,
    arg_where,
    argsort_by,
    coalesce,
    col,
    collect_all,
    concat_list,
    count,
    element,
    format,
    from_epoch,
    lit,
    select,
    struct,
)
from polars.functions.whenthen import WhenThen, WhenThenThen, when
from polars.internals.anonymous_scan import (
    _deser_and_exec,
    _scan_ipc_fsspec,
    _scan_parquet_fsspec,
    _scan_pyarrow_dataset,
)
from polars.internals.batched import BatchedCsvReader
from polars.internals.io import (
    _is_local_file,
    _prepare_file_arg,
    _update_columns,
    read_ipc_schema,
    read_parquet_schema,
)
from polars.lazyframe import LazyFrame, wrap_ldf
from polars.series import Series, wrap_s

__all__ = [
    "DataFrame",
    "Expr",
    "LazyFrame",
    "Series",
    "all",
    "arange",
    "arg_where",
    "arg_sort_by",
    "argsort_by",
    "BatchedCsvReader",
    "coalesce",
    "col",
    "collect_all",
    "concat",
    "concat_list",
    "count",
    "date_range",
    "element",
    "expr_to_lit_or_expr",
    "format",
    "from_epoch",
    "lit",
    "read_ipc_schema",
    "read_parquet_schema",
    "select",
    "selection_to_pyexpr_list",
    "struct",
    "when",
    "wrap_df",
    "wrap_expr",
    "wrap_ldf",
    "wrap_s",
    "WhenThen",
    "WhenThenThen",
    "_deser_and_exec",
    "_is_local_file",
    "_prepare_file_arg",
    "_scan_pyarrow_dataset",
    "_scan_ipc_fsspec",
    "_scan_parquet_fsspec",
    "_update_columns",
]
