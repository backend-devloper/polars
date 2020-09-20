use crate::{dataframe::PyDataFrame, series::PySeries};
use pyo3::prelude::*;

pub mod dataframe;
pub mod error;
pub mod npy;
pub mod series;

#[pymodule]
fn pypolars(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PySeries>().unwrap();
    m.add_class::<PyDataFrame>().unwrap();
    Ok(())
}
