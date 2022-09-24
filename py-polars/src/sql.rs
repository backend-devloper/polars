use polars_sql::SQLContext;
use pyo3::prelude::*;

use crate::{PyLazyFrame, PyPolarsErr};

#[pyclass]
#[repr(transparent)]
#[derive(Clone)]
pub struct PySQLContext {
    pub context: SQLContext,
}

#[pymethods]
#[allow(
    clippy::wrong_self_convention,
    clippy::should_implement_trait,
    clippy::len_without_is_empty
)]
impl PySQLContext {
    #[staticmethod]
    #[allow(clippy::new_without_default)]
    pub fn new() -> PySQLContext {
        PySQLContext {
            context: SQLContext::new(),
        }
    }

    pub fn register(&mut self, name: &str, lf: PyLazyFrame) {
        self.context.register(name, lf.ldf)
    }

    pub fn execute(&self, query: &str) -> PyResult<PyLazyFrame> {
        Ok(self
            .context
            .execute(query)
            .map_err(PyPolarsErr::from)?
            .into())
    }
}
