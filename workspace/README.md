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

S-to-R mechanical analysis ignores the first 100 parsed records as startup,
including their events. It searches up to 40 records strictly before `S`, never
including startup records, for the highest peak confirmed by a drop of at least
16 ODS units within the next 10 records, no later than its first terminal `R`.
Equal confirmed peaks retain the first; consecutive decreases are not required.
The measurement segment starts at that peak and extends through up to 10
records after `R`. No rebound is required to accept a minimum.

If the first following `S` occurs within 10 records after `R` and ends with
another `R`, the sequences are merged and the window extends again from the
last `R`. Otherwise the window stops before that `S`. A newer `S` replaces an
unfinished start. For every S-to-E sequence, the interval from 100 records
before its `S` through its `E`, inclusive, is protected: any overlapping
mechanical measurement is omitted entirely, not trimmed. Obstacle measurement
is unchanged.

Load is the maximum minus the minimum ODS value across the entire extended
segment, not just the difference between the S and R samples. These are signal
units, not force, torque or a direct measure of obstacle-detection sensitivity.
Measurements without a confirmed peak are invalid (`NO_CONFIRMED_PEAK`), as
are segments containing ODS `0` (`ODS_RESET_0000`) or with a load greater than
500 (`EXCESSIVE_LOAD`). Invalid measurements appear in details and counts but
not in load or time statistics. The analysis parameters and rejection rules
remain provisional. Internal zero-valued fragments do not automatically start
another 100-record startup exclusion.

The main menu offers obstacle measurement and S-to-R mechanical analysis
separately. Both can process all cleaned files, one selected file, or one
selected folder. Obstacle measurement writes valid measurements to CSV.
S-to-R analysis writes a per-file and pooled summary CSV plus one combined
sequence-details CSV when at least one measurement remains after exclusions,
even if all remaining measurements are invalid. Otherwise no reports are
created. Both report types go
to `sensitivity/output/`; names include a timestamp and gain a numeric suffix
if needed to avoid overwriting existing files. Reported time is nominally 20 ms
per parsed interval, from the first S to the last merged R; the pre-S peak and
post-R window are not included in that duration. Cleaned logs have no timestamps
to identify samples lost before cleaning. Detail indices are zero-based:
`Start_Index` is the confirmed peak, `S_Index` the first S and `R_Index` the last R.

The `ALL_FILES_POOLED` summary combines all selected configurations; it does not
group by project, firmware, torque, type or sensitivity. There is no sensitivity
selection. Select comparable inputs before interpreting the pooled statistics.

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
