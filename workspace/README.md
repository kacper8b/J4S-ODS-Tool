# J4S ODS Tool Workspace

Put motor log `.txt` files directly in `input/` or place them in folders there,
then run `run.bat`. The parser can process all files, one loose file, or one
selected folder. Folder selections include nested subfolders and provide an
option to return to the main menu.

Cleaned files ready for further analysis are written to `output/` while
preserving the input folder structure. Rejected-line files are written
directly in `rejected/` and are prefixed with the relative input folder path
to keep similarly named inputs distinct. The menu can optionally add the
current date (`YYYY-MM-DD`) to output filenames. The `reports/` folder is
reserved for future analysis reports.

The workspace folders are kept by Git, but their contents are ignored so that
input data and generated files are not committed.
