# Build gppu 3.6.0

Publish the Python 3.14 artifacts for the existing `gppu/v3.6.0` tag through the `gppu` GitHub Actions workflow.

## Required result

- [ ] Linux test and release jobs obtain Python 3.14 through `actions/setup-python`.
- [ ] Rebuilding an existing tag uploads its artifacts to the existing release.
- [ ] The workflow completes successfully for `gppu/v3.6.0` with its tests enabled.
- [ ] The versioned release and `gppu/latest` contain the 3.6.0 wheel and source distribution.
