import csv
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from statistics import mean, stdev

from .sensitivity_analysis import (
    INPUT_DIR,
    OUTPUT_DIR,
    REPORTS_DIR,
    LogRecord,
    parse_cleaned_file,
    select_cleaned_files,
    select_source,
)

SAMPLE_INTERVAL_MS = 20
WINDOW_BEFORE_S = 40
MAX_VALID_SR_LOAD = 500
TERMINAL_EVENTS = {"R", "E", "X"}
METADATA_FILE = INPUT_DIR / "motor_metadata.csv"
METADATA_FIELDS = [
    "Project",
    "Type",
    "Firmware",
    "Torque_Nm",
    "Sensitivity",
]
METADATA_CSV_FIELDS = METADATA_FIELDS

SUMMARY_FIELDS = [
    "File",
    *METADATA_FIELDS,
    "SR_Count",
    "Invalid_SR_Count",
    "Average_SR_Load",
    "Max_SR_Load",
    "P95_SR_Load",
    "SR_Load_STD",
    "Average_SR_Time_ms",
]
DETAIL_FIELDS = [
    "File",
    *METADATA_FIELDS,
    "Start_Index",
    "S_Index",
    "R_Index",
    "Status",
    "Reason",
    "Segment_Min",
    "Segment_Max",
    "Peak_Load",
    "SR_Time_ms",
]


@dataclass(frozen=True)
class SRSequence:
    file: str
    start_index: int
    s_index: int
    r_index: int
    status: str
    reason: str
    segment_min: int | None
    segment_max: int | None
    peak_load: int | None
    sr_time_ms: int
    metadata: tuple[str, ...] = ("", "", "", "", "")


@dataclass(frozen=True)
class MotorMetadata:
    project: str = ""
    type: str = ""
    firmware: str = ""
    torque_nm: str = ""
    sensitivity: str = ""

    def as_values(self) -> tuple[str, ...]:
        return (
            self.project,
            self.type,
            self.firmware,
            self.torque_nm,
            self.sensitivity,
        )


