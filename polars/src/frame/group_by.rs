use super::hash_join::prepare_hashed_relation;
use crate::chunked_array::builder::PrimitiveChunkedBuilder;
use crate::prelude::*;
use enum_dispatch::enum_dispatch;
use num::{Num, NumCast, ToPrimitive, Zero};
use rayon::prelude::*;
use std::hash::Hash;

fn groupby<T>(a: impl Iterator<Item = T>) -> Vec<(usize, Vec<usize>)>
where
    T: Hash + Eq + Copy,
{
    let hash_tbl = prepare_hashed_relation(a);

    hash_tbl
        .into_iter()
        .map(|(_, indexes)| {
            let first = unsafe { *indexes.get_unchecked(0) };
            (first, indexes)
        })
        .collect()
}

#[enum_dispatch(Series)]
trait IntoGroupTuples {
    fn group_tuples(&self) -> Vec<(usize, Vec<usize>)> {
        unimplemented!()
    }
}

impl<T> IntoGroupTuples for ChunkedArray<T>
where
    T: PolarsIntegerType,
    T::Native: Eq + Hash,
{
    fn group_tuples(&self) -> Vec<(usize, Vec<usize>)> {
        if let Ok(slice) = self.cont_slice() {
            groupby(slice.iter())
        } else {
            groupby(self.into_iter())
        }
    }
}
impl IntoGroupTuples for BooleanChunked {
    fn group_tuples(&self) -> Vec<(usize, Vec<usize>)> {
        if self.is_optimal_aligned() {
            groupby(self.into_no_null_iter())
        } else {
            groupby(self.into_iter())
        }
    }
}

impl IntoGroupTuples for Utf8Chunked {
    fn group_tuples(&self) -> Vec<(usize, Vec<usize>)> {
        if self.is_optimal_aligned() {
            groupby(self.into_no_null_iter())
        } else {
            groupby(self.into_iter())
        }
    }
}

impl IntoGroupTuples for Float64Chunked {}
impl IntoGroupTuples for Float32Chunked {}
impl IntoGroupTuples for LargeListChunked {}

impl DataFrame {
    /// Group DataFrame using a Series column.
    ///
    /// # Example
    ///
    /// ```
    /// use polars::prelude::*;
    /// fn groupby_sum(df: &DataFrame) -> Result<DataFrame> {
    ///     df.groupby("column_name")?
    ///     .select("agg_column_name")
    ///     .sum()
    /// }
    /// ```
    pub fn groupby(&self, by: &str) -> Result<GroupBy> {
        let groups = if let Some(s) = self.column(by) {
            s.group_tuples()
        } else {
            return Err(PolarsError::NotFound);
        };

        Ok(GroupBy {
            df: self,
            by: by.to_string(),
            groups,
            selection: None,
        })
    }
}

#[derive(Debug, Clone)]
pub struct GroupBy<'a> {
    df: &'a DataFrame,
    pub by: String,
    // [first idx, [other idx]]
    groups: Vec<(usize, Vec<usize>)>,
    selection: Option<String>,
}

#[enum_dispatch(Series)]
trait NumericAggSync {
    fn agg_mean(&self, _groups: &Vec<(usize, Vec<usize>)>) -> Series {
        unimplemented!()
    }
    fn agg_min(&self, _groups: &Vec<(usize, Vec<usize>)>) -> Series {
        unimplemented!()
    }
    fn agg_max(&self, _groups: &Vec<(usize, Vec<usize>)>) -> Series {
        unimplemented!()
    }
    fn agg_sum(&self, _groups: &Vec<(usize, Vec<usize>)>) -> Series {
        unimplemented!()
    }
}

impl NumericAggSync for BooleanChunked {}
impl NumericAggSync for Utf8Chunked {}
impl NumericAggSync for LargeListChunked {}

impl<T> NumericAggSync for ChunkedArray<T>
where
    T: PolarsNumericType + Sync,
    T::Native: std::ops::Add<Output = T::Native> + Num + NumCast,
{
    fn agg_mean(&self, groups: &Vec<(usize, Vec<usize>)>) -> Series {
        Series::Float64(
            groups
                .par_iter()
                .map(|(_first, idx)| {
                    // Fast path
                    if let Ok(slice) = self.cont_slice() {
                        let mut sum = 0.;
                        for i in idx {
                            sum = sum + slice[*i].to_f64().unwrap()
                        }
                        Some(sum / idx.len() as f64)
                    } else {
                        let take = unsafe {
                            self.take_unchecked(idx.into_iter().copied(), Some(self.len()))
                        };
                        let opt_sum: Option<T::Native> = take.sum();
                        opt_sum.map(|sum| sum.to_f64().unwrap() / idx.len() as f64)
                    }
                })
                .collect(),
        )
    }

    fn agg_min(&self, groups: &Vec<(usize, Vec<usize>)>) -> Series {
        groups
            .par_iter()
            .map(|(_first, idx)| {
                if let Ok(slice) = self.cont_slice() {
                    let mut min = None;
                    for i in idx {
                        let v = slice[*i];

                        min = match min {
                            Some(min) => {
                                if min < v {
                                    Some(min)
                                } else {
                                    Some(v)
                                }
                            }
                            None => Some(v),
                        };
                    }
                    min
                } else {
                    let take =
                        unsafe { self.take_unchecked(idx.into_iter().copied(), Some(self.len())) };
                    take.min()
                }
            })
            .collect::<ChunkedArray<T>>()
            .into_series()
    }

    fn agg_max(&self, groups: &Vec<(usize, Vec<usize>)>) -> Series {
        groups
            .par_iter()
            .map(|(_first, idx)| {
                if let Ok(slice) = self.cont_slice() {
                    let mut max = None;
                    for i in idx {
                        let v = slice[*i];

                        max = match max {
                            Some(max) => {
                                if max > v {
                                    Some(max)
                                } else {
                                    Some(v)
                                }
                            }
                            None => Some(v),
                        };
                    }
                    max
                } else {
                    let take =
                        unsafe { self.take_unchecked(idx.into_iter().copied(), Some(self.len())) };
                    take.max()
                }
            })
            .collect::<ChunkedArray<T>>()
            .into_series()
    }

    fn agg_sum(&self, groups: &Vec<(usize, Vec<usize>)>) -> Series {
        groups
            .par_iter()
            .map(|(_first, idx)| {
                if let Ok(slice) = self.cont_slice() {
                    let mut sum = Zero::zero();
                    for i in idx {
                        sum = sum + slice[*i]
                    }
                    Some(sum)
                } else {
                    let take =
                        unsafe { self.take_unchecked(idx.into_iter().copied(), Some(self.len())) };
                    take.sum()
                }
            })
            .collect::<ChunkedArray<T>>()
            .into_series()
    }
}

