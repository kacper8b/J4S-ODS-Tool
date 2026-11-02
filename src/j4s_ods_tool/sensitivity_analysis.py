import csv
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .txt_parser import OUTPUT_DIR, WORKSPACE_DIR

SENSITIVITY_DIR = WORKSPACE_DIR / "sensitivity"
INPUT_DIR = SENSITIVITY_DIR / "input"
REPORTS_DIR = SENSITIVITY_DIR / "output"
PARSER_SYMBOLS = {"S", "R", "E", "N", "X", "Y"}
TERMINAL_EVENTS = {"R", "E", "X"}
REPORT_FIELDS = [
    "File",
    "Cleaned_S_Line",
    "Cleaned_E_Line",
    "S_Ref",
    "ODS_E",
    "Obstacle_Load",
]


@dataclass(frozen=True)
class LogRecord:
    line_number: int
    ods: int
    events: tuple[str, ...]


@dataclass(frozen=True)
class ObstacleMeasurement:
    file: str
    s_line: int
    e_line: int
    s_reference: int
    e_ods: int

    @property
    def load(self) -> int:
        return self.s_reference - self.e_ods


@dataclass
class AnalysisSummary:
    sequences_started: int = 0
    terminated_by_r: int = 0
    terminated_by_x: int = 0
    e_without_reference: int = 0
    incomplete_sequences: int = 0
    measurements: list[ObstacleMeasurement] = field(default_factory=list)


def parse_cleaned_file(file_path: Path) -> list[LogRecord]:
    records = []

    with file_path.open("r", encoding="utf-8") as cleaned_file:
        for line_number, line in enumerate(cleaned_file, start=1):
            if not line.strip():
                continue

            columns = line.rstrip("\r\n").split("\t")
            if len(columns) != 7:
                raise ValueError(
                    f"{file_path}:{line_number}: expected 7 tab-separated fields"
                )

            try:
                ods = int(columns[3], 16)
            except ValueError as error:
                raise ValueError(
                    f"{file_path}:{line_number}: invalid hexadecimal ODS value "
                    f"{columns[3]!r}"
                ) from error

            events = tuple(symbol for symbol in columns[5:7] if symbol)
            invalid_symbols = [
                symbol for symbol in events if symbol not in PARSER_SYMBOLS
            ]
            if invalid_symbols:
                raise ValueError(
                    f"{file_path}:{line_number}: unrecognized event symbol(s): "
                    f"{', '.join(invalid_symbols)}"
                )

            records.append(LogRecord(line_number, ods, events))

    return records


def analyze_records(records: list[LogRecord]) -> AnalysisSummary:
    summary = AnalysisSummary()
    active_start: LogRecord | None = None
    active_reference: int | None = None

    for index, record in enumerate(records):
        if "S" in record.events:
            if active_start is not None:
                summary.incomplete_sequences += 1

            summary.sequences_started += 1
            active_start = record
            active_reference = (
                max(previous.ods for previous in records[index - 4 : index])
                if index >= 4
                else None
            )

        terminal_events = [event for event in record.events if event in TERMINAL_EVENTS]
        if len(terminal_events) > 1:
            raise ValueError(
                f"Line {record.line_number}: multiple terminal events in one record"
            )

        if active_start is None or not terminal_events:
            continue

        terminal_event = terminal_events[0]
        if terminal_event == "R":
            summary.terminated_by_r += 1
        elif terminal_event == "X":
            summary.terminated_by_x += 1
        elif active_reference is None:
            summary.e_without_reference += 1
        else:
            summary.measurements.append(
                ObstacleMeasurement(
                    file="",
                    s_line=active_start.line_number,
                    e_line=record.line_number,
                    s_reference=active_reference,
                    e_ods=record.ods,
                )
            )

        active_start = None
        active_reference = None

    if active_start is not None:
        summary.incomplete_sequences += 1

    return summary


def select_source() -> Path | None:
    while True:
        print("\nAnalysis source:")
        print(f"1 - Parser output ({OUTPUT_DIR})")
        print(f"2 - Dedicated sensitivity input ({INPUT_DIR})")
        print("0 - Back")
        choice = input("\nSource choice: ").strip()
        if choice == "1":
            return OUTPUT_DIR
        if choice == "2":
            return INPUT_DIR
        if choice == "0":
            return None
        print("Unknown option.")


