use crate::datatypes::{AnyType, ToStr};
use crate::prelude::*;

#[cfg(feature = "temporal")]
use crate::chunked_array::temporal::{
    date32_as_datetime, date64_as_datetime, time32_millisecond_as_time, time32_second_as_time,
    time64_microsecond_as_time, time64_nanosecond_as_time, timestamp_microseconds_as_datetime,
    timestamp_milliseconds_as_datetime, timestamp_nanoseconds_as_datetime,
    timestamp_seconds_as_datetime,
};
use num::{Num, NumCast};
#[cfg(feature = "pretty")]
use prettytable::Table;
use std::{
    fmt,
    fmt::{Debug, Display, Formatter},
};

/// Some unit functions that just pass the integer values if we don't want all chrono functionality
#[cfg(not(feature = "temporal"))]
mod temporal {
    pub struct DateTime<T>(T)
    where
        T: Copy;

    impl<T> DateTime<T>
    where
        T: Copy,
    {
        pub fn date(&self) -> T {
            self.0
        }
    }

    pub fn date32_as_datetime(v: i32) -> DateTime<i32> {
        DateTime(v)
    }
    pub fn date64_as_datetime(v: i64) -> DateTime<i64> {
        DateTime(v)
    }
    pub fn time32_millisecond_as_time(v: i32) -> i32 {
        v
    }
    pub fn time32_second_as_time(v: i32) -> i32 {
        v
    }
    pub fn time64_nanosecond_as_time(v: i64) -> i64 {
        v
    }
    pub fn time64_microsecond_as_time(v: i64) -> i64 {
        v
    }
    pub fn timestamp_nanoseconds_as_datetime(v: i64) -> i64 {
        v
    }
    pub fn timestamp_microseconds_as_datetime(v: i64) -> i64 {
        v
    }
    pub fn timestamp_milliseconds_as_datetime(v: i64) -> i64 {
        v
    }
    pub fn timestamp_seconds_as_datetime(v: i64) -> i64 {
        v
    }
}
#[cfg(not(feature = "temporal"))]
use temporal::*;

impl Debug for Series {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        const LIMIT: usize = 10;
        let limit = std::cmp::min(self.len(), LIMIT);

        macro_rules! format_series {
            ($a:ident, $name:expr) => {{
                write![f, "Series: {}\n[\n", $name]?;

                for i in 0..limit {
                    let v = $a.get(i);
                    write!(f, "\t{}\n", v)?;
                }

                write![f, "]"]
            }};
        }

        match self {
            Series::UInt8(a) => format_series!(a, "u8"),
            Series::UInt16(a) => format_series!(a, "u16"),
            Series::UInt32(a) => format_series!(a, "u32"),
            Series::UInt64(a) => format_series!(a, "u64"),
            Series::Int8(a) => format_series!(a, "i8"),
            Series::Int16(a) => format_series!(a, "i16"),
            Series::Int32(a) => format_series!(a, "i32"),
            Series::Int64(a) => format_series!(a, "i64"),
            Series::Bool(a) => format_series!(a, "bool"),
            Series::Float32(a) => format_series!(a, "f32"),
            Series::Float64(a) => format_series!(a, "f64"),
            Series::Date32(a) => format_series!(a, "date32(day)"),
            Series::Date64(a) => format_series!(a, "date64(ms)"),
            Series::Time32Millisecond(a) => format_series!(a, "time32(ms)"),
            Series::Time32Second(a) => format_series!(a, "time32(s)"),
            Series::Time64Nanosecond(a) => format_series!(a, "time64(ns)"),
            Series::Time64Microsecond(a) => format_series!(a, "time64(μs)"),
            Series::DurationNanosecond(a) => format_series!(a, "duration(ns)"),
            Series::DurationMicrosecond(a) => format_series!(a, "duration(μs)"),
            Series::DurationMillisecond(a) => format_series!(a, "duration(ms)"),
            Series::DurationSecond(a) => format_series!(a, "duration(s)"),
            Series::IntervalDayTime(a) => format_series!(a, "interval(daytime)"),
            Series::IntervalYearMonth(a) => format_series!(a, "interval(year-month)"),
            Series::TimestampNanosecond(a) => format_series!(a, "timestamp(ns)"),
            Series::TimestampMicrosecond(a) => format_series!(a, "timestamp(μs)"),
            Series::TimestampMillisecond(a) => format_series!(a, "timestamp(ms)"),
            Series::TimestampSecond(a) => format_series!(a, "timestamp(s)"),
            Series::Utf8(a) => {
                write![f, "Series: str \n[\n"]?;
                a.into_iter().take(LIMIT).for_each(|opt_s| match opt_s {
                    None => {
                        write!(f, "\tnull\n").ok();
                    }
                    Some(s) => {
                        write!(f, "\t\"{}\"\n", &s[..std::cmp::min(LIMIT, s.len())]).ok();
                    }
                });
                write![f, "]"]
            }
            Series::List(a) => todo!(),
        }
    }
}

impl Display for Series {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        Debug::fmt(self, f)
    }
}

impl Debug for DataFrame {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        Display::fmt(self, f)
    }
}

