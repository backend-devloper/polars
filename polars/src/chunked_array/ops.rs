//! Traits for miscellaneous operations on ChunkedArray
use crate::chunked_array::builder::get_large_list_builder;
use crate::prelude::*;
use crate::utils::Xob;
use arrow::compute;
use itertools::Itertools;
use num::{Num, NumCast};
use std::cmp::Ordering;
use std::ops::{Add, Div};

/// Cast `ChunkedArray<T>` to `ChunkedArray<N>`
pub trait ChunkCast {
    /// Cast `ChunkedArray<T>` to `ChunkedArray<N>`
    fn cast<N>(&self) -> Result<ChunkedArray<N>>
    where
        N: PolarsDataType;
}

/// Fastest way to do elementwise operations on a ChunkedArray<T>
pub trait ChunkApply<'a, A, B> {
    /// Apply a closure `F` elementwise.
    fn apply<F>(&'a self, f: F) -> Self
    where
        F: Fn(A) -> B + Copy;
}

/// Aggregation operations
pub trait ChunkAgg<T> {
    /// Returns `None` if the array is empty or only contains null values.
    fn sum(&self) -> Option<T>;
    /// Returns the minimum value in the array, according to the natural order.
    /// Returns an option because the array is nullable.
    fn min(&self) -> Option<T>;
    /// Returns the maximum value in the array, according to the natural order.
    /// Returns an option because the array is nullable.
    fn max(&self) -> Option<T>;

    /// Returns the mean value in the array.
    /// Returns an option because the array is nullable.
    fn mean(&self) -> Option<T>;
}

/// Compare [Series](series/series/enum.Series.html)
/// and [ChunkedArray](series/chunked_array/struct.ChunkedArray.html)'s and get a `boolean` mask that
/// can be used to filter rows.
///
/// # Example
///
/// ```
/// use polars::prelude::*;
/// fn filter_all_ones(df: &DataFrame) -> Result<DataFrame> {
///     let mask = df
///     .column("column_a")
///     .ok_or(PolarsError::NotFound)?
///     .eq(1);
///
///     df.filter(&mask)
/// }
/// ```
pub trait ChunkCompare<Rhs> {
    /// Check for equality.
    fn eq(&self, rhs: Rhs) -> BooleanChunked;

    /// Check for inequality.
    fn neq(&self, rhs: Rhs) -> BooleanChunked;

    /// Greater than comparison.
    fn gt(&self, rhs: Rhs) -> BooleanChunked;

    /// Greater than or equal comparison.
    fn gt_eq(&self, rhs: Rhs) -> BooleanChunked;

    /// Less than comparison.
    fn lt(&self, rhs: Rhs) -> BooleanChunked;

    /// Less than or equal comparison
    fn lt_eq(&self, rhs: Rhs) -> BooleanChunked;
}

/// Get unique values in a ChunkedArray<T>
pub trait ChunkUnique<T> {
    // We don't return Self to be able to use AutoRef specialization
    /// Get unique values of a ChunkedArray
    fn unique(&self) -> ChunkedArray<T>;

    /// Get first index of the unique values in a ChunkedArray.
    fn arg_unique(&self) -> Vec<usize>;
}

/// Sort operations on ChunkedArray<T>
pub trait ChunkSort<T> {
    /// Returned a sorted ChunkedArray<T>.
    fn sort(&self, reverse: bool) -> ChunkedArray<T>;

    /// Sort this array in place.
    fn sort_in_place(&mut self, reverse: bool);

    /// Retrieve the indexes needed to sort this array.
    fn argsort(&self, reverse: bool) -> Vec<usize>;
}

fn sort_partial<T: PartialOrd>(a: &Option<T>, b: &Option<T>) -> Ordering {
    match (a, b) {
        (Some(a), Some(b)) => a.partial_cmp(b).expect("could not compare"),
        (None, Some(_)) => Ordering::Less,
        (Some(_), None) => Ordering::Greater,
        (None, None) => Ordering::Equal,
    }
}

