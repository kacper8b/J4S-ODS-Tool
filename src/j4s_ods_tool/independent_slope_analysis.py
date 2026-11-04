import csv
import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

from .sensitivity_analysis import (
    INPUT_DIR,
    REPORTS_DIR,
    SENSITIVITY_DIR,
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
PARAMETERS_PATH = SENSITIVITY_DIR / "independent_slope_parameters.json"


@dataclass(frozen=True)
class SlopeParameters:
    startup_samples: int = 100
    exclusion_before_obstacle_s: int = 100
    start_drop: int = 32
    progress_drop: int = 4
    max_idle_intervals: int = 15
    end_rebound: int = 24
    min_duration_intervals: int = 10
    min_amplitude: int = 32
    max_amplitude: int = 500


DEFAULT_PARAMETERS = SlopeParameters()
PARAMETER_LABELS = (
    ("startup_samples", "Startup exclusion (records)"),
    ("exclusion_before_obstacle_s", "Obstacle protection before S (records)"),
    ("start_drop", "Start confirmation drop (ODS units)"),
    ("progress_drop", "Significant progress drop (ODS units)"),
    ("max_idle_intervals", "Maximum inactivity (intervals)"),
    ("end_rebound", "Ending rebound (ODS units)"),
    ("min_duration_intervals", "Minimum length (intervals)"),
    ("min_amplitude", "Minimum amplitude (ODS units)"),
    ("max_amplitude", "Maximum amplitude (ODS units)"),
)

SUMMARY_FIELDS = [
    "File", *METADATA_FIELDS, "Slope_Count", "Invalid_Slope_Count",
    "Average_Amplitude", "Max_Amplitude", "P95_Amplitude", "Amplitude_STD",
    "Average_Duration_ms",
]
DETAIL_FIELDS = [
    "File", *METADATA_FIELDS, "Start_Index", "End_Index", "Peak_Value",
    "Minimum_Value", "Amplitude", "Duration_ms", "Status", "Reason", "Closure",
]


def validate_parameters(parameters: SlopeParameters) -> SlopeParameters:
    for name, value in asdict(parameters).items():
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
    if parameters.max_amplitude < parameters.min_amplitude:
        raise ValueError("max_amplitude must be greater than or equal to min_amplitude")
    return parameters


def load_parameters(path: Path = PARAMETERS_PATH) -> SlopeParameters:
    if not path.exists():
        return DEFAULT_PARAMETERS
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} contains invalid JSON: {error}") from error
    if not isinstance(values, dict):
        raise ValueError(f"{path} must contain a JSON object")

    expected = set(asdict(DEFAULT_PARAMETERS))
    missing = expected - values.keys()
    extra = values.keys() - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing: {', '.join(sorted(missing))}")
        if extra:
            details.append(f"unexpected: {', '.join(sorted(extra))}")
        raise ValueError(f"{path} has invalid parameter fields ({'; '.join(details)})")
    return validate_parameters(SlopeParameters(**values))


