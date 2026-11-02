import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from j4s_ods_tool import __main__ as app
from j4s_ods_tool import sr_mechanical_analysis
from j4s_ods_tool.sensitivity_analysis import LogRecord
from j4s_ods_tool.sr_mechanical_analysis import (
    METADATA_CSV_FIELDS,
    METADATA_FIELDS,
    MotorMetadata,
    analyze_files,
    analyze_records,
    read_motor_metadata,
    resolve_motor_metadata,
)


def record(line_number: int, ods: int, *events: str) -> LogRecord:
    return LogRecord(line_number, ods, events)


class AnalyzeRecordsTests(unittest.TestCase):
    def test_measures_peak_to_peak_load_in_pre_s_window_and_reports_s_to_r_time(self) -> None:
        records = [record(index + 1, 100) for index in range(45)]
        records[0] = record(1, 900)
        records[41] = record(42, 150, "S")
        records[43] = record(44, 80, "R")

        sequences = analyze_records(records, file_name="run_cleaned.txt")

        self.assertEqual(len(sequences), 1)
        sequence = sequences[0]
        self.assertEqual(sequence.file, "run_cleaned.txt")
        self.assertEqual(sequence.start_index, 1)
        self.assertEqual(sequence.s_index, 41)
        self.assertEqual(sequence.r_index, 43)
        self.assertEqual(sequence.segment_min, 80)
        self.assertEqual(sequence.segment_max, 150)
        self.assertEqual(sequence.peak_load, 70)
        self.assertEqual(sequence.sr_time_ms, 40)
        self.assertEqual(sequence.status, "VALID")

    def test_e_and_x_close_sequences_without_s_to_r_candidates(self) -> None:
        sequences = analyze_records(
            [
                record(1, 100, "S"),
                record(2, 90, "E"),
                record(3, 100, "S"),
                record(4, 90, "X"),
                record(5, 80, "R"),
            ]
        )

        self.assertEqual(sequences, [])

    def test_new_s_replaces_previous_start(self) -> None:
        sequences = analyze_records(
            [
                record(1, 100, "S"),
                record(2, 110),
                record(3, 120, "S"),
                record(4, 90, "R"),
            ]
        )

        self.assertEqual(len(sequences), 1)
        self.assertEqual(sequences[0].s_index, 2)
        self.assertEqual(sequences[0].r_index, 3)

    def test_same_record_s_and_r_is_a_zero_time_candidate(self) -> None:
        sequence = analyze_records([record(1, 100, "S", "R")])[0]

        self.assertEqual(sequence.s_index, sequence.r_index)
        self.assertEqual(sequence.sr_time_ms, 0)
        self.assertEqual(sequence.status, "VALID")

    def test_zero_ods_and_load_above_500_are_invalid(self) -> None:
        zero_sequence = analyze_records(
            [
                record(1, 0),
                record(2, 100, "S"),
                record(3, 100, "R"),
            ]
        )[0]
        excessive_sequence = analyze_records(
            [
                record(1, 100, "S"),
                record(2, 601, "R"),
            ]
        )[0]

        self.assertEqual(zero_sequence.status, "INVALID")
        self.assertEqual(zero_sequence.reason, "ODS_RESET_0000")
        self.assertIsNone(zero_sequence.peak_load)
        self.assertEqual(excessive_sequence.status, "INVALID")
        self.assertEqual(excessive_sequence.reason, "EXCESSIVE_LOAD")
        self.assertEqual(excessive_sequence.peak_load, 501)

    def test_load_equal_to_500_is_valid(self) -> None:
        sequence = analyze_records(
            [record(1, 100, "S"), record(2, 600, "R")]
        )[0]

        self.assertEqual(sequence.peak_load, 500)
        self.assertEqual(sequence.status, "VALID")

    def test_rejects_multiple_terminal_events_in_one_record(self) -> None:
        with self.assertRaisesRegex(ValueError, "multiple terminal events"):
            analyze_records([record(1, 100, "S", "R", "E")])