def percentile(values: list[int], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def analyze_records(
    records: list[LogRecord], file_name: str = ""
) -> list[SRSequence]:
    sequences = []
    active_s_index: int | None = None
    active_start_index: int | None = None

    for index, record in enumerate(records):
        terminal_events = [event for event in record.events if event in TERMINAL_EVENTS]
        if len(terminal_events) > 1:
            raise ValueError(
                f"Line {record.line_number}: multiple terminal events in one record"
            )

        if "S" in record.events:
            active_s_index = index
            active_start_index = max(0, index - WINDOW_BEFORE_S)

        if active_s_index is None or not terminal_events:
            continue

        terminal_event = terminal_events[0]
        if terminal_event == "R":
            segment = records[active_start_index : index + 1]
            sr_time_ms = (index - active_s_index) * SAMPLE_INTERVAL_MS

            if any(sample.ods == 0 for sample in segment):
                sequences.append(
                    SRSequence(
                        file=file_name,
                        start_index=active_start_index,
                        s_index=active_s_index,
                        r_index=index,
                        status="INVALID",
                        reason="ODS_RESET_0000",
                        segment_min=None,
                        segment_max=None,
                        peak_load=None,
                        sr_time_ms=sr_time_ms,
                    )
                )
            else:
                segment_values = [sample.ods for sample in segment]
                segment_min = min(segment_values)
                segment_max = max(segment_values)
                peak_load = segment_max - segment_min
                valid = peak_load <= MAX_VALID_SR_LOAD
                sequences.append(
                    SRSequence(
                        file=file_name,
                        start_index=active_start_index,
                        s_index=active_s_index,
                        r_index=index,
                        status="VALID" if valid else "INVALID",
                        reason="" if valid else "EXCESSIVE_LOAD",
                        segment_min=segment_min,
                        segment_max=segment_max,
                        peak_load=peak_load,
                        sr_time_ms=sr_time_ms,
                    )
                )

        active_s_index = None
        active_start_index = None

    return sequences


def _statistics_row(
    file_name: str,
    sequences: list[SRSequence],
    metadata: MotorMetadata = MotorMetadata(),
) -> dict[str, str | int | float]:
    valid_sequences = [sequence for sequence in sequences if sequence.status == "VALID"]
    times = [sequence.sr_time_ms for sequence in valid_sequences]

    row: dict[str, str | int | float] = {
        "File": file_name,
        **dict(zip(METADATA_FIELDS, metadata.as_values(), strict=True)),
        "SR_Count": len(valid_sequences),
        "Invalid_SR_Count": len(sequences) - len(valid_sequences),
        "Average_SR_Load": "",
        "Max_SR_Load": "",
        "P95_SR_Load": "",
        "SR_Load_STD": "",
        "Average_SR_Time_ms": "",
    }

    if not valid_sequences:
        return row

    valid_loads = []
    for sequence in valid_sequences:
        if sequence.peak_load is None:
            raise ValueError("A valid S-to-R sequence must have a peak load")
        valid_loads.append(sequence.peak_load)

    row.update(
        {
            "Average_SR_Load": round(mean(valid_loads), 2),
            "Max_SR_Load": max(valid_loads),
            "P95_SR_Load": round(percentile(valid_loads, 95), 2),
            "SR_Load_STD": (
                round(stdev(valid_loads), 2) if len(valid_loads) > 1 else 0
            ),
            "Average_SR_Time_ms": round(mean(times), 2),
        }
    )
    return row


def _source_folder_key(folder: str) -> str:
    folder_path = Path(folder)
    if folder_path.is_absolute() or ".." in folder_path.parts:
        raise ValueError(f"Folder path must be relative: {folder!r}")
    return "." if folder_path == Path(".") else folder_path.as_posix()


def read_motor_metadata(metadata_file: Path = METADATA_FILE) -> MotorMetadata | None:
    if not metadata_file.exists():
        return None

    with metadata_file.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None:
            raise ValueError(f"Metadata CSV is missing its header: {metadata_file}")

        duplicates = sorted(
            name for name in set(reader.fieldnames) if reader.fieldnames.count(name) > 1
        )
        if duplicates:
            raise ValueError(
                f"Metadata CSV has duplicate columns: {', '.join(duplicates)}"
            )

        missing_fields = [
            field for field in METADATA_CSV_FIELDS if field not in reader.fieldnames
        ]
        if missing_fields:
            raise ValueError(
                f"Metadata CSV is missing required columns: {', '.join(missing_fields)}"
            )
        unexpected_fields = [
            field for field in reader.fieldnames if field not in METADATA_CSV_FIELDS
        ]
        if unexpected_fields:
            raise ValueError(
                f"Metadata CSV has unexpected columns: {', '.join(unexpected_fields)}"
            )

        metadata_rows = []
        for row in reader:
            if not any((row.get(field) or "").strip() for field in METADATA_FIELDS):
                continue
            metadata_rows.append(
                MotorMetadata(
                    project=(row.get("Project") or "").strip(),
                    type=(row.get("Type") or "").strip(),
                    firmware=(row.get("Firmware") or "").strip(),
                    torque_nm=(row.get("Torque_Nm") or "").strip(),
                    sensitivity=(row.get("Sensitivity") or "").strip(),
                )
            )

    if len(metadata_rows) > 1:
        raise ValueError(
            f"{metadata_file}: expected at most one metadata row because the "
            "configuration applies to the selected folder."
        )
    return metadata_rows[0] if metadata_rows else None


def _prompt_manual_metadata(folder: str) -> MotorMetadata:
    print(f"\nMotor metadata for folder: {folder}")
    while True:
        choice = input("Enter metadata for this folder? [y/N]: ").strip().lower()
        if choice in {"", "n", "no"}:
            return MotorMetadata()
        if choice in {"y", "yes"}:
            values = {field: input(f"{field}: ").strip() for field in METADATA_FIELDS}
            return MotorMetadata(
                project=values["Project"],
                type=values["Type"],
                firmware=values["Firmware"],
                torque_nm=values["Torque_Nm"],
                sensitivity=values["Sensitivity"],
            )
        print("Enter Y or N.")


def resolve_motor_metadata(
    files: list[Path],
    source_dir: Path,
    *,
    metadata_file: Path = METADATA_FILE,
) -> dict[str, MotorMetadata]:
    shared_metadata = read_motor_metadata(metadata_file)
    selected_folders = sorted(
        {
            _source_folder_key(file_path.parent.relative_to(source_dir).as_posix())
            for file_path in files
        }
    )

    metadata_by_folder = {}
    for folder in selected_folders:
        folder_metadata_file = source_dir / folder / metadata_file.name
        if folder_metadata_file == metadata_file or not folder_metadata_file.exists():
            continue
        folder_metadata = read_motor_metadata(folder_metadata_file)
        if folder_metadata is not None:
            metadata_by_folder[folder] = folder_metadata

    unmatched_folders = [
        folder for folder in selected_folders if folder not in metadata_by_folder
    ]
    if len(selected_folders) == 1 and unmatched_folders and shared_metadata is not None:
        return {selected_folders[0]: shared_metadata}

    if len(selected_folders) > 1 and unmatched_folders and shared_metadata is not None:
        print(
            "Selected files span multiple folders; shared metadata does not "
            "identify the remaining folders. Enter metadata separately for each."
        )

    for folder in unmatched_folders:
        metadata_by_folder[folder] = _prompt_manual_metadata(folder)

    return metadata_by_folder


def _unique_report_paths(
    reports_dir: Path, timestamp: str
) -> tuple[Path, Path]:
    suffix = 1
    while True:
        numeric_suffix = "" if suffix == 1 else f"_{suffix:03d}"
        summary_path = reports_dir / (
            f"sensitivity_sr_summary_{timestamp}{numeric_suffix}.csv"
        )
        details_path = reports_dir / (
            f"sensitivity_sr_details_{timestamp}{numeric_suffix}.csv"
        )
        if not summary_path.exists() and not details_path.exists():
            return summary_path, details_path
        suffix += 1


def write_reports(
    summary_rows: list[dict[str, str | int | float]],
    sequences: list[SRSequence],
    reports_dir: Path,
    timestamp: str,
) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path, details_path = _unique_report_paths(reports_dir, timestamp)

    with summary_path.open("w", newline="", encoding="utf-8") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary_rows)

    with details_path.open("w", newline="", encoding="utf-8") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=DETAIL_FIELDS)
        writer.writeheader()
        writer.writerows(
            {
                "File": sequence.file,
                **dict(zip(METADATA_FIELDS, sequence.metadata)),
                "Start_Index": sequence.start_index,
                "S_Index": sequence.s_index,
                "R_Index": sequence.r_index,
                "Status": sequence.status,
                "Reason": sequence.reason,
                "Segment_Min": sequence.segment_min,
                "Segment_Max": sequence.segment_max,
                "Peak_Load": sequence.peak_load,
                "SR_Time_ms": sequence.sr_time_ms,
            }
            for sequence in sequences
        )

    return summary_path, details_path


