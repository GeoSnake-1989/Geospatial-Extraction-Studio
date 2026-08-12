# Geospatial Extraction Studio project instructions

- Target Windows 11 and keep the app runnable without an OpenAI connection.
- Treat coordinate reference systems, NoData, horizontal units, vertical units, and vertical datums as explicit metadata. Never invent missing metadata.
- Preserve provider downloads under `data/original/`; write previews and other derivatives under `data/processed/`.
- Keep raster reads bounded. The interactive viewer uses decimated grids; source files remain separate.
- Keep providers behind the adapter in `backend/app/providers/`.
- Add or update tests for bounding-box validation, NoData handling, and raster preview behavior when changing the processing pipeline.
- Do not commit downloaded elevation files, the SQLite database, or generated caches.
