# J4S ODS Tool Workspace

Put motor log `.txt` files directly in `parser/input/` or place them in folders there,
then run `run.bat`. The parser can process all files, one loose file, or one
selected folder. Folder selections include nested subfolders and provide an
option to return to the main menu.

## Working folders

```text
parser/
  input/       Raw motor logs
  output/      Cleaned logs
  rejected/    Rejected lines
sensitivity/
  input/       Dedicated cleaned logs for analysis
  output/      Analysis reports
```

The analysis first asks whether to read directly from `parser/output/` (without
copying files) or from the dedicated `sensitivity/input/`. Both sources require
normalized seven-column `*_cleaned.txt` files, not raw logs. To undo a source
choice, use Back in the file-selection menu and choose the analysis again;
the choice does not modify or copy input data.

The initial
obstacle analysis pairs each `S` with the first following `R`, `E`, or `X`;
only an `E`-terminated sequence produces a measurement. Its reference is the
maximum ODS value from the four records immediately before `S`, and the
measurement is `S_ref - ODS(E)`. Reports always go to `sensitivity/output/` with one
row per valid obstacle measurement. The analysis menu can process all cleaned
files, one selected file, or one selected folder.

Cleaned files ready for further analysis are written to `parser/output/` while
preserving the input folder structure. Rejected-line files are written
directly in `parser/rejected/` and are prefixed with the relative input folder path
to keep similarly named inputs distinct. The menu can optionally add the
current date (`YYYY-MM-DD`) to output filenames.

The workspace folders are kept by Git, but their contents are ignored so that
input data and generated files are not committed.

## Previous folder layout

The old workspace-root `input/`, `output/`, `rejected/` and `reports/` folders
are no longer used by the application. Existing data was copied to the
corresponding parser folders and `sensitivity/output/` during this layout
change. After verifying that the copies matched, the old folders were removed.
Use only the module-specific folders above.
