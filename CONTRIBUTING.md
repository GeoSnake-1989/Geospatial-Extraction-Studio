# Contributing to Geospatial Extraction Studio

Geospatial Extraction Studio accepts contributions under Apache License 2.0.
Under section 5 of that license, material intentionally submitted for inclusion
is offered under the same license unless the submission is conspicuously marked
otherwise and accepted in writing by the project owner.

## Right to contribute

Only submit material that you wrote or that you have the legal right to submit.
Do not copy code, documentation, maps, imagery, icons, fonts, datasets, or other
content from a source whose terms are unknown or incompatible with this project.

Commit messages for outside contributions must include a Developer Certificate
of Origin sign-off:

```text
Signed-off-by: Your Name <your-email@example.com>
```

By adding the sign-off, the contributor certifies the contribution under the
Developer Certificate of Origin 1.1 at https://developercertificate.org/.
Create the sign-off with `git commit --signoff`.

## Data and assets

- Do not commit downloaded elevation, NAIP, or OpenStreetMap data, generated
  exports, caches, databases, logs, virtual environments, or build output.
- Record the source, author, license, required attribution, and modification
  history for every new third-party or generated asset.
- Preserve provider metadata and license links in generated source manifests.
- Disclose material AI assistance and perform human review for provenance,
  similarity, attribution, and license compatibility before submission.

## Verification

Run the backend tests and frontend build described in `README.md`. Update
`THIRD_PARTY_NOTICES.md`, lockfiles, and legal tests whenever dependencies or
data providers change.
