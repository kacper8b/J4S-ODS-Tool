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
from j4s_ods_tool import sensitivity_analysis
from j4s_ods_tool.sensitivity_analysis import (
    LogRecord,
    analyze_files,
    analyze_records,
    parse_cleaned_file,
)


def record(line_number: int, ods: int, *events: str) -> LogRecord:
    return LogRecord(line_number, ods, events)


class AnalyzeRecordsTests(unittest.TestCase):
    def test_measures_only_e_using_maximum_of_four_previous_samples(self) -> None:
        records = [
            record(1, 0x0100),
            record(2, 0x0120),
            record(3, 0x0110),
            record(4, 0x0115),
            record(5, 0x0300, "S"),
            record(6, 0x0200),
            record(7, 0x0080, "E"),
        ]

        summary = analyze_records(records)

        self.assertEqual(summary.sequences_started, 1)
        self.assertEqual(len(summary.measurements), 1)
        measurement = summary.measurements[0]
        self.assertEqual(measurement.s_line, 5)
        self.assertEqual(measurement.e_line, 7)
        self.assertEqual(measurement.s_reference, 0x0120)
        self.assertEqual(measurement.e_ods, 0x0080)
        self.assertEqual(measurement.load, 0x00A0)

    def test_r_and_x_terminate_sequence_without_an_obstacle_measurement(self) -> None:
        records = [
            record(1, 1),
            record(2, 2),
            record(3, 3),
            record(4, 4),
            record(5, 5, "S"),
            record(6, 6, "R"),
            record(7, 7, "E"),
            record(8, 8, "S"),
            record(9, 9, "X"),
            record(10, 10, "E"),
        ]

        summary = analyze_records(records)

        self.assertEqual(summary.terminated_by_r, 1)
        self.assertEqual(summary.terminated_by_x, 1)
        self.assertEqual(summary.measurements, [])

    def test_e_without_four_previous_records_is_reported_without_measurement(self) -> None:
        summary = analyze_records(
            [
                record(1, 0x0100, "S"),
                record(2, 0x0080, "E"),
            ]
        )

        self.assertEqual(summary.e_without_reference, 1)
        self.assertEqual(summary.measurements, [])

    def test_repeated_s_and_unterminated_sequence_are_counted(self) -> None:
        summary = analyze_records(
            [
                record(1, 1, "S"),
                record(2, 2, "S"),
            ]
        )

        self.assertEqual(summary.sequences_started, 2)
        self.assertEqual(summary.incomplete_sequences, 2)

    def test_rejects_multiple_terminal_events_in_one_record(self) -> None:
        records = [
            record(1, 1, "S"),
            record(2, 2, "R", "E"),
        ]

        with self.assertRaisesRegex(ValueError, "multiple terminal events"):
            analyze_records(records)


class CleanedFileTests(unittest.TestCase):
    def test_reads_normalized_seven_column_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            file_path = Path(temporary_directory) / "run_cleaned.txt"
            file_path.write_text(
                "2571\t22C3\t3D1F\t0100\t\tS\t\n"
                "2570\t2303\t3DC3\t0080\t\tE\t\n",
                encoding="utf-8",
            )

            records = parse_cleaned_file(file_path)

        self.assertEqual(records, [record(1, 0x0100, "S"), record(2, 0x0080, "E")])

    def test_reports_measurement_with_source_and_cleaned_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "output"
            report_dir = root / "reports"
            cleaned_file = output_dir / "Group" / "run_cleaned.txt"
            cleaned_file.parent.mkdir(parents=True)
            cleaned_file.write_text(
                "a\tb\tc\t0100\t\t\t\n"
                "a\tb\tc\t0120\t\t\t\n"
                "a\tb\tc\t0110\t\t\t\n"
                "a\tb\tc\t0115\t\t\t\n"
                "a\tb\tc\t0300\t\tS\t\n"
                "a\tb\tc\t0080\t\tE\t\n",
                encoding="utf-8",
            )

            summary, report_path = analyze_files(
                [cleaned_file],
                output_dir=output_dir,
                reports_dir=report_dir,
                timestamp="test",
            )

            self.assertEqual(len(summary.measurements), 1)
            self.assertEqual(report_path, report_dir / "sensitivity_obstacle_test.csv")
            with report_path.open(newline="", encoding="utf-8") as report_file:
                rows = list(csv.DictReader(report_file))

        self.assertEqual(
            rows,
            [
                {
                    "File": str(Path("Group") / "run_cleaned.txt"),
                    "Cleaned_S_Line": "5",
                    "Cleaned_E_Line": "6",
                    "S_Ref": str(0x0120),
                    "ODS_E": str(0x0080),
                    "Obstacle_Load": str(0x00A0),
                }
            ],
        )

    def test_analysis_menu_does_not_overwrite_existing_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_dir = root / "output"
            report_dir = root / "reports"
            report_dir.mkdir()
            existing_report = report_dir / "sensitivity_obstacle_test.csv"
            existing_report.write_text("existing", encoding="utf-8")
            cleaned_file = output_dir / "run_cleaned.txt"
            output_dir.mkdir()
            cleaned_file.write_text(
                "a\tb\tc\t0100\t\t\t\n"
                "a\tb\tc\t0120\t\t\t\n"
                "a\tb\tc\t0110\t\t\t\n"
                "a\tb\tc\t0115\t\t\t\n"
                "a\tb\tc\t0300\t\tS\t\n"
                "a\tb\tc\t0080\t\tE\t\n",
                encoding="utf-8",
            )

            _, report_path = analyze_files(
                [cleaned_file],
                output_dir=output_dir,
                reports_dir=report_dir,
                timestamp="test",
            )

            self.assertEqual(
                report_path,
                report_dir / "sensitivity_obstacle_test_002.csv",
            )
            self.assertEqual(existing_report.read_text(encoding="utf-8"), "existing")