#[cfg(feature = "pretty")]
impl Display for DataFrame {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let mut table = Table::new();
        let names = self
            .schema()
            .fields()
            .iter()
            .map(|f| format!("{}\n---\n{}", f.name(), f.data_type().to_str()))
            .collect();
        table.set_titles(names);
        for i in 0..10 {
            let opt = self.get(i);
            if let Some(row) = opt {
                let mut row_str = Vec::with_capacity(row.len());
                for v in &row {
                    row_str.push(format!("{}", v));
                }
                table.add_row(row.iter().map(|v| format!("{}", v)).collect());
            } else {
                break;
            }
        }
        write!(f, "{}", table)?;
        Ok(())
    }
}

#[cfg(not(feature = "pretty"))]
impl Display for DataFrame {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "DataFrame. NOTE: compile with the feature 'pretty' for pretty printing."
        )
    }
}

fn fmt_integer<T: Num + NumCast>(f: &mut Formatter<'_>, width: usize, v: T) -> fmt::Result {
    let v: i64 = NumCast::from(v).unwrap();
    if v > 9999 {
        write!(f, "{:>width$e}", v, width = width)
    } else {
        write!(f, "{:>width$}", v, width = width)
    }
}

fn fmt_float<T: Num + NumCast>(f: &mut Formatter<'_>, width: usize, v: T) -> fmt::Result {
    let v: f64 = NumCast::from(v).unwrap();
    let v = (v * 1000.).round() / 1000.;
    if v > 9999. || v < 0.001 {
        write!(f, "{:>width$e}", v, width = width)
    } else {
        write!(f, "{:>width$}", v, width = width)
    }
}

#[cfg(not(feature = "pretty"))]
impl Display for AnyType<'_> {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        write!(f, "{:?}", self)
    }
}

#[cfg(feature = "pretty")]
impl Display for AnyType<'_> {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        let width = 0;
        match self {
            AnyType::Null => write!(f, "{}", "null"),
            AnyType::UInt8(v) => write!(f, "{}", v),
            AnyType::UInt16(v) => write!(f, "{}", v),
            AnyType::UInt32(v) => write!(f, "{}", v),
            AnyType::UInt64(v) => write!(f, "{}", v),
            AnyType::Int8(v) => fmt_integer(f, width, *v),
            AnyType::Int16(v) => fmt_integer(f, width, *v),
            AnyType::Int32(v) => fmt_integer(f, width, *v),
            AnyType::Int64(v) => fmt_integer(f, width, *v),
            AnyType::Float32(v) => fmt_float(f, width, *v),
            AnyType::Float64(v) => fmt_float(f, width, *v),
            AnyType::Boolean(v) => write!(f, "{}", *v),
            AnyType::Utf8(v) => write!(f, "{}", format!("\"{}\"", v)),
            AnyType::Date32(v) => write!(f, "{}", date32_as_datetime(*v).date()),
            AnyType::Date64(v) => write!(f, "{}", date64_as_datetime(*v).date()),
            AnyType::Time32(v, TimeUnit::Millisecond) => {
                write!(f, "{}", time32_millisecond_as_time(*v))
            }
            AnyType::Time32(v, TimeUnit::Second) => write!(f, "{}", time32_second_as_time(*v)),
            AnyType::Time64(v, TimeUnit::Nanosecond) => {
                write!(f, "{}", time64_nanosecond_as_time(*v))
            }
            AnyType::Time64(v, TimeUnit::Microsecond) => {
                write!(f, "{}", time64_microsecond_as_time(*v))
            }
            AnyType::Duration(v, TimeUnit::Nanosecond) => write!(f, "{}", v),
            AnyType::Duration(v, TimeUnit::Microsecond) => write!(f, "{}", v),
            AnyType::Duration(v, TimeUnit::Millisecond) => write!(f, "{}", v),
            AnyType::Duration(v, TimeUnit::Second) => write!(f, "{}", v),
            AnyType::TimeStamp(v, TimeUnit::Nanosecond) => {
                write!(f, "{}", timestamp_nanoseconds_as_datetime(*v))
            }
            AnyType::TimeStamp(v, TimeUnit::Microsecond) => {
                write!(f, "{}", timestamp_microseconds_as_datetime(*v))
            }
            AnyType::TimeStamp(v, TimeUnit::Millisecond) => {
                write!(f, "{}", timestamp_milliseconds_as_datetime(*v))
            }
            AnyType::TimeStamp(v, TimeUnit::Second) => {
                write!(f, "{}", timestamp_seconds_as_datetime(*v))
            }
            AnyType::IntervalDayTime(v) => write!(f, "{}", v),
            AnyType::IntervalYearMonth(v) => write!(f, "{}", v),
            _ => unimplemented!(),
        }
    }
}

#[cfg(all(test, feature = "temporal"))]
mod test {
    use crate::prelude::*;

    #[test]
    fn temporal() {
        let s = Date32Chunked::new_from_opt_slice("date32", &[Some(1), None, Some(3)]);
        assert_eq!(
            r#"Series: date32(day)
[
	1970-01-02
	null
	1970-01-04
]"#,
            format!("{:?}", s.into_series())
        );

        let s = Date64Chunked::new_from_opt_slice("", &[Some(1), None, Some(1000_000_000_000)]);
        assert_eq!(
            r#"Series: date64(ms)
[
	1970-01-01
	null
	2001-09-09
]"#,
            format!("{:?}", s.into_series())
        );
        let s = Time64NanosecondChunked::new_from_slice(
            "",
            &[1_000_000, 37_800_005_000_000, 86_399_210_000_000],
        );
        assert_eq!(
            r#"Series: time64(ns)
[
	00:00:00.001
	10:30:00.005
	23:59:59.210
]"#,
            format!("{:?}", s.into_series())
        )
    }
}