impl<T> ChunkSort<T> for ChunkedArray<T>
where
    T: PolarsNumericType,
    T::Native: std::cmp::PartialOrd,
{
    fn sort(&self, reverse: bool) -> ChunkedArray<T> {
        if reverse {
            self.into_iter()
                .sorted_by(|a, b| sort_partial(b, a))
                .collect()
        } else {
            self.into_iter()
                .sorted_by(|a, b| sort_partial(a, b))
                .collect()
        }
    }

    fn sort_in_place(&mut self, reverse: bool) {
        let sorted = self.sort(reverse);
        self.chunks = sorted.chunks;
    }

    fn argsort(&self, reverse: bool) -> Vec<usize> {
        if reverse {
            self.into_iter()
                .enumerate()
                .sorted_by(|(_idx_a, a), (_idx_b, b)| sort_partial(b, a))
                .map(|(idx, _v)| idx)
                .collect::<AlignedVec<usize>>()
                .0
        } else {
            self.into_iter()
                .enumerate()
                .sorted_by(|(_idx_a, a), (_idx_b, b)| sort_partial(a, b))
                .map(|(idx, _v)| idx)
                .collect::<AlignedVec<usize>>()
                .0
        }
    }
}

macro_rules! argsort {
    ($self:ident, $closure:expr) => {{
        $self
            .into_iter()
            .enumerate()
            .sorted_by($closure)
            .map(|(idx, _v)| idx)
            .collect::<AlignedVec<usize>>()
            .0
    }};
}

macro_rules! sort {
    ($self:ident, $reverse:ident) => {{
        if $reverse {
            $self.into_iter().sorted_by(|a, b| b.cmp(a)).collect()
        } else {
            $self.into_iter().sorted_by(|a, b| a.cmp(b)).collect()
        }
    }};
}

impl ChunkSort<Utf8Type> for Utf8Chunked {
    fn sort(&self, reverse: bool) -> Utf8Chunked {
        sort!(self, reverse)
    }

    fn sort_in_place(&mut self, reverse: bool) {
        let sorted = self.sort(reverse);
        self.chunks = sorted.chunks;
    }

    fn argsort(&self, reverse: bool) -> Vec<usize> {
        if reverse {
            argsort!(self, |(_idx_a, a), (_idx_b, b)| b.cmp(a))
        } else {
            argsort!(self, |(_idx_a, a), (_idx_b, b)| a.cmp(b))
        }
    }
}

impl ChunkSort<LargeListType> for LargeListChunked {
    fn sort(&self, _reverse: bool) -> Self {
        println!("A ListChunked cannot be sorted. Doing nothing");
        self.clone()
    }

    fn sort_in_place(&mut self, _reverse: bool) {
        println!("A ListChunked cannot be sorted. Doing nothing");
    }

    fn argsort(&self, _reverse: bool) -> Vec<usize> {
        println!("A ListChunked cannot be sorted. Doing nothing");
        (0..self.len()).collect()
    }
}

impl ChunkSort<BooleanType> for BooleanChunked {
    fn sort(&self, reverse: bool) -> BooleanChunked {
        sort!(self, reverse)
    }

    fn sort_in_place(&mut self, reverse: bool) {
        let sorted = self.sort(reverse);
        self.chunks = sorted.chunks;
    }

    fn argsort(&self, reverse: bool) -> Vec<usize> {
        if reverse {
            argsort!(self, |(_idx_a, a), (_idx_b, b)| b.cmp(a))
        } else {
            argsort!(self, |(_idx_a, a), (_idx_b, b)| a.cmp(b))
        }
    }
}

pub enum FillNoneStrategy<T> {
    Backward,
    Forward,
    Mean,
    Min,
    Max,
    Value(T),
}

/// Replace None values with various strategies
pub trait ChunkFillNone<T> {
    /// Replace None values with one of the following strategies:
    /// * Forward fill (replace None with the previous value)
    /// * Backward fill (replace None with the next value)
    /// * Mean fill (replace None with the mean of the whole array)
    /// * Min fill (replace None with the minimum of the whole array)
    /// * Max fill (replace None with the maximum of the whole array)
    /// * Value fill (replace None with a given value)
    fn fill_none(&self, strategy: FillNoneStrategy<T>) -> Result<Self>
    where
        Self: Sized;
}

fn fill_forward<T>(ca: &ChunkedArray<T>) -> ChunkedArray<T>
where
    T: PolarsNumericType,
{
    ca.into_iter()
        .scan(None, |previous, opt_v| {
            let val = match opt_v {
                Some(_) => Some(opt_v),
                None => Some(*previous),
            };
            *previous = opt_v;
            val
        })
        .collect()
}