impl<'a> GroupBy<'a> {
    pub fn select(mut self, name: &str) -> Self {
        self.selection = Some(name.to_string());
        self
    }

    fn keys(&self) -> Series {
        unsafe {
            self.df.f_column(&self.by).take_iter_unchecked(
                self.groups.iter().map(|(idx, _)| *idx),
                Some(self.groups.len()),
            )
        }
    }

    fn prepare_agg(&self) -> Result<(&String, Series, &Series)> {
        let name = match &self.selection {
            Some(name) => name,
            None => return Err(PolarsError::NoSelection),
        };

        let keys = self.keys();
        let agg_col = self.df.column(name).ok_or(PolarsError::NotFound)?;
        Ok((name, keys, agg_col))
    }

    /// Aggregate grouped series and compute the mean per group.
    pub fn mean(&self) -> Result<DataFrame> {
        let (name, keys, agg_col) = self.prepare_agg()?;
        let new_name = format!["{}_mean", name];

        let mut agg = agg_col.agg_mean(&self.groups);
        agg.rename(&new_name);
        DataFrame::new(vec![keys, agg])
    }

    /// Aggregate grouped series and compute the sum per group.
    pub fn sum(&self) -> Result<DataFrame> {
        let (name, keys, agg_col) = self.prepare_agg()?;
        let new_name = format!["{}_sum", name];
        let mut agg = agg_col.agg_sum(&self.groups);
        agg.rename(&new_name);
        DataFrame::new(vec![keys, agg])
    }

    /// Aggregate grouped series and compute the minimal value per group.
    pub fn min(&self) -> Result<DataFrame> {
        let (name, keys, agg_col) = self.prepare_agg()?;
        let new_name = format!["{}_min", name];
        let mut agg = apply_method_numeric_series!(agg_col, agg_min, &self.groups);
        agg.rename(&new_name);
        DataFrame::new(vec![keys, agg])
    }

    /// Aggregate grouped series and compute the maximum value per group.
    pub fn max(&self) -> Result<DataFrame> {
        let (name, keys, agg_col) = self.prepare_agg()?;
        let new_name = format!["{}_max", name];
        let mut agg = agg_col.agg_max(&self.groups);
        agg.rename(&new_name);
        DataFrame::new(vec![keys, agg])
    }

    /// Aggregate grouped series and compute the number of values per group.
    pub fn count(&self) -> Result<DataFrame> {
        let (name, keys, agg_col) = self.prepare_agg()?;
        let new_name = format!["{}_count", name];

        let mut builder = PrimitiveChunkedBuilder::new(&new_name, self.groups.len());
        for (_first, idx) in &self.groups {
            let s =
                unsafe { agg_col.take_iter_unchecked(idx.into_iter().copied(), Some(idx.len())) };
            builder.append_value(s.len() as u32);
        }
        let ca = builder.finish();
        let agg = Series::UInt32(ca);
        DataFrame::new(vec![keys, agg])
    }
}

#[cfg(test)]
mod test {
    use crate::prelude::*;

    #[test]
    fn test_group_by() {
        let s0 = Series::new("days", ["mo", "mo", "tue", "wed", "tue"].as_ref());
        let s1 = Series::new("temp", [20, 10, 7, 9, 1].as_ref());
        let s2 = Series::new("rain", [0.2, 0.1, 0.3, 0.1, 0.01].as_ref());
        let df = DataFrame::new(vec![s0, s1, s2]).unwrap();

        println!(
            "{:?}",
            df.groupby("days").unwrap().select("temp").count().unwrap()
        );
        println!(
            "{:?}",
            df.groupby("days").unwrap().select("temp").mean().unwrap()
        );
        println!(
            "{:?}",
            df.groupby("days").unwrap().select("temp").sum().unwrap()
        );
        println!(
            "{:?}",
            df.groupby("days").unwrap().select("temp").min().unwrap()
        );
        println!(
            "{:?}",
            df.groupby("days").unwrap().select("temp").max().unwrap()
        );
    }
}
