import csv
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

from .sensitivity_analysis import (
    INPUT_DIR,
    REPORTS_DIR,
    TERMINAL_EVENTS,
    LogRecord,
    parse_cleaned_file,
    select_cleaned_files,
    select_source,
)
from .sr_mechanical_analysis import (
    METADATA_FIELDS,
    MotorMetadata,
    percentile,
    resolve_motor_metadata,
)

SAMPLE_INTERVAL_MS = 20
STARTUP_SAMPLES = 100
EXCLUSION_BEFORE_OBSTACLE_S = 100
START_DROP = 16
PROGRESS_DROP = 4
MAX_IDLE_INTERVALS = 15
END_REBOUND = 24
MIN_DURATION_INTERVALS = 10
MIN_AMPLITUDE = 32
MAX_AMPLITUDE = 500

SUMMARY_FIELDS = [
    "File", *METADATA_FIELDS, "Slope_Count", "Invalid_Slope_Count",
    "Average_Amplitude", "Max_Amplitude", "P95_Amplitude", "Amplitude_STD",
    "Average_Duration_ms",
]
DETAIL_FIELDS = [
    "File", *METADATA_FIELDS, "Start_Index", "End_Index", "Peak_Value",
    "Minimum_Value", "Amplitude", "Duration_ms", "Status", "Reason", "Closure",
]


@dataclass(frozen=True)
class SlopeMeasurement:
    file: str
    start_index: int
    end_index: int
    peak_value: int
    minimum_value: int
    amplitude: int
    duration_ms: int
    status: str
    reason: str
    closure: str
    metadata: tuple[str, ...] = ("", "", "", "", "")


def _excluded_records(records: list[LogRecord]) -> list[bool]:
    excluded = [index < STARTUP_SAMPLES or record.ods == 0
                for index, record in enumerate(records)]
    active_s: int | None = None
    for index, record in enumerate(records):
        if index < STARTUP_SAMPLES:
            continue
        terminals = [event for event in record.events if event in TERMINAL_EVENTS]
        if len(terminals) > 1:
            raise ValueError(
                f"Line {record.line_number}: multiple terminal events in one record"
            )
        if "S" in record.events:
            active_s = index
        if active_s is not None and terminals:
            if terminals[0] == "E":
                start = max(0, active_s - EXCLUSION_BEFORE_OBSTACLE_S)
                excluded[start : index + 1] = [True] * (index + 1 - start)
            active_s = None
    return excluded


def _measurement(
    records: list[LogRecord], peak: int, minimum: int, file_name: str, closure: str
) -> SlopeMeasurement:
    intervals = minimum - peak
    amplitude = records[peak].ods - records[minimum].ods
    reasons = []
    if intervals < MIN_DURATION_INTERVALS:
        reasons.append("TOO_SHORT")
    if amplitude < MIN_AMPLITUDE:
        reasons.append("INSUFFICIENT_AMPLITUDE")
    if amplitude > MAX_AMPLITUDE:
        reasons.append("EXCESSIVE_AMPLITUDE")
    return SlopeMeasurement(
        file=file_name,
        start_index=peak,
        end_index=minimum,
        peak_value=records[peak].ods,
        minimum_value=records[minimum].ods,
        amplitude=amplitude,
        duration_ms=intervals * SAMPLE_INTERVAL_MS,
        status="INVALID" if reasons else "VALID",
        reason=";".join(reasons),
        closure=closure,
    )


def analyze_records(
    records: list[LogRecord], file_name: str = ""
) -> list[SlopeMeasurement]:
    excluded = _excluded_records(records)
    measurements = []
    peak: int | None = None
    minimum: int | None = None
    progress: int | None = None

    for index, record in enumerate(records):
        if excluded[index]:
            if peak is not None and minimum is not None:
                measurements.append(
                    _measurement(records, peak, minimum, file_name, "BLOCK_BOUNDARY")
                )
            peak = minimum = progress = None
            continue
        if peak is None:
            peak = index
            continue
        if minimum is None:
            if record.ods >= records[peak].ods:
                peak = index
            elif records[peak].ods - record.ods >= START_DROP:
                minimum = progress = index
            continue

        if progress is None:
            raise ValueError("An active slope must have a progress reference")
        if record.ods < records[minimum].ods:
            minimum = index
        if records[progress].ods - records[minimum].ods >= PROGRESS_DROP:
            progress = minimum

        closure = ""
        if record.ods - records[minimum].ods >= END_REBOUND:
            closure = "REBOUND"
        elif index - progress > MAX_IDLE_INTERVALS:
            closure = "INACTIVITY"
        if closure:
            measurements.append(
                _measurement(records, peak, minimum, file_name, closure)
            )
            peak = index
            minimum = progress = None

    if peak is not None and minimum is not None:
        measurements.append(
            _measurement(records, peak, minimum, file_name, "BLOCK_BOUNDARY")
        )
    return measurements


