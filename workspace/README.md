# J4S ODS Tool Workspace

Put motor log `.txt` files directly in `input/` or place them in folders there,
then run `run.bat`. The parser can process all files, one loose file, or one
selected folder. Folder selections include nested subfolders and provide an
option to return to the main menu.

Processed files and rejected-line files are written together directly in
`output/`. Outputs from folders are prefixed with the relative folder path
(folder names joined with underscores) to keep similarly named inputs distinct.
The `reports/` folder is reserved for future analysis reports.

The workspace folders are kept by Git, but their contents are ignored so that
input data and generated files are not committed.
