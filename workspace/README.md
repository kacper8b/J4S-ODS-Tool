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
including their events. Each `S` starts a sequence; the first following `R`,
`E` or `X` closes it. Only an R-terminated sequence produces a measurement.
A newer `S` replaces an unfinished start. Sequences are not merged or extended,
and neighboring S-to-E sequences do not exclude an S-to-R measurement.
Obstacle measurement and independent slope analysis are unchanged.

The S reference is `S_ref = max(F[S-4:S])`, using exactly the four parsed
records immediately before S, including startup records when needed.
Only their maximum value is included with the S-to-R samples, not the entire
pre-S segment. Load is `max(S_ref, F[S..R]) - min(S_ref, F[S..R])`, with
both S and R included. These are filtered-signal units, not force, torque
or a direct measure of obstacle-detection sensitivity.
Measurements containing ODS `0` in S_ref or S..R are invalid
(`ODS_RESET_0000`), as are ranges greater than 500 (`EXCESSIVE_LOAD`).
A range of exactly 500 is accepted. Invalid measurements appear in details
and counts but not in load or time statistics. The startup exclusion and
rejection rules remain provisional. Internal zero-valued fragments do not
automatically start another 100-record startup exclusion.

The main menu offers obstacle measurement and S-to-R mechanical analysis
separately. Both can process all cleaned files, one selected file, or one
selected folder. Obstacle measurement writes valid measurements to CSV.
S-to-R analysis writes a per-file and pooled summary CSV plus one combined
sequence-details CSV when at least one measurement remains after startup exclusion,
even if all remaining measurements are invalid. Otherwise no reports are
created. Both report types go
to `sensitivity/output/`; names include a timestamp and gain a numeric suffix
if needed to avoid overwriting existing files. Reported time is nominally 20 ms
per parsed interval, from S to R; the four reference records are not included
in that duration. Cleaned logs have no timestamps to identify samples lost
before cleaning. Detail indices are zero-based: `Start_Index` identifies
the earliest maximum among the four S-reference records, while `S_Index`
and `R_Index` identify the sequence boundaries.

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

## Independent slope analysis

Main-menu option 4 detects downward slopes directly from the filtered signal,
without using recorded S/R markers as slope boundaries. It reuses the source,
file-selection and folder-metadata workflow of S-to-R analysis. Existing
analyses and source files are unchanged.

Main-menu option 5 configures the nine Independent Slope Analysis detection
parameters. The settings are shared across selected files and motor
configurations, persist between runs in
`sensitivity/independent_slope_parameters.json`, and are ignored by Git.
Choose whether to change the current values or restore defaults. If no settings
file exists, the documented defaults are used. Invalid settings are reported
instead of silently replaced. The confirmed 20 ms sample interval is fixed.

The intended scope is upward motor movement; "downward slope" refers to the
filtered ODS signal, not motor direction. Direction is not checked from the
input. ODS is the fourth hexadecimal field. Indices count parsed records, not
original text lines.

The first 100 parsed records are excluded. Recorded S-to-E sequences exclude
the interval from 100 records before their S through E, inclusive. Excluded
records and zero ODS values split the signal into separate eligible blocks.
Slopes cannot cross those boundaries.

Track a local peak (latest sample on an equal plateau) until a drop of at least
32 units confirms a candidate. Track its minimum and join smaller drops while
brief plateaus or rebounds remain below the ending criteria. A cumulative
decrease of at least 4 units updates the progress reference. After updating
progress, close on a rebound of at least 24 units from the minimum or more than
15 intervals without significant progress. Resume peak search at that closure
sample. The reported end is the first occurrence of the running minimum, not
the later closure sample.

After joining, accept a duration of at least 10 sample intervals and amplitude
from 32 through 500 units, inclusive. All thresholds are provisional. Typical
30-40-interval durations and recurrence around 120-130 intervals are not forced
by detection. Duration is nominally `(End_Index - Start_Index) * 20 ms`; missing
acquisitions cannot be inferred from cleaned rows.

Reports are `independent_slope_summary_<timestamp>.csv` (per-file and
`ALL_FILES_POOLED` amplitude/time statistics) and
`independent_slope_details_<timestamp>.csv` (metadata, zero-based start/end
indices, peak/minimum values, amplitude, time, status, reason and closure).
Both go to `sensitivity/output/` with a numeric suffix on name collisions.
Confirmed candidates failing duration/amplitude criteria remain in details and
invalid counts, but not in statistics. No confirmed candidates means no reports.
The pooled summary mixes all selected configurations.

Closure distinguishes `REBOUND`, `INACTIVITY` and `BLOCK_BOUNDARY` (excluded
data, zero ODS or end of file). A boundary-closed slope may still meet acceptance
criteria, but its physical ending is not confirmed; inspect these candidates
before interpreting them. Valid boundary-closed slopes currently contribute
to summary statistics; there is no separate boundary-statistics group. The
console reports the count of all boundary-closed candidates.

The 500-unit limit is on peak-to-minimum amplitude, not the absolute peak.
Length is measured in intervals: 10 intervals span 11 record positions.
Equal minima keep their first occurrence. New minimum/progress updates happen
before closure checks, and rebound takes precedence over inactivity. Small
fragments are joined only while the candidate remains active; closed candidates
are not merged retroactively. Internal zero values do not trigger another
100-record startup exclusion.

For example, a 300-unit decrease over 30 intervals is valid (600 ms); a
100-unit decrease over 9 intervals is too short, and a 501-unit decrease is
too large. A rebound of exactly 24 units closes an active candidate. Recorded
S/R markers cannot independently start or close one.

Independent duration measures peak-to-minimum; S-to-R duration measures first
S-to-last R, so these times are not interchangeable. Compare configurations
without mixing project, firmware or torque. Signal amplitudes are not physical
force or a direct percentage measure of obstacle-detection sensitivity.

## Torque vs Ucapa

Main-menu option 6 compares the mean value of the fourth cleaned column
(`wUCapFiltValue`) between two selected folders. Choose one source
(`parser/output/` or `sensitivity/input/`), then select two different displayed
top-level folders; each folder includes its nested subfolders. The same
start/end interval in seconds is applied from the beginning of every file.
Sample times are nominally `record index * 20 ms`, with both interval endpoints
included. Each folder mean pools all matching records across its files, giving
every record equal weight.

The console shows both means and the difference (second folder minus first) to
two decimal places. No CSV report is created. If either folder has no records
in the interval, the comparison is not calculated. Cleaned logs contain no
timestamps, so missing acquisitions cannot be identified.

## Previous folder layout

The old workspace-root `input/`, `output/`, `rejected/` and `reports/` folders
are no longer used by the application. Existing data was copied to the
corresponding parser folders and `sensitivity/output/` during this layout
change. After verifying that the copies matched, the old folders were removed.
Use only the module-specific folders above.
