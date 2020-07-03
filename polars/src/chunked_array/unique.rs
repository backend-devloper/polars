use crate::prelude::*;
use crate::utils::{floating_encode_f64, integer_decode};
use fnv::{FnvBuildHasher, FnvHasher};
use num::{NumCast, ToPrimitive};
use std::collections::{HashMap, HashSet};
use std::hash::{BuildHasherDefault, Hash};

pub trait Unique<T> {
    // We don't return Self to be able to use AutoRef specialization
    fn unique(&self) -> ChunkedArray<T>;
}

fn fill_set<A>(
    a: impl Iterator<Item = A>,
    capacity: usize,
) -> HashSet<A, BuildHasherDefault<FnvHasher>>
where
    A: Hash + Eq,
{
    let mut set = HashSet::with_capacity_and_hasher(capacity, FnvBuildHasher::default());

    for val in a {
        set.insert(val);
    }

    set
}

impl<T> Unique<T> for ChunkedArray<T>
where
    T: PolarsIntegerType,
    T::Native: Hash + Eq,
    ChunkedArray<T>: ChunkOps,
{
    fn unique(&self) -> Self {
        let set = match self.cont_slice() {
            Ok(slice) => fill_set(slice.iter().map(|v| Some(*v)), self.len()),
            Err(_) => fill_set(self.into_iter(), self.len()),
        };

        let builder = PrimitiveChunkedBuilder::new(self.name(), set.len());
        builder.new_from_iter(set.iter().copied())
    }
}

impl Unique<Utf8Type> for Utf8Chunked {
    fn unique(&self) -> Self {
        let set = fill_set(self.into_iter(), self.len());
        let mut builder = Utf8ChunkedBuilder::new(self.name(), set.len());
        self.into_iter()
            .for_each(|val| builder.append_value(val).expect("could not append"));
        builder.finish()
    }
}

impl Unique<BooleanType> for BooleanChunked {
    fn unique(&self) -> Self {
        // can be None, Some(true), Some(false)
        let mut unique = Vec::with_capacity(3);
        for v in self {
            if unique.len() == 3 {
                break;
            }
            if !unique.contains(&v) {
                unique.push(v)
            }
        }
        ChunkedArray::new_from_opt_slice(self.name(), &unique)
    }
}

// Use stable form of specialization using autoref
// https://github.com/dtolnay/case-studies/blob/master/autoref-specialization/README.md
impl<T> Unique<T> for &ChunkedArray<T>
where
    T: PolarsNumericType,
    T::Native: NumCast + ToPrimitive,
    ChunkedArray<T>: ChunkOps,
{
    fn unique(&self) -> ChunkedArray<T> {
        let set = match self.cont_slice() {
            Ok(slice) => fill_set(
                slice
                    .iter()
                    .map(|v| Some(integer_decode(v.to_f64().unwrap()))),
                self.len(),
            ),
            Err(_) => fill_set(
                self.into_iter()
                    .map(|opt_v| opt_v.map(|v| integer_decode(v.to_f64().unwrap()))),
                self.len(),
            ),
        };

        let builder = PrimitiveChunkedBuilder::new(self.name(), set.len());
        builder.new_from_iter(set.iter().copied().map(|opt| match opt {
            Some((mantissa, exponent, sign)) => {
                let flt = floating_encode_f64(mantissa, exponent, sign);
                let val: T::Native = NumCast::from(flt).unwrap();
                Some(val)
            }
            None => None,
        }))
    }
}

pub trait ValueCounts<T>
where
    T: ArrowPrimitiveType,
{
    fn value_counts(&self) -> HashMap<Option<T::Native>, u32, BuildHasherDefault<FnvHasher>>;
}

fn fill_set_value_count<K>(
    a: impl Iterator<Item = K>,
    capacity: usize,
) -> HashMap<K, u32, BuildHasherDefault<FnvHasher>>
where
    K: Hash + Eq,
{
    let mut kv_store = HashMap::with_capacity_and_hasher(capacity, FnvBuildHasher::default());

    for key in a {
        let count = kv_store.entry(key).or_insert(0);
        *count += 1;
    }

    kv_store
}

impl<T> ValueCounts<T> for ChunkedArray<T>
where
    T: PolarsIntegerType,
    T::Native: Hash + Eq,
    ChunkedArray<T>: ChunkOps,
{
    fn value_counts(&self) -> HashMap<Option<T::Native>, u32, BuildHasherDefault<FnvHasher>> {
        match self.cont_slice() {
            Ok(slice) => fill_set_value_count(slice.iter().map(|v| Some(*v)), self.len()),
            Err(_) => fill_set_value_count(self.into_iter(), self.len()),
        }
    }
}

#[cfg(test)]
mod test {
    use crate::prelude::*;
    use itertools::Itertools;

    #[test]
    fn unique() {
        let ca = ChunkedArray::<Int32Type>::new_from_slice("a", &[1, 2, 3, 2, 1]);
        assert_eq!(
            ca.unique().into_iter().collect_vec(),
            vec![Some(1), Some(2), Some(3)]
        );
        let ca = BooleanChunked::new_from_slice("a", &[true, false, true]);
        assert_eq!(
            ca.unique().into_iter().collect_vec(),
            vec![Some(true), Some(false)]
        );
    }
}
