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

Obstacle measurement pairs each `S` with the first following `R`, `E`, or `X`;
only an `E`-terminated sequence produces a measurement. Its reference is the
maximum ODS value from the four records immediately before `S`, and the
measurement is `S_ref - ODS(E)`. Its report has one row per valid obstacle
measurement.

S-to-R mechanical analysis measures the peak-to-peak ODS range from up to 40
records before `S` through the terminating `R`. Sequences terminated by `E` or
`X` do not produce a candidate, and a newer `S` replaces an unfinished start.
Segments containing ODS `0` or with a peak load greater than 500 are marked
invalid. These two rejection rules remain provisional. Reported S-to-R time is
nominally `(R index - S index) * 20 ms`; cleaned files have no timestamps to
identify samples lost before cleaning.

The main menu offers obstacle measurement and S-to-R mechanical analysis
separately. Both can process all cleaned files, one selected file, or one
selected folder. Obstacle measurement writes valid measurements to CSV.
S-to-R analysis writes a per-file and pooled summary CSV plus one combined
sequence-details CSV when at least one candidate exists. Both report types go
to `sensitivity/output/`; names include a timestamp and gain a numeric suffix
if needed to avoid overwriting existing files. Reported time is nominally 20 ms
per parsed interval; cleaned logs have no timestamps to identify samples lost
before cleaning.

S-to-R analysis is for upward movement (`Up`) only. Reports identify each motor
configuration with `Project`, `Type`, `Firmware`, `Torque_Nm`, and
`Sensitivity` columns; direction is fixed and is not included as a column.
`Type` is `SLE` or `Standard`; each folder represents one version/configuration.
Each configuration folder in `sensitivity/input/` can contain its own
`motor_metadata.csv` with one metadata row; that row is used for files in that
folder. The tracked `sensitivity/input/motor_metadata.csv` is a template and
fallback for a single selected folder without its own metadata file, including
files selected from `parser/output/`. If metadata is missing for any selected
folder, the application asks whether to enter it; declining leaves those
report fields blank. Folder structure is preserved between parser input and
output.

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
