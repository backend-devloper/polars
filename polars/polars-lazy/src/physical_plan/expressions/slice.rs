use crate::physical_plan::state::ExecutionState;
use crate::prelude::*;
use polars_core::frame::groupby::GroupTuples;
use polars_core::prelude::*;
use polars_core::utils::slice_offsets;
use std::sync::Arc;

pub struct SliceExpr {
    pub(crate) input: Arc<dyn PhysicalExpr>,
    pub(crate) offset: i64,
    pub(crate) len: usize,
}

impl PhysicalExpr for SliceExpr {
    fn evaluate(&self, df: &DataFrame, state: &ExecutionState) -> Result<Series> {
        let series = self.input.evaluate(df, state)?;
        Ok(series.slice(self.offset, self.len))
    }

    fn evaluate_on_groups<'a>(
        &self,
        df: &DataFrame,
        groups: &'a GroupTuples,
        state: &ExecutionState,
    ) -> Result<AggregationContext<'a>> {
        let mut ac = self.input.evaluate_on_groups(df, groups, state)?;

        let groups = ac
            .groups
            .iter()
            .map(|(first, idx)| {
                let (offset, len) = slice_offsets(self.offset, self.len, idx.len());
                (*first, idx[offset..offset + len].to_vec())
            })
            .collect();

        ac.with_groups(groups);
        Ok(ac)
    }

    fn to_field(&self, input_schema: &Schema) -> Result<Field> {
        self.input.to_field(input_schema)
    }

    fn as_agg_expr(&self) -> Result<&dyn PhysicalAggregation> {
        Ok(self)
    }
}
impl PhysicalAggregation for SliceExpr {
    // As a final aggregation a Slice returns a list array.
    fn aggregate(
        &self,
        df: &DataFrame,
        groups: &GroupTuples,
        state: &ExecutionState,
    ) -> Result<Option<Series>> {
        let ac = self.evaluate_on_groups(df, groups, state)?;
        let s = ac.aggregated_final().into_owned();
        Ok(Some(s))
    }
}
