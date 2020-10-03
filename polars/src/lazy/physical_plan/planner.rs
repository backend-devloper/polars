use crate::{lazy::prelude::*, prelude::*};
use std::rc::Rc;

pub struct DefaultPlanner {}
impl Default for DefaultPlanner {
    fn default() -> Self {
        Self {}
    }
}

impl PhysicalPlanner for DefaultPlanner {
    fn create_physical_plan(&self, logical_plan: &LogicalPlan) -> Result<Rc<dyn Executor>> {
        self.create_initial_physical_plan(logical_plan)
    }
}

impl DefaultPlanner {
    pub fn create_initial_physical_plan(
        &self,
        logical_plan: &LogicalPlan,
    ) -> Result<Rc<dyn Executor>> {
        match logical_plan {
            LogicalPlan::Filter { input, predicate } => {
                let input = self.create_initial_physical_plan(input)?;
                let predicate = self.create_physical_expr(predicate)?;
                Ok(Rc::new(FilterExec::new(predicate, input)))
            }
            LogicalPlan::CsvScan {
                path,
                schema,
                has_header,
                delimiter,
            } => Ok(Rc::new(CsvExec::new(
                path.clone(),
                schema.clone(),
                *has_header,
                *delimiter,
            ))),
            LogicalPlan::Projection { expr, input } => {
                let input = self.create_initial_physical_plan(input)?;
                let phys_expr = expr
                    .iter()
                    .map(|expr| self.create_physical_expr(expr))
                    .collect::<Result<Vec<_>>>()?;
                Ok(Rc::new(PipeExec::new("projection", input, phys_expr)))
            }
            LogicalPlan::DataFrameScan { df } => Ok(Rc::new(DataFrameExec::new(df.clone()))),
            LogicalPlan::Sort { input, expr } => {
                let input = self.create_initial_physical_plan(input)?;
                let phys_expr = expr
                    .iter()
                    .map(|e| self.create_physical_expr(e))
                    .collect::<Result<Vec<_>>>()?;
                Ok(Rc::new(PipeExec::new("sort", input, phys_expr)))
            }
        }
    }

    // todo! add schema and ctxt
    pub fn create_physical_expr(&self, expr: &Expr) -> Result<Rc<dyn PhysicalExpr>> {
        match expr {
            Expr::Literal(value) => Ok(Rc::new(LiteralExpr::new(value.clone()))),
            Expr::BinaryExpr { left, op, right } => {
                let lhs = self.create_physical_expr(left)?;
                let rhs = self.create_physical_expr(right)?;
                Ok(Rc::new(BinaryExpr::new(lhs.clone(), *op, rhs.clone())))
            }
            Expr::Column(column) => Ok(Rc::new(ColumnExpr::new(column.clone()))),
            Expr::Sort { expr, reverse } => {
                let phys_expr = self.create_physical_expr(expr)?;
                Ok(Rc::new(SortExpr::new(phys_expr, *reverse)))
            }
            Expr::Not(expr) => {
                let phys_expr = self.create_physical_expr(expr)?;
                Ok(Rc::new(NotExpr::new(phys_expr)))
            }
            Expr::Alias(expr, name) => {
                let phys_expr = self.create_physical_expr(expr)?;
                Ok(Rc::new(AliasExpr::new(phys_expr, name.clone())))
            }
            Expr::IsNull(expr) => {
                let phys_expr = self.create_physical_expr(expr)?;
                Ok(Rc::new(IsNullExpr::new(phys_expr)))
            }
            Expr::IsNotNull(expr) => {
                let phys_expr = self.create_physical_expr(expr)?;
                Ok(Rc::new(IsNotNullExpr::new(phys_expr)))
            }
        }
    }
}