fn fill_backward<T>(ca: &ChunkedArray<T>) -> ChunkedArray<T>
where
    T: PolarsNumericType,
{
    let mut iter = ca.into_iter().peekable();

    let mut builder = PrimitiveChunkedBuilder::<T>::new(ca.name(), ca.len());
    while let Some(opt_v) = iter.next() {
        match opt_v {
            Some(v) => builder.append_value(v),
            None => {
                match iter.peek() {
                    // end of iterator
                    None => builder.append_null(),
                    Some(opt_v) => builder.append_option(*opt_v),
                }
            }
        }
    }
    builder.finish()
}

fn fill_value<T>(ca: &ChunkedArray<T>, value: Option<T::Native>) -> ChunkedArray<T>
where
    T: PolarsNumericType,
{
    ca.into_iter()
        .map(|opt_v| match opt_v {
            Some(_) => opt_v,
            None => value,
        })
        .collect()
}

impl<T> ChunkFillNone<T::Native> for ChunkedArray<T>
where
    T: PolarsNumericType,
    T::Native: Add<Output = T::Native> + PartialOrd + Div<Output = T::Native> + Num + NumCast,
{
    fn fill_none(&self, strategy: FillNoneStrategy<T::Native>) -> Result<Self> {
        // nothing to fill
        if self.null_count() == 0 {
            return Ok(self.clone());
        }
        let ca = match strategy {
            FillNoneStrategy::Forward => fill_forward(self),
            FillNoneStrategy::Backward => fill_backward(self),
            FillNoneStrategy::Min => fill_value(self, self.min()),
            FillNoneStrategy::Max => fill_value(self, self.max()),
            FillNoneStrategy::Mean => fill_value(self, self.mean()),
            FillNoneStrategy::Value(val) => fill_value(self, Some(val)),
        };
        Ok(ca)
    }
}

/// Fill a ChunkedArray with one value.
pub trait ChunkFull<T> {
    /// Create a ChunkedArray with a single value.
    fn full(name: &str, value: T, length: usize) -> Self
    where
        Self: std::marker::Sized;
}

impl<T> ChunkFull<T::Native> for ChunkedArray<T>
where
    T: ArrowPrimitiveType,
{
    fn full(name: &str, value: T::Native, length: usize) -> Self
    where
        T::Native: Copy,
    {
        let mut builder = PrimitiveChunkedBuilder::new(name, length);

        for _ in 0..length {
            builder.append_value(value)
        }
        builder.finish()
    }
}

impl<'a> ChunkFull<&'a str> for Utf8Chunked {
    fn full(name: &str, value: &'a str, length: usize) -> Self {
        let mut builder = Utf8ChunkedBuilder::new(name, length);

        for _ in 0..length {
            builder.append_value(value);
        }
        builder.finish()
    }
}

/// Reverse a ChunkedArray<T>
pub trait ChunkReverse<T> {
    /// Return a reversed version of this array.
    fn reverse(&self) -> ChunkedArray<T>;
}

impl<T> ChunkReverse<T> for ChunkedArray<T>
where
    T: PolarsNumericType,
    ChunkedArray<T>: ChunkOps,
{
    fn reverse(&self) -> ChunkedArray<T> {
        if let Ok(slice) = self.cont_slice() {
            let ca: Xob<ChunkedArray<T>> = slice.iter().rev().copied().collect();
            let mut ca = ca.into_inner();
            ca.rename(self.name());
            ca
        } else {
            self.take((0..self.len()).rev(), None)
                .expect("implementation error, should not fail")
        }
    }
}

macro_rules! impl_reverse {
    ($arrow_type:ident, $ca_type:ident) => {
        impl ChunkReverse<$arrow_type> for $ca_type {
            fn reverse(&self) -> Self {
                self.take((0..self.len()).rev(), None)
                    .expect("implementation error, should not fail")
            }
        }
    };
}

impl_reverse!(BooleanType, BooleanChunked);
impl_reverse!(Utf8Type, Utf8Chunked);
impl_reverse!(LargeListType, LargeListChunked);

