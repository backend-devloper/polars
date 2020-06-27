use thiserror::Error as ThisError;

#[derive(Debug, ThisError)]
pub enum PolarsError {
    #[error(transparent)]
    ArrowError(#[from] arrow::error::ArrowError),
    #[error("Invalid operation")]
    InvalidOperation,
    #[error("Chunk don't match")]
    ChunkMisMatch,
    #[error("Data types don't match")]
    DataTypeMisMatch,
    #[error("Not found")]
    NotFound,
    #[error("Lengths don't match")]
    LengthMismatch,
    #[error("{0}")]
    Other(String),
    #[error("No selection was made")]
    NoSelection,
    #[error("Out of bounds")]
    OutOfBounds,
    #[error("Not contiguous or null values")]
    NoSlice,
    #[error("Such empty...")]
    NoData,
}

pub type Result<T> = std::result::Result<T, PolarsError>;
