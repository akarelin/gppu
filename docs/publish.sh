# gppu's documentation (docs/mkdocs.yaml), built from the code checked out with its tags, into the folder nginx serves at
# kb.karel.in/gppu/v3/ on trix (RAN trix_kb.conf), copied there over ssh by gppu-docs.yaml, independently of releases
set -e
site="$RUNNER_TEMP/site"
uvx --python 3.14 --with mkdocs-material --with "mkdocstrings[python]" --with mkdocs-gen-files --with graphifyy mkdocs build --strict -f docs/mkdocs.yaml -d "$site"
ssh trix 'rm -rf /data/gppu/docs/v3.next && install -d -m 755 /data/gppu /data/gppu/docs'
scp -rq "$site" trix:/data/gppu/docs/v3.next
ssh trix 'rm -rf /data/gppu/docs/v3 && mv /data/gppu/docs/v3.next /data/gppu/docs/v3'