/// Filter values by a boolean mask.
pub trait ChunkFilter<T> {
    /// Filter values in the ChunkedArray with a boolean mask.
    ///
    /// ```rust
    /// # use polars::prelude::*;
    /// let array = Int32Chunked::new_from_slice("array", &[1, 2, 3]);
    /// let mask = BooleanChunked::new_from_slice("mask", &[true, false, true]);
    ///
    /// let filtered = array.filter(&mask).unwrap();
    /// assert_eq!(Vec::from(&filtered), [Some(1), Some(3)])
    /// ```
    fn filter(&self, filter: &BooleanChunked) -> Result<ChunkedArray<T>>
    where
        Self: Sized;
}

impl<T> ChunkFilter<T> for ChunkedArray<T>
where
    T: PolarsSingleType,
    ChunkedArray<T>: ChunkOps,
{
    fn filter(&self, filter: &BooleanChunked) -> Result<ChunkedArray<T>> {
        let opt = self.optional_rechunk(filter)?;
        let left = opt.as_ref().or(Some(self)).unwrap();
        let chunks = left
            .chunks
            .iter()
            .zip(&filter.downcast_chunks())
            .map(|(arr, &fil)| compute::filter(&*(arr.clone()), fil))
            .collect::<std::result::Result<Vec<_>, arrow::error::ArrowError>>()?;

        Ok(self.copy_with_chunks(chunks))
    }
}

impl ChunkFilter<LargeListType> for LargeListChunked {
    fn filter(&self, filter: &BooleanChunked) -> Result<LargeListChunked> {
        let dt = self.get_inner_dtype();
        let mut builder = get_large_list_builder(dt, self.len(), self.name());
        filter
            .into_iter()
            .zip(self.into_iter())
            .for_each(|(opt_bool_val, opt_series)| {
                let bool_val = opt_bool_val.unwrap_or(false);
                let opt_val = match bool_val {
                    true => opt_series,
                    false => None,
                };
                builder.append_opt_series(opt_val.as_ref())
            });
        Ok(builder.finish())
    }
}

/// Shift the values of a ChunkedArray by a number of periods.
pub trait ChunkShift<T, V> {
    /// Shift the values by a given period and fill the parts that will be empty due to this operation
    /// with `fill_value`.
    fn shift(&self, periods: i32, fill_value: Option<V>) -> Result<ChunkedArray<T>>;
}

fn chunk_shift_helper<T>(
    ca: &ChunkedArray<T>,
    builder: &mut PrimitiveChunkedBuilder<T>,
    amount: usize,
) where
    T: PolarsNumericType,
    T::Native: Copy,
{
    match ca.cont_slice() {
        // fast path
        Ok(slice) => slice
            .iter()
            .take(amount)
            .for_each(|v| builder.append_value(*v)),
        // slower path
        _ => {
            ca.into_iter()
                .take(amount)
                .for_each(|opt| builder.append_option(opt));
        }
    }
}

impl<T> ChunkShift<T, T::Native> for ChunkedArray<T>
where
    T: PolarsNumericType,
    T::Native: Copy,
{
    fn shift(&self, periods: i32, fill_value: Option<T::Native>) -> Result<ChunkedArray<T>> {
        if periods.abs() >= self.len() as i32 {
            return Err(PolarsError::OutOfBounds);
        }
        let mut builder = PrimitiveChunkedBuilder::<T>::new(self.name(), self.len());
        let amount = self.len() - periods.abs() as usize;

        // Fill the front of the array
        if periods > 0 {
            for _ in 0..periods {
                builder.append_option(fill_value)
            }
            chunk_shift_helper(self, &mut builder, amount);
        // Fill the back of the array
        } else {
            chunk_shift_helper(self, &mut builder, amount);
            for _ in 0..periods.abs() {
                builder.append_option(fill_value)
            }
        }
        Ok(builder.finish())
    }
}

macro_rules! impl_shift {
    // append_method and append_fn do almost the same. Only for largelist type, the closure
    // accepts an owned value, while fill_value is a reference. That's why we have two options.
    ($self:ident, $builder:ident, $periods:ident, $fill_value:ident,
    $append_method:ident, $append_fn:expr) => {{
        let amount = $self.len() - $periods.abs() as usize;

        // Fill the front of the array
        if $periods > 0 {
            for _ in 0..$periods {
                $builder.$append_method($fill_value)
            }
            $self
                .into_iter()
                .take(amount)
                .for_each(|opt| $append_fn(&mut $builder, opt));
        // Fill the back of the array
        } else {
            $self
                .into_iter()
                .take(amount)
                .for_each(|opt| $append_fn(&mut $builder, opt));
            for _ in 0..$periods.abs() {
                $builder.$append_method($fill_value)
            }
        }
        Ok($builder.finish())
    }};
}

