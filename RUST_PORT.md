# Rust Port Plan — gpru v3.5.0alpha1 (Experimental)

This repository now includes a Rust workspace that starts porting:

- `gpru` core general-purpose helpers
- adjacent libraries `statusline` and `w11` (scaffolds)

## Implemented in `crates/gpru`

- Safe coercion helpers: `safe_float`, `safe_int`, `safe_list`
- Dict helpers: `deepget`, `dict_all_paths`, `dict_sort_keylen`, `dict_element_append`
- Time helpers: `now_str`, `now_ts`, `pretty_timedelta`, `prepend_datestamp`, `append_timestamp`
- YAML/JSON IO: `dict_from_yml`, `dict_to_yml`, `dict_to_json` with `!include` support

## Next slices

1. Port `Env` config loader and typed `glob` accessors.
2. Port logger color pipeline (`Info`, `Warn`, `Error`, `Debug`).
3. Port cache/database abstractions from `gppu.data`.
4. Build executable crates for `statusline` and `w11`.


## Release channel

- This Rust migration track is marked **experimental** and versioned as **3.5.0-alpha.1**.
- It is intended for **branch build validation** before any stable release tags are created.

## Parity status checkpoint

- **Y2 coverage:** initial Rust implementations added for `y2list`, `y2path`, `y2topic`, `y2slug`, and `y2eid` with parity-oriented tests.
- **CRAP coverage:** there is no `CRAP` test suite or module in this repository to run yet; add concrete CRAP scenarios/tests to validate parity once available.
- **Overall parity:** not 100% yet; current port covers selected core helpers and initial Y2 types.


## LLM testing instructions

- See `GPRU_LLM_TESTING.md` for required local validation, parity checks, and PR reporting format.

- Release tag target: `v3.5.0alpha1` on branch `dev`.
