//! Everything you need to get started with Polars.
pub use crate::{
    chunked_array::{
        arithmetic::Pow,
        builder::{
            AlignedAlloc, AlignedVec, LargListBuilderTrait, LargeListPrimitiveChunkedBuilder,
            LargeListUtf8ChunkedBuilder, NewChunkedArray, PrimitiveChunkedBuilder,
            Utf8ChunkedBuilder,
        },
        chunkops::ChunkOps,
        comparison::NumComp,
        iterator::{IntoNoNullIterator, NumericChunkIterDispatch},
        ops::{
            ChunkAgg, ChunkApply, ChunkCast, ChunkCompare, ChunkFilter, ChunkFull, ChunkReverse,
            ChunkShift, ChunkSort, ChunkUnique,
        },
        take::{
            AsTakeIndex, IntoTakeRandom, NumTakeRandomChunked, NumTakeRandomCont, Take, TakeRandom,
        },
        ChunkedArray, Downcast,
    },
    datatypes,
    datatypes::*,
    error::{PolarsError, Result},
    frame::{
        ser::{
            csv::{CsvReader, CsvWriter},
            ipc::{IPCReader, IPCWriter},
            json::JsonReader,
            SerReader, SerWriter,
        },
        DataFrame,
    },
    series::{arithmetic::LhsNumOps, NamedFrom, Series},
    testing::*,
};
pub use arrow::datatypes::{ArrowPrimitiveType, Field, Schema};

#[cfg(feature = "temporal")]
pub use crate::chunked_array::temporal::{
    AsNaiveDateTime, AsNaiveTime, FromNaiveDate, FromNaiveDateTime, FromNaiveTime,
};

#[cfg(test)]
pub(crate) fn create_df() -> DataFrame {
    let s0 = Series::new("days", [0, 1, 2, 3, 4].as_ref());
    let s1 = Series::new("temp", [22.1, 19.9, 7., 2., 3.].as_ref());
    DataFrame::new(vec![s0, s1]).unwrap()
}