class ApplicationMenuTests(unittest.TestCase):
    def test_analysis_uses_selected_source_and_common_report_directory(self) -> None:
        for choice, source_name in (("1", "parser"), ("2", "sensitivity")):
            with self.subTest(source=source_name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                parser_output = root / "parser" / "output"
                dedicated_input = root / "sensitivity" / "input"
                reports = root / "sensitivity" / "output"
                for source in (parser_output, dedicated_input):
                    source.mkdir(parents=True)
                    file_path = source / "Group" / "run_cleaned.txt"
                    file_path.parent.mkdir()
                    file_path.write_text(
                        "a\tb\tc\t0100\t\t\t\n" * 4
                        + "a\tb\tc\t00F0\t\tS\t\n"
                        + "a\tb\tc\t0080\t\tE\t\n",
                        encoding="utf-8",
                    )
                console = io.StringIO()
                with (
                    patch.object(sensitivity_analysis, "OUTPUT_DIR", parser_output),
                    patch.object(sensitivity_analysis, "INPUT_DIR", dedicated_input),
                    patch.object(sensitivity_analysis, "REPORTS_DIR", reports),
                    patch("builtins.input", side_effect=[choice, "1"]),
                    redirect_stdout(console),
                ):
                    sensitivity_analysis.main()

                selected_source = parser_output if choice == "1" else dedicated_input
                self.assertIn(f"Source:\n{selected_source}", console.getvalue())
                report_files = list(reports.glob("*.csv"))
                self.assertEqual(len(report_files), 1)
                with report_files[0].open(newline="", encoding="utf-8") as report:
                    rows = list(csv.DictReader(report))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["File"], str(Path("Group") / "run_cleaned.txt"))
                self.assertEqual(rows[0]["Obstacle_Load"], "128")

    def test_source_selection_can_go_back_and_rejects_unknown_options(self) -> None:
        with (
            patch("builtins.input", side_effect=["invalid", "0"]),
            redirect_stdout(io.StringIO()) as console,
        ):
            self.assertIsNone(sensitivity_analysis.select_source())
        self.assertIn("Unknown option.", console.getvalue())

    def test_empty_source_is_explicit_and_does_not_create_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reports = root / "sensitivity" / "output"
            with (
                patch.object(sensitivity_analysis, "OUTPUT_DIR", root / "parser" / "output"),
                patch.object(sensitivity_analysis, "INPUT_DIR", root / "sensitivity" / "input"),
                patch.object(sensitivity_analysis, "REPORTS_DIR", reports),
                patch("builtins.input", side_effect=["2"]),
                redirect_stdout(io.StringIO()) as console,
            ):
                sensitivity_analysis.main()
            self.assertIn("No cleaned TXT files found", console.getvalue())
            self.assertEqual(list(reports.iterdir()), [])

    def test_file_selection_is_scoped_to_source_and_recurses_into_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "sensitivity" / "input"
            nested_file = source / "Group" / "Nested" / "run_cleaned.txt"
            nested_file.parent.mkdir(parents=True)
            nested_file.touch()
            (source / "raw.txt").touch()
            for choices in (["1"], ["2", "1"], ["3", "1"]):
                with (
                    self.subTest(choices=choices),
                    patch("builtins.input", side_effect=choices),
                    redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(
                        sensitivity_analysis.select_cleaned_files(source),
                        [nested_file],
                    )

    def test_menu_dispatches_to_cleaned_log_analysis(self) -> None:
        with (
            patch("builtins.input", side_effect=["2", "0", ""]),
            patch.object(app.sensitivity_analysis, "main") as analyze,
            redirect_stdout(io.StringIO()),
        ):
            app.main()

        analyze.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
