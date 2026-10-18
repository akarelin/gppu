# gppu's documentation (mkdocs.yaml beside this file), published at its site_url: each module's page written by mkdocstrings from the
# module's docstrings, read from the checkout's source, so the build installs none of gppu's dependencies:
#   docker build -f docs/Dockerfile --output type=local,dest=<folder> .
FROM python:3.14-slim AS mkdocs
RUN pip install --no-cache-dir mkdocs-material "mkdocstrings[python]"
WORKDIR /gppu
COPY gppu gppu
COPY docs docs
RUN mkdocs build --strict -f docs/mkdocs.yaml -d /site

FROM scratch
COPY --from=mkdocs /site /
