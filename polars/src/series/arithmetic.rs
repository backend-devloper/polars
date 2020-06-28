use crate::prelude::*;
use num::{Num, NumCast};
use std::ops;

impl Series {
    pub fn subtract(&self, rhs: &Series) -> Result<Self> {
        macro_rules! subtract {
            ($variant:path, $lhs:ident) => {{
                if let $variant(rhs_) = rhs {
                    Ok($variant($lhs - rhs_))
                } else {
                    Err(PolarsError::DataTypeMisMatch)
                }
            }};
        }
        match self {
            Series::UInt32(lhs) => subtract!(Series::UInt32, lhs),
            Series::Int32(lhs) => subtract!(Series::Int32, lhs),
            Series::Int64(lhs) => subtract!(Series::Int64, lhs),
            Series::Float32(lhs) => subtract!(Series::Float32, lhs),
            Series::Float64(lhs) => subtract!(Series::Float64, lhs),
            Series::Date32(lhs) => subtract!(Series::Date32, lhs),
            Series::Date64(lhs) => subtract!(Series::Date64, lhs),
            Series::Time64Ns(lhs) => subtract!(Series::Time64Ns, lhs),
            Series::DurationNs(lhs) => subtract!(Series::DurationNs, lhs),
            _ => Err(PolarsError::InvalidOperation),
        }
    }

    pub fn add_to(&self, rhs: &Series) -> Result<Self> {
        macro_rules! add {
            ($variant:path, $lhs:ident) => {{
                if let $variant(rhs_) = rhs {
                    Ok($variant($lhs + rhs_))
                } else {
                    Err(PolarsError::DataTypeMisMatch)
                }
            }};
        }
        match self {
            Series::UInt32(lhs) => add!(Series::UInt32, lhs),
            Series::Int32(lhs) => add!(Series::Int32, lhs),
            Series::Int64(lhs) => add!(Series::Int64, lhs),
            Series::Float32(lhs) => add!(Series::Float32, lhs),
            Series::Float64(lhs) => add!(Series::Float64, lhs),
            Series::Date32(lhs) => add!(Series::Date32, lhs),
            Series::Date64(lhs) => add!(Series::Date64, lhs),
            Series::Time64Ns(lhs) => add!(Series::Time64Ns, lhs),
            Series::DurationNs(lhs) => add!(Series::DurationNs, lhs),
            _ => Err(PolarsError::InvalidOperation),
        }
    }

    pub fn multiply(&self, rhs: &Series) -> Result<Self> {
        macro_rules! multiply {
            ($variant:path, $lhs:ident) => {{
                if let $variant(rhs_) = rhs {
                    Ok($variant($lhs * rhs_))
                } else {
                    Err(PolarsError::DataTypeMisMatch)
                }
            }};
        }
        match self {
            Series::UInt32(lhs) => multiply!(Series::UInt32, lhs),
            Series::Int32(lhs) => multiply!(Series::Int32, lhs),
            Series::Int64(lhs) => multiply!(Series::Int64, lhs),
            Series::Float32(lhs) => multiply!(Series::Float32, lhs),
            Series::Float64(lhs) => multiply!(Series::Float64, lhs),
            Series::Date32(lhs) => multiply!(Series::Date32, lhs),
            Series::Date64(lhs) => multiply!(Series::Date64, lhs),
            Series::Time64Ns(lhs) => multiply!(Series::Time64Ns, lhs),
            Series::DurationNs(lhs) => multiply!(Series::DurationNs, lhs),
            _ => Err(PolarsError::InvalidOperation),
        }
    }

