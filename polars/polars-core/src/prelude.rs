//! Everything you need to get started with Polars.
pub use crate::{
    chunked_array::{
        arithmetic::Pow,
        builder::{
            BooleanChunkedBuilder, ChunkedBuilder, ListBooleanChunkedBuilder, ListBuilderTrait,
            ListPrimitiveChunkedBuilder, ListUtf8ChunkedBuilder, NewChunkedArray,
            PrimitiveChunkedBuilder, Utf8ChunkedBuilder,
        },
        comparison::{CompToSeries, NumComp},
        iterator::{IntoNoNullIterator, PolarsIterator},
        ops::{
            aggregate::*,
            chunkops::ChunkOps,
            take::{AsTakeIndex, IntoTakeRandom, NumTakeRandomChunked, NumTakeRandomCont},
            window::InitFold,
            *,
        },
        ChunkedArray, Downcast, NoNull,
    },
    datatypes,
    datatypes::*,
    error::{PolarsError, Result},
    frame::{group_by::VecHash, hash_join::JoinType, DataFrame},
    series::{
        arithmetic::{LhsNumOps, NumOpsDispatch},
        IntoSeries, NamedFrom, Series, SeriesTrait,
    },
    testing::*,
};
pub use arrow::datatypes::{ArrowPrimitiveType, Field as ArrowField, Schema as ArrowSchema};
pub(crate) use polars_arrow::array::*;
pub use polars_arrow::vec::AlignedVec;
pub use std::sync::Arc;

#[cfg(feature = "temporal")]
pub use crate::chunked_array::temporal::conversion::*;

#[macro_export]
macro_rules! as_result {
    ($block:block) => {{
        let res: Result<_> = $block;
        res
    }};
}