def save_parameters(parameters: SlopeParameters, path: Path = PARAMETERS_PATH) -> None:
    validate_parameters(parameters)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(path.name + ".tmp")
    temporary_path.write_text(
        json.dumps(asdict(parameters), indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def configure_parameters(path: Path = PARAMETERS_PATH) -> None:
    try:
        current = load_parameters(path)
    except ValueError as error:
        print(f"\nInvalid independent slope settings: {error}")
        choice = input("1 - Restore defaults, 0 - Back\nChoice: ").strip()
        if choice == "1":
            save_parameters(DEFAULT_PARAMETERS, path)
            print("Default parameters saved.")
        return

    while True:
        print("\nIndependent slope parameters:")
        for name, label in PARAMETER_LABELS:
            print(f"{label}: {getattr(current, name)}")
        print("1 - Change parameters")
        print("2 - Restore defaults")
        print("0 - Back")
        choice = input("\nChoice: ").strip()

        if choice == "1":
            values = {}
            for name, label in PARAMETER_LABELS:
                while True:
                    answer = input(f"{label} [{getattr(current, name)}]: ").strip()
                    if not answer:
                        values[name] = getattr(current, name)
                        break
                    try:
                        values[name] = int(answer)
                    except ValueError:
                        print("Enter a whole number.")
                        continue
                    break
            try:
                updated = validate_parameters(SlopeParameters(**values))
            except ValueError as error:
                print(f"Invalid parameters: {error}")
                continue
            save_parameters(updated, path)
            current = updated
            print("Parameters saved.")
        elif choice == "2":
            if input("Restore all default parameters? [y/N]: ").strip().lower() == "y":
                save_parameters(DEFAULT_PARAMETERS, path)
                current = DEFAULT_PARAMETERS
                print("Default parameters saved.")
        elif choice == "0":
            return
        else:
            print("Unknown option.")


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


def _excluded_records(
    records: list[LogRecord],
    parameters: SlopeParameters = DEFAULT_PARAMETERS,
) -> list[bool]:
    excluded = [index < parameters.startup_samples or record.ods == 0
                for index, record in enumerate(records)]
    active_s: int | None = None
    for index, record in enumerate(records):
        if index < parameters.startup_samples:
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
                start = max(0, active_s - parameters.exclusion_before_obstacle_s)
                excluded[start : index + 1] = [True] * (index + 1 - start)
            active_s = None
    return excluded


def _measurement(
    records: list[LogRecord],
    peak: int,
    minimum: int,
    file_name: str,
    closure: str,
    parameters: SlopeParameters = DEFAULT_PARAMETERS,
) -> SlopeMeasurement:
    intervals = minimum - peak
    amplitude = records[peak].ods - records[minimum].ods
    reasons = []
    if intervals < parameters.min_duration_intervals:
        reasons.append("TOO_SHORT")
    if amplitude < parameters.min_amplitude:
        reasons.append("INSUFFICIENT_AMPLITUDE")
    if amplitude > parameters.max_amplitude:
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
    records: list[LogRecord],
    file_name: str = "",
    parameters: SlopeParameters = DEFAULT_PARAMETERS,
) -> list[SlopeMeasurement]:
    validate_parameters(parameters)
    excluded = _excluded_records(records, parameters)
    measurements = []
    peak: int | None = None
    minimum: int | None = None
    progress: int | None = None

    for index, record in enumerate(records):
        if excluded[index]:
            if peak is not None and minimum is not None:
                measurements.append(
                    _measurement(
                        records, peak, minimum, file_name, "BLOCK_BOUNDARY", parameters
                    )
                )
            peak = minimum = progress = None
            continue
        if peak is None:
            peak = index
            continue
        if minimum is None:
            if record.ods >= records[peak].ods:
                peak = index
            elif records[peak].ods - record.ods >= parameters.start_drop:
                minimum = progress = index
            continue

        if progress is None:
            raise ValueError("An active slope must have a progress reference")
        if record.ods < records[minimum].ods:
            minimum = index
        if records[progress].ods - records[minimum].ods >= parameters.progress_drop:
            progress = minimum

        closure = ""
        if record.ods - records[minimum].ods >= parameters.end_rebound:
            closure = "REBOUND"
        elif index - progress > parameters.max_idle_intervals:
            closure = "INACTIVITY"
        if closure:
            measurements.append(
                _measurement(records, peak, minimum, file_name, closure, parameters)
            )
            peak = index
            minimum = progress = None

    if peak is not None and minimum is not None:
        measurements.append(
            _measurement(
                records, peak, minimum, file_name, "BLOCK_BOUNDARY", parameters
            )
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
    parameters: SlopeParameters = DEFAULT_PARAMETERS,
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
            for m in analyze_records(parse_cleaned_file(path), file_name, parameters)
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
    try:
        parameters = load_parameters()
    except ValueError as error:
        print(f"\nInvalid independent slope settings: {error}")
        return
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
        parameters=parameters,
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