    fn divide(&self, rhs: &Series) -> Result<Self> {
        macro_rules! divide {
            ($variant:path, $lhs:ident) => {{
                if let $variant(rhs_) = rhs {
                    Ok($variant($lhs / rhs_))
                } else {
                    Err(PolarsError::DataTypeMisMatch)
                }
            }};
        }
        match self {
            Series::UInt32(lhs) => divide!(Series::UInt32, lhs),
            Series::Int32(lhs) => divide!(Series::Int32, lhs),
            Series::Int64(lhs) => divide!(Series::Int64, lhs),
            Series::Float32(lhs) => divide!(Series::Float32, lhs),
            Series::Float64(lhs) => divide!(Series::Float64, lhs),
            Series::Date32(lhs) => divide!(Series::Date32, lhs),
            Series::Date64(lhs) => divide!(Series::Date64, lhs),
            Series::Time64Ns(lhs) => divide!(Series::Time64Ns, lhs),
            Series::DurationNs(lhs) => divide!(Series::DurationNs, lhs),
            _ => Err(PolarsError::InvalidOperation),
        }
    }
}

impl ops::Sub for Series {
    type Output = Self;

    fn sub(self, rhs: Self) -> Self::Output {
        (&self).subtract(&rhs).expect("data types don't match")
    }
}

impl ops::Add for Series {
    type Output = Self;

    fn add(self, rhs: Self) -> Self::Output {
        (&self).add_to(&rhs).expect("data types don't match")
    }
}

impl std::ops::Mul for Series {
    type Output = Self;

    fn mul(self, rhs: Self) -> Self::Output {
        (&self).multiply(&rhs).expect("data types don't match")
    }
}

impl std::ops::Div for Series {
    type Output = Self;

    fn div(self, rhs: Self) -> Self::Output {
        (&self).divide(&rhs).expect("data types don't match")
    }
}

// Same only now for referenced data types

impl ops::Sub for &Series {
    type Output = Series;

    fn sub(self, rhs: Self) -> Self::Output {
        (&self).subtract(rhs).expect("data types don't match")
    }
}

impl ops::Add for &Series {
    type Output = Series;

    fn add(self, rhs: Self) -> Self::Output {
        (&self).add_to(rhs).expect("data types don't match")
    }
}

impl std::ops::Mul for &Series {
    type Output = Series;

    /// ```
    /// # use polars::prelude::*;
    /// let s: Series = [1, 2, 3].iter().collect();
    /// let out = &s * &s;
    /// ```
    fn mul(self, rhs: Self) -> Self::Output {
        (&self).multiply(rhs).expect("data types don't match")
    }
}

impl std::ops::Div for &Series {
    type Output = Series;

    /// ```
    /// # use polars::prelude::*;
    /// let s: Series = [1, 2, 3].iter().collect();
    /// let out = &s / &s;
    /// ```
    fn div(self, rhs: Self) -> Self::Output {
        (&self).divide(rhs).expect("data types don't match")
    }
}

// Series +-/* number

macro_rules! op_num_rhs {
    ($typ:ty, $ca:ident, $rhs:ident, $operand:tt) => {
    {
            let rhs: $typ = NumCast::from($rhs).expect(&format!("could not cast"));
            $ca.into_iter().map(|opt_v| opt_v.map(|v| v $operand rhs)).collect()
            }
    }
}

impl<T> ops::Sub<T> for &Series
where
    T: Num + NumCast,
{
    type Output = Series;

    fn sub(self, rhs: T) -> Self::Output {
        match self {
            Series::UInt32(ca) => op_num_rhs!(u32, ca, rhs, -),
            Series::Int32(ca) => op_num_rhs!(i32, ca, rhs, -),
            Series::Int64(ca) => op_num_rhs!(i64, ca, rhs, -),
            Series::Float32(ca) => op_num_rhs!(f32, ca, rhs, -),
            Series::Float64(ca) => op_num_rhs!(f64, ca, rhs, -),
            Series::Date32(ca) => op_num_rhs!(i32, ca, rhs, -),
            Series::Date64(ca) => op_num_rhs!(i64, ca, rhs, -),
            Series::Time64Ns(ca) => op_num_rhs!(i64, ca, rhs, -),
            Series::DurationNs(ca) => op_num_rhs!(i64, ca, rhs, -),
            _ => unimplemented!(),
        }
    }
}

impl<T> ops::Sub<T> for Series
where
    T: Num + NumCast,
{
    type Output = Self;

    fn sub(self, rhs: T) -> Self::Output {
        (&self).sub(rhs)
    }
}

