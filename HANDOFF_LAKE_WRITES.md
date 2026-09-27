---
fileClass: Document
created: 2026-09-27T07:12-07:00
updated: 2026-09-27T07:12-07:00
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-27T07:12-07:00 }
---

# Handoff: writing into the Lake through gppu.fs

Task: gppu's filesystem layer writes files into the Lake (`lake://`) by rules: it leaves a file alone when it matches, replaces it only when the new one strictly extends it, and merges by rules kept in the folder. Pipelines in Cruft call it instead of writing files themselves.

## Alex's words, 2026-09-27, in the Cruft Omi session

- 07:04: "Not overwriting existing files if metadata matchess. Overwrite if strictly larger (for append-only format) and [tbd] if deep merge is required. (Should be lake feature. Writing into correct folder with doing merge or new version, etc. Its not omi."
- 07:04: "Existing media can be moved to match lake structure, but not re-downloaded."
- between 07:04 and 07:10: "lake gppu.fs should be doing it"; "lake://"; "Rules on how to merge files can be stored in a foldeer. Contacts foler will have yaml file that defines how to delete/update/upsert, etc."; "Hand off fs work to gppu and let's do something else instead,"

Deep merge is marked tbd by Alex: not specified.

## Where it will be used

- Cruft (`D:\Dev\CRAP\Cruft`, Windmill workspace `cruft` at https://cruft.karelin.ai) runs the Lake's pipelines. `f/lake/omi/raw` writes each Omi conversation as `detail.json` at the graph's textlake rule `recording_detail`, now `sources/{YYYY}/recordings/omi/{MM}/{DD}/{id}/detail.json`, comparing bytes itself; `f/lake/plaud` (another session) and `f/lake/m365` (another session) write the same way. Their workers mount `\\s1\Lake` at `/mnt/S1/Lake`.
- Contacts are the first folder Alex names for merge rules; `examples/contacts` in this repo is the existing contacts example.