def analyze_files(
    files: list[Path],
    *,
    output_dir: Path = OUTPUT_DIR,
    reports_dir: Path = REPORTS_DIR,
    timestamp: str | None = None,
    metadata_by_folder: dict[str, MotorMetadata] | None = None,
) -> tuple[
    list[dict[str, str | int | float]],
    list[SRSequence],
    tuple[Path, Path] | None,
]:
    summary_rows = []
    all_sequences = []
    folder_metadata = metadata_by_folder or {}

    for file_path in files:
        relative_file = str(file_path.relative_to(output_dir))
        relative_folder = _source_folder_key(
            file_path.parent.relative_to(output_dir).as_posix()
        )
        metadata = folder_metadata.get(relative_folder, MotorMetadata())
        file_sequences = analyze_records(
            parse_cleaned_file(file_path), file_name=relative_file
        )
        file_sequences = [
            replace(sequence, metadata=metadata.as_values())
            for sequence in file_sequences
        ]
        all_sequences.extend(file_sequences)
        summary_rows.append(_statistics_row(relative_file, file_sequences, metadata))

    if not all_sequences:
        return summary_rows, all_sequences, None

    pooled_row = _statistics_row("ALL_FILES_POOLED", all_sequences)
    summary_rows.append(pooled_row)
    report_paths = write_reports(
        summary_rows,
        all_sequences,
        reports_dir,
        timestamp or datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    return summary_rows, all_sequences, report_paths


def main() -> None:
    for directory in (OUTPUT_DIR, INPUT_DIR, REPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    source_dir = select_source()
    if source_dir is None:
        return
    files = select_cleaned_files(source_dir)
    if not files:
        return

    print(f"\nSource:\n{source_dir}")
    metadata_by_folder = resolve_motor_metadata(files, source_dir)
    _, sequences, report_paths = analyze_files(
        files,
        output_dir=source_dir,
        reports_dir=REPORTS_DIR,
        metadata_by_folder=metadata_by_folder,
    )

    valid_count = sum(sequence.status == "VALID" for sequence in sequences)
    invalid_count = len(sequences) - valid_count
    print("\nS-to-R mechanical analysis completed")
    print(f"Valid S-to-R sequences  : {valid_count}")
    print(f"Invalid S-to-R sequences: {invalid_count}")
    if report_paths is None:
        print("No S-to-R candidates; no reports were created.")
    else:
        print(f"\nSummary report:\n{report_paths[0]}")
        print(f"\nSequence details:\n{report_paths[1]}")