impl<T> ops::Add<T> for &Series
where
    T: Num + NumCast,
{
    type Output = Series;

    fn add(self, rhs: T) -> Self::Output {
        match self {
            Series::UInt32(ca) => op_num_rhs!(u32, ca, rhs, +),
            Series::Int32(ca) => op_num_rhs!(i32, ca, rhs, +),
            Series::Int64(ca) => op_num_rhs!(i64, ca, rhs, +),
            Series::Float32(ca) => op_num_rhs!(f32, ca, rhs, +),
            Series::Float64(ca) => op_num_rhs!(f64, ca, rhs, +),
            Series::Date32(ca) => op_num_rhs!(i32, ca, rhs, +),
            Series::Date64(ca) => op_num_rhs!(i64, ca, rhs, +),
            Series::Time64Ns(ca) => op_num_rhs!(i64, ca, rhs, +),
            Series::DurationNs(ca) => op_num_rhs!(i64, ca, rhs, +),
            _ => unimplemented!(),
        }
    }
}

impl<T> ops::Add<T> for Series
where
    T: Num + NumCast,
{
    type Output = Self;

    fn add(self, rhs: T) -> Self::Output {
        (&self).add(rhs)
    }
}

impl<T> ops::Div<T> for &Series
where
    T: Num + NumCast,
{
    type Output = Series;

    fn div(self, rhs: T) -> Self::Output {
        match self {
            Series::UInt32(ca) => op_num_rhs!(u32, ca, rhs, /),
            Series::Int32(ca) => op_num_rhs!(i32, ca, rhs, /),
            Series::Int64(ca) => op_num_rhs!(i64, ca, rhs, /),
            Series::Float32(ca) => op_num_rhs!(f32, ca, rhs, /),
            Series::Float64(ca) => op_num_rhs!(f64, ca, rhs, /),
            Series::Date32(ca) => op_num_rhs!(i32, ca, rhs, /),
            Series::Date64(ca) => op_num_rhs!(i64, ca, rhs, /),
            Series::Time64Ns(ca) => op_num_rhs!(i64, ca, rhs, /),
            Series::DurationNs(ca) => op_num_rhs!(i64, ca, rhs, /),
            _ => unimplemented!(),
        }
    }
}

impl<T> ops::Div<T> for Series
where
    T: Num + NumCast,
{
    type Output = Self;

    fn div(self, rhs: T) -> Self::Output {
        (&self).div(rhs)
    }
}

impl<T> ops::Mul<T> for &Series
where
    T: Num + NumCast,
{
    type Output = Series;

    fn mul(self, rhs: T) -> Self::Output {
        match self {
            Series::UInt32(ca) => op_num_rhs!(u32, ca, rhs, *),
            Series::Int32(ca) => op_num_rhs!(i32, ca, rhs, *),
            Series::Int64(ca) => op_num_rhs!(i64, ca, rhs, *),
            Series::Float32(ca) => op_num_rhs!(f32, ca, rhs, *),
            Series::Float64(ca) => op_num_rhs!(f64, ca, rhs, *),
            Series::Date32(ca) => op_num_rhs!(i32, ca, rhs, *),
            Series::Date64(ca) => op_num_rhs!(i64, ca, rhs, *),
            Series::Time64Ns(ca) => op_num_rhs!(i64, ca, rhs, *),
            Series::DurationNs(ca) => op_num_rhs!(i64, ca, rhs, *),
            _ => unimplemented!(),
        }
    }
}

impl<T> ops::Mul<T> for Series
where
    T: Num + NumCast,
{
    type Output = Self;

    fn mul(self, rhs: T) -> Self::Output {
        (&self).mul(rhs)
    }
}

pub trait LhsNumOps<Rhs> {
    type Output;

    fn add(self, rhs: Rhs) -> Self::Output;
    fn sub(self, rhs: Rhs) -> Self::Output;
    fn div(self, rhs: Rhs) -> Self::Output;
    fn mul(self, rhs: Rhs) -> Self::Output;
}