class ReportTests(unittest.TestCase):
    @staticmethod
    def _write_cleaned_file(path: Path, rows: list[tuple[int, tuple[str, ...]]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"a\tb\tc\t{ods:04X}\t\t{events[0] if events else ''}\t"
            f"{events[1] if len(events) > 1 else ''}\n"
            for ods, events in rows
        ]
        path.write_text("".join(lines), encoding="utf-8")

    def test_writes_per_file_and_pooled_statistics_and_combined_details(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "input"
            reports_dir = root / "reports"
            first = output_dir / "Group" / "first_cleaned.txt"
            second = output_dir / "second_cleaned.txt"
            self._write_cleaned_file(
                first,
                [(100, ()), (120, ("S",)), (100, ("R",))],
            )
            self._write_cleaned_file(
                second,
                [(200, ("S",)), (100, ("R",))],
            )

            summary_rows, sequences, report_paths = analyze_files(
                [first, second],
                output_dir=output_dir,
                reports_dir=reports_dir,
                timestamp="test",
                metadata_by_folder={
                    "Group": MotorMetadata(
                        project="J4S IO",
                        type="SLE",
                        firmware="A15",
                        torque_nm="6",
                        sensitivity="High",
                    ),
                    ".": MotorMetadata(
                        project="J4S IO",
                        type="Standard",
                        firmware="A15",
                        torque_nm="6",
                        sensitivity="Low",
                    ),
                },
            )

            self.assertEqual(len(sequences), 2)
            self.assertEqual(report_paths[0].name, "sensitivity_sr_summary_test.csv")
            self.assertEqual(report_paths[1].name, "sensitivity_sr_details_test.csv")
            self.assertEqual(summary_rows[-1]["File"], "ALL_FILES_POOLED")
            self.assertEqual(summary_rows[-1]["SR_Count"], 2)
            self.assertEqual(summary_rows[-1]["Average_SR_Load"], 60)
            self.assertEqual(summary_rows[-1]["Max_SR_Load"], 100)
            self.assertEqual(summary_rows[-1]["P95_SR_Load"], 96)
            self.assertEqual(summary_rows[-1]["SR_Load_STD"], 56.57)
            self.assertEqual(summary_rows[-1]["Average_SR_Time_ms"], 20)
            self.assertEqual(summary_rows[0]["Project"], "J4S IO")
            self.assertEqual(summary_rows[0]["Type"], "SLE")
            self.assertEqual(summary_rows[-1]["Project"], "")

            with report_paths[0].open(newline="", encoding="utf-8") as report_file:
                summary_csv = list(csv.DictReader(report_file))
            with report_paths[1].open(newline="", encoding="utf-8") as report_file:
                details_csv = list(csv.DictReader(report_file))

        self.assertEqual(summary_csv[-1]["File"], "ALL_FILES_POOLED")
        self.assertEqual(
            list(summary_csv[0]),
            [
                "File",
                *METADATA_FIELDS,
                "SR_Count",
                "Invalid_SR_Count",
                "Average_SR_Load",
                "Max_SR_Load",
                "P95_SR_Load",
                "SR_Load_STD",
                "Average_SR_Time_ms",
            ],
        )
        self.assertEqual(len(details_csv), 2)
        self.assertEqual(
            list(details_csv[0]),
            [
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
            ],
        )
        self.assertEqual(details_csv[0]["S_Index"], "1")
        self.assertEqual(details_csv[0]["SR_Time_ms"], "20")
        self.assertEqual(details_csv[0]["Firmware"], "A15")

    def test_creates_reports_for_invalid_candidates_but_not_for_no_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "input"
            reports_dir = root / "reports"
            invalid_file = output_dir / "invalid_cleaned.txt"
            self._write_cleaned_file(
                invalid_file,
                [(0, ("S",)), (100, ("R",))],
            )

            rows, sequences, report_paths = analyze_files(
                [invalid_file],
                output_dir=output_dir,
                reports_dir=reports_dir,
                timestamp="invalid",
            )

            self.assertEqual(len(sequences), 1)
            self.assertEqual(rows[0]["SR_Count"], 0)
            self.assertEqual(rows[0]["Invalid_SR_Count"], 1)
            self.assertIsNotNone(report_paths)

            existing_reports = sorted(path.name for path in reports_dir.iterdir())
            no_candidate_file = output_dir / "no_candidate_cleaned.txt"
            self._write_cleaned_file(no_candidate_file, [(100, ("S",)), (90, ("E",))])
            _, sequences, no_report_paths = analyze_files(
                [no_candidate_file],
                output_dir=output_dir,
                reports_dir=reports_dir,
                timestamp="none",
            )
            reports_after = sorted(path.name for path in reports_dir.iterdir())

        self.assertEqual(sequences, [])
        self.assertIsNone(no_report_paths)
        self.assertEqual(reports_after, existing_reports)

    def test_report_pair_does_not_overwrite_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "input"
            reports_dir = root / "reports"
            existing_summary = reports_dir / "sensitivity_sr_summary_test.csv"
            existing_summary.parent.mkdir()
            existing_summary.write_text("existing", encoding="utf-8")
            cleaned_file = output_dir / "run_cleaned.txt"
            self._write_cleaned_file(
                cleaned_file,
                [(100, ("S",)), (90, ("R",))],
            )

            _, _, report_paths = analyze_files(
                [cleaned_file],
                output_dir=output_dir,
                reports_dir=reports_dir,
                timestamp="test",
            )
            self.assertEqual(existing_summary.read_text(encoding="utf-8"), "existing")

        self.assertEqual(
            report_paths[0].name, "sensitivity_sr_summary_test_002.csv"
        )
        self.assertEqual(
            report_paths[1].name, "sensitivity_sr_details_test_002.csv"
        )


class ApplicationMenuTests(unittest.TestCase):
    def test_menu_dispatches_to_s_r_analysis(self) -> None:
        with (
            patch("builtins.input", side_effect=["3", "0", ""]),
            patch.object(app.sr_mechanical_analysis, "main") as analyze,
            redirect_stdout(io.StringIO()),
        ):
            app.main()

        analyze.assert_called_once_with()


class MotorMetadataTests(unittest.TestCase):
    def _write_metadata(self, path: Path, rows: list[list[str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as metadata_file:
            writer = csv.writer(metadata_file)
            writer.writerow(METADATA_CSV_FIELDS)
            writer.writerows(rows)

    def test_reads_one_metadata_row_for_a_selected_folder_in_either_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            metadata_file = root / "sensitivity" / "input" / "motor_metadata.csv"
            self._write_metadata(
                metadata_file,
                [["J4S IO", "SLE", "A15", "6", "High"]],
            )
            input_root = root / "sensitivity" / "input"
            parser_root = root / "parser" / "output"
            input_file = input_root / "Group" / "input_cleaned.txt"
            parser_file = parser_root / "Group" / "parser_cleaned.txt"
            input_file.parent.mkdir(parents=True)
            parser_file.parent.mkdir(parents=True)

            with patch("builtins.input") as input_mock:
                input_metadata = resolve_motor_metadata(
                    [input_file], input_root, metadata_file=metadata_file
                )
                parser_metadata = resolve_motor_metadata(
                    [parser_file], parser_root, metadata_file=metadata_file
                )

        self.assertEqual(
            input_metadata["Group"],
            MotorMetadata("J4S IO", "SLE", "A15", "6", "High"),
        )
        self.assertEqual(parser_metadata["Group"], input_metadata["Group"])
        input_mock.assert_not_called()

    def test_reads_metadata_from_each_selected_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source_root = Path(temporary_directory) / "input"
            high_folder = source_root / "J4S IO SLE 6Nm High"
            low_folder = source_root / "J4S IO SLE 6Nm Low"
            high_file = high_folder / "run1_cleaned.txt"
            low_file = low_folder / "run2_cleaned.txt"
            high_metadata_file = high_folder / "motor_metadata.csv"
            low_metadata_file = low_folder / "motor_metadata.csv"
            self._write_metadata(
                high_metadata_file,
                [["J4S IO", "SLE", "A15+", "6Nm", "High"]],
            )
            self._write_metadata(
                low_metadata_file,
                [["J4S IO", "SLE", "A15+", "6Nm", "Low"]],
            )

            with patch("builtins.input") as input_mock:
                metadata = resolve_motor_metadata(
                    [high_file, low_file],
                    source_root,
                    metadata_file=source_root / "motor_metadata.csv",
                )

        self.assertEqual(metadata["J4S IO SLE 6Nm High"].sensitivity, "High")
        self.assertEqual(metadata["J4S IO SLE 6Nm Low"].sensitivity, "Low")
        self.assertEqual(metadata["J4S IO SLE 6Nm High"].firmware, "A15+")
        input_mock.assert_not_called()

    def test_multiple_selected_folders_require_separate_manual_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "input"
            metadata_file = root / "motor_metadata.csv"
            self._write_metadata(
                metadata_file,
                [["J4S IO", "SLE", "A15", "6", "High"]],
            )
            direct_file = source_root / "Group" / "direct_cleaned.txt"
            nested_file = source_root / "Group" / "Nested" / "nested_cleaned.txt"
            direct_file.parent.mkdir(parents=True)
            nested_file.parent.mkdir(parents=True)

            with patch("builtins.input", side_effect=["n", "n"]) as input_mock:
                metadata = resolve_motor_metadata(
                    [direct_file, nested_file], source_root, metadata_file=metadata_file
                )

        self.assertEqual(input_mock.call_count, 2)
        self.assertEqual(metadata["Group"], MotorMetadata())
        self.assertEqual(metadata["Group/Nested"], MotorMetadata())

    def test_manual_metadata_is_requested_once_per_unmatched_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "input"
            folder = source_root / "Group"
            files = [folder / "one_cleaned.txt", folder / "two_cleaned.txt"]
            folder.mkdir(parents=True)
            metadata_file = root / "motor_metadata.csv"
            metadata_file.write_text(
                ",".join(METADATA_CSV_FIELDS) + "\n", encoding="utf-8"
            )

            with patch(
                "builtins.input",
                side_effect=["y", "J4S IO", "SLE", "A15", "6", "High"],
            ) as input_mock:
                metadata = resolve_motor_metadata(
                    files, source_root, metadata_file=metadata_file
                )

        self.assertEqual(input_mock.call_count, 6)
        self.assertEqual(metadata["Group"].sensitivity, "High")

    def test_multiple_folder_manual_entries_keep_each_configuration_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source_root = root / "input"
            sle_folder = source_root / "J4S IO SLE 6Nm High"
            standard_folder = source_root / "J4S IO Standard 6Nm Low"
            sle_folder.mkdir(parents=True)
            standard_folder.mkdir(parents=True)
            files = [
                sle_folder / "run1_cleaned.txt",
                standard_folder / "run2_cleaned.txt",
            ]
            metadata_file = root / "motor_metadata.csv"
            metadata_file.write_text(
                ",".join(METADATA_CSV_FIELDS) + "\n", encoding="utf-8"
            )

            with patch(
                "builtins.input",
                side_effect=[
                    "y",
                    "J4S IO",
                    "SLE",
                    "A15",
                    "6",
                    "High",
                    "y",
                    "J4S IO",
                    "Standard",
                    "A15",
                    "6",
                    "Low",
                ],
            ):
                metadata = resolve_motor_metadata(
                    files, source_root, metadata_file=metadata_file
                )

        self.assertEqual(metadata["J4S IO SLE 6Nm High"].type, "SLE")
        self.assertEqual(metadata["J4S IO Standard 6Nm Low"].type, "Standard")
        self.assertNotEqual(
            metadata["J4S IO SLE 6Nm High"].sensitivity,
            metadata["J4S IO Standard 6Nm Low"].sensitivity,
        )

    def test_rejects_multiple_metadata_rows_without_a_folder_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            metadata_file = Path(temporary_directory) / "motor_metadata.csv"
            self._write_metadata(
                metadata_file,
                [
                    ["J4S IO", "SLE", "A15", "6", "High"],
                    ["J4S IO", "Standard", "A15", "6", "Low"],
                ],
            )

            with self.assertRaisesRegex(ValueError, "at most one metadata row"):
                read_motor_metadata(metadata_file)


if __name__ == "__main__":
    unittest.main()