def _statistics_row(
    file_name: str,
    measurements: list[SlopeMeasurement],
    metadata: MotorMetadata = MotorMetadata(),
) -> dict[str, str | int | float]:
    valid = [measurement for measurement in measurements if measurement.status == "VALID"]
    row: dict[str, str | int | float] = {
        "File": file_name,
        **dict(zip(METADATA_FIELDS, metadata.as_values(), strict=True)),
        "Slope_Count": len(valid),
        "Invalid_Slope_Count": len(measurements) - len(valid),
        "Average_Amplitude": "",
        "Max_Amplitude": "",
        "P95_Amplitude": "",
        "Amplitude_STD": "",
        "Average_Duration_ms": "",
    }
    if valid:
        amplitudes = [measurement.amplitude for measurement in valid]
        row.update(
            Average_Amplitude=round(mean(amplitudes), 2),
            Max_Amplitude=max(amplitudes),
            P95_Amplitude=round(percentile(amplitudes, 95), 2),
            Amplitude_STD=round(stdev(amplitudes), 2) if len(valid) > 1 else 0,
            Average_Duration_ms=round(mean(m.duration_ms for m in valid), 2),
        )
    return row


def write_reports(
    rows: list[dict[str, str | int | float]],
    measurements: list[SlopeMeasurement],
    reports_dir: Path,
    timestamp: str,
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        ending = "" if suffix == 1 else f"_{suffix:03d}"
        summary = reports_dir / f"independent_slope_summary_{timestamp}{ending}.csv"
        details = reports_dir / f"independent_slope_details_{timestamp}{ending}.csv"
        if not summary.exists() and not details.exists():
            break
        suffix += 1
    with summary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    with details.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(
            {
                "File": m.file,
                **dict(zip(METADATA_FIELDS, m.metadata, strict=True)),
                "Start_Index": m.start_index,
                "End_Index": m.end_index,
                "Peak_Value": m.peak_value,
                "Minimum_Value": m.minimum_value,
                "Amplitude": m.amplitude,
                "Duration_ms": m.duration_ms,
                "Status": m.status,
                "Reason": m.reason,
                "Closure": m.closure,
            }
            for m in measurements
        )
    return summary, details


def analyze_files(
    files: list[Path],
    *,
    source_dir: Path = INPUT_DIR,
    reports_dir: Path = REPORTS_DIR,
    metadata_by_folder: dict[str, MotorMetadata] | None = None,
    timestamp: str | None = None,
) -> tuple[
    list[dict[str, str | int | float]],
    list[SlopeMeasurement],
    tuple[Path, Path] | None,
]:
    rows = []
    measurements = []
    folder_metadata = metadata_by_folder or {}
    for path in files:
        file_name = str(path.relative_to(source_dir))
        folder = path.parent.relative_to(source_dir).as_posix()
        metadata = folder_metadata.get(folder, MotorMetadata())
        found = [
            replace(m, metadata=metadata.as_values())
            for m in analyze_records(parse_cleaned_file(path), file_name)
        ]
        measurements.extend(found)
        rows.append(_statistics_row(file_name, found, metadata))
    if not measurements:
        return rows, measurements, None
    rows.append(_statistics_row("ALL_FILES_POOLED", measurements))
    paths = write_reports(
        rows, measurements, reports_dir,
        timestamp or datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    return rows, measurements, paths


def main() -> None:
    source = select_source()
    if source is None:
        return
    files = select_cleaned_files(source)
    if not files:
        return
    print(f"\nSource:\n{source}")
    metadata = resolve_motor_metadata(files, source)
    _, measurements, reports = analyze_files(
        files, source_dir=source, metadata_by_folder=metadata,
    )
    valid = sum(m.status == "VALID" for m in measurements)
    print("\nIndependent slope analysis completed")
    print(f"Valid slopes  : {valid}")
    print(f"Invalid slopes: {len(measurements) - valid}")
    print(
        "Slopes closed at a block boundary (end not confirmed): "
        f"{sum(m.closure == 'BLOCK_BOUNDARY' for m in measurements)}"
    )
    if reports is None:
        print("No slope candidates; no reports were created.")
    else:
        print(f"\nSummary report:\n{reports[0]}")
        print(f"\nSlope details:\n{reports[1]}")