impl ChunkShift<BooleanType, bool> for BooleanChunked {
    fn shift(&self, periods: i32, fill_value: Option<bool>) -> Result<BooleanChunked> {
        if periods.abs() >= self.len() as i32 {
            return Err(PolarsError::OutOfBounds);
        }
        let mut builder = PrimitiveChunkedBuilder::<BooleanType>::new(self.name(), self.len());

        fn append_fn(builder: &mut PrimitiveChunkedBuilder<BooleanType>, v: Option<bool>) {
            builder.append_option(v);
        }

        impl_shift!(self, builder, periods, fill_value, append_option, append_fn)
    }
}

impl ChunkShift<Utf8Type, &str> for Utf8Chunked {
    fn shift(&self, periods: i32, fill_value: Option<&str>) -> Result<Utf8Chunked> {
        if periods.abs() >= self.len() as i32 {
            return Err(PolarsError::OutOfBounds);
        }
        let mut builder = Utf8ChunkedBuilder::new(self.name(), self.len());
        fn append_fn(builder: &mut Utf8ChunkedBuilder, v: Option<&str>) {
            builder.append_option(v);
        }

        impl_shift!(self, builder, periods, fill_value, append_option, append_fn)
    }
}

impl ChunkShift<LargeListType, &Series> for LargeListChunked {
    fn shift(&self, periods: i32, fill_value: Option<&Series>) -> Result<LargeListChunked> {
        if periods.abs() >= self.len() as i32 {
            return Err(PolarsError::OutOfBounds);
        }
        let dt = self.get_inner_dtype();
        let mut builder = get_large_list_builder(dt, self.len(), self.name());
        fn append_fn(builder: &mut Box<dyn LargListBuilderTrait>, v: Option<Series>) {
            builder.append_opt_series(v.as_ref());
        }

        impl_shift!(
            self,
            builder,
            periods,
            fill_value,
            append_opt_series,
            append_fn
        )
    }
}

#[cfg(test)]
mod test {
    use crate::prelude::*;

    #[test]
    fn test_shift() {
        let ca = Int32Chunked::new_from_slice("", &[1, 2, 3]);
        let shifted = ca.shift(1, Some(0)).unwrap();
        assert_eq!(shifted.cont_slice().unwrap(), &[0, 1, 2]);
        let shifted = ca.shift(1, None).unwrap();
        assert_eq!(Vec::from(&shifted), &[None, Some(1), Some(2)]);
        let shifted = ca.shift(-1, None).unwrap();
        assert_eq!(Vec::from(&shifted), &[Some(1), Some(2), None]);
        assert!(ca.shift(3, None).is_err());
    }

    #[test]
    fn test_fill_none() {
        let ca =
            Int32Chunked::new_from_opt_slice("", &[None, Some(2), Some(3), None, Some(4), None]);
        let filled = ca.fill_none(FillNoneStrategy::Forward).unwrap();
        assert_eq!(
            Vec::from(&filled),
            &[None, Some(2), Some(3), Some(3), Some(4), Some(4)]
        );
        let filled = ca.fill_none(FillNoneStrategy::Backward).unwrap();
        assert_eq!(
            Vec::from(&filled),
            &[Some(2), Some(2), Some(3), Some(4), Some(4), None]
        );
        let filled = ca.fill_none(FillNoneStrategy::Min).unwrap();
        assert_eq!(
            Vec::from(&filled),
            &[Some(2), Some(2), Some(3), Some(2), Some(4), Some(2)]
        );
        let filled = ca.fill_none(FillNoneStrategy::Value(10)).unwrap();
        assert_eq!(
            Vec::from(&filled),
            &[Some(10), Some(2), Some(3), Some(10), Some(4), Some(10)]
        );
        let filled = ca.fill_none(FillNoneStrategy::Mean).unwrap();
        assert_eq!(
            Vec::from(&filled),
            &[Some(3), Some(2), Some(3), Some(3), Some(4), Some(3)]
        );
        println!("{:?}", filled);
    }
}
