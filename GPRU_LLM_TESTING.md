# GPRU LLM Testing Guide (v6.0.0-experimental)

Use this checklist whenever you modify Rust code in `crates/gpru`, `crates/statusline`, or `crates/w11`.

## 1) Fast local validation (required)

```bash
cargo fmt --all
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --all-targets --locked
```

## 2) Parity-focused checks (required for behavior changes)

Run the Rust parity tests:

```bash
cargo test -p gpru --test port_parity -- --nocapture
cargo test -p gpru --test y2_parity -- --nocapture
```

If your change is related to Y2 semantics, compare against existing Python behavior:

```bash
pytest -q tests/test_y2types.py
```

## 3) Packaging sanity checks (required before merge)

```bash
cargo package -p gpru --allow-dirty
cargo check -p statusline --all-targets --locked
cargo check -p w11 --all-targets --locked
```

## 4) CI parity expectation

Your PR should pass the workflow:

- `.github/workflows/rust-branch-build.yml`
- jobs: `quality`, `build-and-test` (Linux/macOS/Windows), and `package-dry-run`

## 5) Reporting format for LLM-generated PRs

Include:

1. Exact commands executed.
2. Pass/fail status per command.
3. Any known parity gaps (e.g., if a Python feature in `gppu` is still not ported to `gpru`).

## Current version marker

- Rust migration track: `6.0.0-experimental`
- Primary crate: `gpru` (General Purpose Rusty Utilities)