def select_cleaned_files(output_dir: Path = OUTPUT_DIR) -> list[Path] | None:
    files = sorted(output_dir.rglob("*_cleaned.txt"))
    if not files:
        print(f"\nNo cleaned TXT files found in:\n{output_dir}")
        return None

    folders = sorted(path for path in output_dir.iterdir() if path.is_dir())
    while True:
        print("\nCleaned files:")
        print(f"1 - All files ({len(files)})")
        print(f"2 - One file ({len(files)})")
        if folders:
            print(f"3 - One folder ({len(folders)})")
        print("0 - Back")
        choice = input("\nChoice: ").strip()

        if choice == "1":
            return files
        if choice == "2":
            for index, file_path in enumerate(files, start=1):
                print(f"{index}. {file_path.relative_to(output_dir)}")
            try:
                selected_index = int(input("\nChoose a file number: "))
            except ValueError:
                print("Enter a number.")
                continue
            if 1 <= selected_index <= len(files):
                return [files[selected_index - 1]]
            print("Invalid number.")
            continue
        if choice == "3" and folders:
            for index, folder in enumerate(folders, start=1):
                print(f"{index}. {folder.relative_to(output_dir)}")
            try:
                selected_index = int(input("\nChoose a folder number: "))
            except ValueError:
                print("Enter a number.")
                continue
            if not 1 <= selected_index <= len(folders):
                print("Invalid number.")
                continue
            selected_files = sorted(folders[selected_index - 1].rglob("*_cleaned.txt"))
            if selected_files:
                return selected_files
            print("No cleaned TXT files found in the selected folder.")
            continue
        if choice == "0":
            return None
        print("Unknown option.")


def write_report(
    measurements: list[ObstacleMeasurement],
    reports_dir: Path,
    timestamp: str,
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"sensitivity_obstacle_{timestamp}.csv"
    suffix = 2
    while report_path.exists():
        report_path = reports_dir / f"sensitivity_obstacle_{timestamp}_{suffix:03d}.csv"
        suffix += 1

    with report_path.open("w", newline="", encoding="utf-8") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for measurement in measurements:
            writer.writerow(
                {
                    "File": measurement.file,
                    "Cleaned_S_Line": measurement.s_line,
                    "Cleaned_E_Line": measurement.e_line,
                    "S_Ref": measurement.s_reference,
                    "ODS_E": measurement.e_ods,
                    "Obstacle_Load": measurement.load,
                }
            )

    return report_path


def analyze_files(
    files: list[Path],
    *,
    output_dir: Path = OUTPUT_DIR,
    reports_dir: Path = REPORTS_DIR,
    timestamp: str | None = None,
) -> tuple[AnalysisSummary, Path | None]:
    combined_summary = AnalysisSummary()

    for file_path in files:
        summary = analyze_records(parse_cleaned_file(file_path))
        combined_summary.sequences_started += summary.sequences_started
        combined_summary.terminated_by_r += summary.terminated_by_r
        combined_summary.terminated_by_x += summary.terminated_by_x
        combined_summary.e_without_reference += summary.e_without_reference
        combined_summary.incomplete_sequences += summary.incomplete_sequences
        relative_file = str(file_path.relative_to(output_dir))
        combined_summary.measurements.extend(
            ObstacleMeasurement(
                file=relative_file,
                s_line=measurement.s_line,
                e_line=measurement.e_line,
                s_reference=measurement.s_reference,
                e_ods=measurement.e_ods,
            )
            for measurement in summary.measurements
        )

    if not combined_summary.measurements:
        return combined_summary, None

    report_path = write_report(
        combined_summary.measurements,
        reports_dir,
        timestamp or datetime.now().strftime("%Y%m%d_%H%M%S"),
    )
    return combined_summary, report_path


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
    summary, report_path = analyze_files(
        files, output_dir=source_dir, reports_dir=REPORTS_DIR
    )
    print("\nAnalysis completed")
    print(f"Sequences started              : {summary.sequences_started}")
    print(f"Sequences terminated by R      : {summary.terminated_by_r}")
    print(f"Sequences terminated by X      : {summary.terminated_by_x}")
    print(f"E events without four samples  : {summary.e_without_reference}")
    print(f"Incomplete sequences           : {summary.incomplete_sequences}")
    print(f"Obstacle measurements          : {len(summary.measurements)}")
    if report_path is None:
        print("No valid E obstacle measurements; no report was created.")
    else:
        print(f"\nReport:\n{report_path}")