macro_rules! op_num_lhs {
    ($typ:ty, $ca:ident, $lhs:ident, $operand:tt) => {
    {
            let lhs: $typ = NumCast::from($lhs).expect(&format!("could not cast"));
            $ca.into_iter().map(|opt_v| opt_v.map(|v| lhs $operand v)).collect()
            }
    }
}

impl<T> LhsNumOps<&Series> for T
where
    T: Num + NumCast,
{
    type Output = Series;

    fn add(self, rhs: &Series) -> Self::Output {
        match rhs {
            Series::UInt32(ca) => op_num_lhs!(u32, ca, self, +),
            Series::Int32(ca) => op_num_lhs!(i32, ca, self, +),
            Series::Int64(ca) => op_num_lhs!(i64, ca, self, +),
            Series::Float32(ca) => op_num_lhs!(f32, ca, self, +),
            Series::Float64(ca) => op_num_lhs!(f64, ca, self, +),
            Series::Date32(ca) => op_num_lhs!(i32, ca, self, +),
            Series::Date64(ca) => op_num_lhs!(i64, ca, self, +),
            Series::Time64Ns(ca) => op_num_lhs!(i64, ca, self, +),
            Series::DurationNs(ca) => op_num_lhs!(i64, ca, self, +),
            _ => unimplemented!(),
        }
    }
    fn sub(self, rhs: &Series) -> Self::Output {
        match rhs {
            Series::UInt32(ca) => op_num_lhs!(u32, ca, self, -),
            Series::Int32(ca) => op_num_lhs!(i32, ca, self, -),
            Series::Int64(ca) => op_num_lhs!(i64, ca, self, -),
            Series::Float32(ca) => op_num_lhs!(f32, ca, self, -),
            Series::Float64(ca) => op_num_lhs!(f64, ca, self, -),
            Series::Date32(ca) => op_num_lhs!(i32, ca, self, -),
            Series::Date64(ca) => op_num_lhs!(i64, ca, self, -),
            Series::Time64Ns(ca) => op_num_lhs!(i64, ca, self, -),
            Series::DurationNs(ca) => op_num_lhs!(i64, ca, self, -),
            _ => unimplemented!(),
        }
    }
    fn div(self, rhs: &Series) -> Self::Output {
        match rhs {
            Series::UInt32(ca) => op_num_lhs!(u32, ca, self, /),
            Series::Int32(ca) => op_num_lhs!(i32, ca, self, /),
            Series::Int64(ca) => op_num_lhs!(i64, ca, self, /),
            Series::Float32(ca) => op_num_lhs!(f32, ca, self, /),
            Series::Float64(ca) => op_num_lhs!(f64, ca, self, /),
            Series::Date32(ca) => op_num_lhs!(i32, ca, self, /),
            Series::Date64(ca) => op_num_lhs!(i64, ca, self, /),
            Series::Time64Ns(ca) => op_num_lhs!(i64, ca, self, /),
            Series::DurationNs(ca) => op_num_lhs!(i64, ca, self, /),
            _ => unimplemented!(),
        }
    }
    fn mul(self, rhs: &Series) -> Self::Output {
        match rhs {
            Series::UInt32(ca) => op_num_lhs!(u32, ca, self, *),
            Series::Int32(ca) => op_num_lhs!(i32, ca, self, *),
            Series::Int64(ca) => op_num_lhs!(i64, ca, self, *),
            Series::Float32(ca) => op_num_lhs!(f32, ca, self, *),
            Series::Float64(ca) => op_num_lhs!(f64, ca, self, *),
            Series::Date32(ca) => op_num_lhs!(i32, ca, self, *),
            Series::Date64(ca) => op_num_lhs!(i64, ca, self, *),
            Series::Time64Ns(ca) => op_num_lhs!(i64, ca, self, *),
            Series::DurationNs(ca) => op_num_lhs!(i64, ca, self, *),
            _ => unimplemented!(),
        }
    }
}
