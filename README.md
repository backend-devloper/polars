# Polars
---

## In memory DataFrames in Rust

This is my mock up of DataFrames implemented in Rust, using Apache Arrow as backend.

## WIP

### Series
- [x] cast
- [x] take by index/ boolean mask
- [x] Rust iterators
- [x] append
- [x] aggregation: min, max, sum
- [x] arithmetic
- [x] comparison
- [ ] find
- [ ] sorting (can be done w/ iterators)

### DataFrame
- [x] selection
- [x] join: inner, left
- [ ] group by
- [x] concat (horizontal)
- [x] read csv
- [ ] write csv
- [ ] write json
- [ ] read json
- [ ] sorting

### Data types
- [x] null
- [x] boolean
- [x] u32
- [x] i32
- [x] i64
- [x] f32
- [x] f64
- [x] utf-8
- [x] date
- [x] time


## Example

```rust
let s0 = Series::init("days", [0, 1, 2, 3, 4].as_ref());
let s1 = Series::init("temp", [22.1, 19.9, 7., 2., 3.].as_ref());
let temp = DataFrame::new_from_columns(vec![s0, s1]).unwrap();

let s0 = Series::init("days", [1, 2].as_ref());
let s1 = Series::init("rain", [0.1, 0.2].as_ref());
let rain = DataFrame::new_from_columns(vec![s0, s1]).unwrap();
let joined = temp.left_join(&rain, "days", "days");
println!("{}", joined.unwrap())
```

```text
           days           temp           rain
            i32            f64            f64
            ---            ---            ---

              0           22.1           null
              1           19.9            0.1
              2              7            0.2
              3              2           null
              4              3           nul
```
