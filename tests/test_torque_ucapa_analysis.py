import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from j4s_ods_tool import __main__ as app
from j4s_ods_tool import torque_ucapa_analysis


def write_cleaned_file(path: Path, values: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for value in values:
        columns = ["0000", "0000", "0000", f"{value:04X}", "", "", ""]
        lines.append("\t".join(columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ParseTimeIntervalTests(unittest.TestCase):
    def test_parses_seconds(self) -> None:
        self.assertEqual(
            torque_ucapa_analysis.parse_time_interval("1.25", "2.5"),
            (Decimal("1.25"), Decimal("2.5")),
        )

    def test_rejects_invalid_intervals(self) -> None:
        invalid_intervals = [
            ("not-a-number", "1"),
            ("NaN", "1"),
            ("-1", "1"),
            ("2", "1"),
        ]
        for interval in invalid_intervals:
            with self.subTest(interval=interval), self.assertRaises(ValueError):
                torque_ucapa_analysis.parse_time_interval(*interval)


class CalculateFolderMeanTests(unittest.TestCase):
    def test_sample_times_follow_parsed_records_not_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "configuration"
            path = folder / "run_cleaned.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            first = "\t".join(["0000", "0000", "0000", "000A", "", "", ""])
            second = "\t".join(["0000", "0000", "0000", "0014", "", "", ""])
            path.write_text(f"{first}\n\n{second}\n", encoding="utf-8")

            mean = torque_ucapa_analysis.calculate_folder_mean(
                folder,
                Decimal("0.02"),
                Decimal("0.02"),
            )

        self.assertEqual(mean, Decimal("20"))

    def test_includes_both_interval_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "configuration"
            write_cleaned_file(
                folder / "run_cleaned.txt",
                [10, 20, 30, 40],
            )

            mean = torque_ucapa_analysis.calculate_folder_mean(
                folder,
                Decimal("0.02"),
                Decimal("0.04"),
            )

        self.assertEqual(mean, Decimal("25"))

    def test_pools_records_across_files_with_equal_record_weight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "configuration"
            write_cleaned_file(folder / "one_cleaned.txt", [10])
            write_cleaned_file(folder / "two_cleaned.txt", [30, 30, 30])

            mean = torque_ucapa_analysis.calculate_folder_mean(
                folder,
                Decimal("0"),
                Decimal("0.04"),
            )

        self.assertEqual(mean, Decimal("25"))

    def test_returns_none_when_no_records_fall_in_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "configuration"
            write_cleaned_file(folder / "run_cleaned.txt", [10, 20])

            mean = torque_ucapa_analysis.calculate_folder_mean(
                folder,
                Decimal("1"),
                Decimal("2"),
            )

        self.assertIsNone(mean)


class FolderSelectionTests(unittest.TestCase):
    def test_selects_two_distinct_top_level_folders(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            first = source / "First"
            second = source / "Second"
            write_cleaned_file(first / "one_cleaned.txt", [10])
            write_cleaned_file(second / "two_cleaned.txt", [20])

            with (
                patch("builtins.input", side_effect=["1", "1"]),
                redirect_stdout(io.StringIO()),
            ):
                selected = torque_ucapa_analysis.select_folder_pair(source)

        self.assertEqual(selected, (first, second))

    def test_requires_two_folders_with_cleaned_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            write_cleaned_file(source / "Only" / "run_cleaned.txt", [10])
            with redirect_stdout(io.StringIO()) as console:
                selected = torque_ucapa_analysis.select_folder_pair(source)

        self.assertIsNone(selected)
        self.assertIn("At least two folders", console.getvalue())


class MainTests(unittest.TestCase):
    def test_prints_means_and_second_minus_first_to_two_decimals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch.object(
                    torque_ucapa_analysis.sensitivity_analysis,
                    "OUTPUT_DIR",
                    root / "parser",
                ),
                patch.object(
                    torque_ucapa_analysis.sensitivity_analysis,
                    "INPUT_DIR",
                    root / "input",
                ),
                patch.object(
                    torque_ucapa_analysis.sensitivity_analysis,
                    "select_source",
                    return_value=root,
                ),
                patch.object(
                    torque_ucapa_analysis,
                    "select_folder_pair",
                    return_value=(root / "First", root / "Second"),
                ),
                patch.object(
                    torque_ucapa_analysis,
                    "read_time_interval",
                    return_value=(Decimal("1"), Decimal("2")),
                ),
                patch.object(
                    torque_ucapa_analysis,
                    "calculate_folder_mean",
                    side_effect=[Decimal("2.346"), Decimal("3.456")],
                ),
                redirect_stdout(io.StringIO()) as console,
            ):
                torque_ucapa_analysis.main()

        output = console.getvalue()
        self.assertIn("First mean Ucap: 2.35", output)
        self.assertIn("Second mean Ucap: 3.46", output)
        self.assertIn("Difference (second folder - first): 1.11", output)

    def test_does_not_report_comparison_when_folder_has_no_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with (
                patch.object(torque_ucapa_analysis.sensitivity_analysis, "OUTPUT_DIR", root / "parser"),
                patch.object(torque_ucapa_analysis.sensitivity_analysis, "INPUT_DIR", root / "input"),
                patch.object(
                    torque_ucapa_analysis.sensitivity_analysis,
                    "select_source",
                    return_value=root,
                ),
                patch.object(
                    torque_ucapa_analysis,
                    "select_folder_pair",
                    return_value=(root / "First", root / "Second"),
                ),
                patch.object(
                    torque_ucapa_analysis,
                    "read_time_interval",
                    return_value=(Decimal("1"), Decimal("2")),
                ),
                patch.object(
                    torque_ucapa_analysis,
                    "calculate_folder_mean",
                    side_effect=[None, Decimal("3")],
                ),
                redirect_stdout(io.StringIO()) as console,
            ):
                torque_ucapa_analysis.main()

        output = console.getvalue()
        self.assertIn(
            "No records fall within the selected interval for: First",
            output,
        )
        self.assertNotIn("Difference (second folder - first):", output)

    def test_main_menu_dispatches_option_six_to_analysis(self) -> None:
        with (
            patch("builtins.input", side_effect=["6", "0", ""]),
            patch.object(app.torque_ucapa_analysis, "main") as analyze,
            redirect_stdout(io.StringIO()),
        ):
            app.main()

        analyze.assert_called_once_with()

    def test_main_menu_keeps_option_five_for_slope_parameters(self) -> None:
        with (
            patch("builtins.input", side_effect=["5", "0", ""]),
            patch.object(
                app.independent_slope_analysis,
                "configure_parameters",
            ) as configure,
            redirect_stdout(io.StringIO()),
        ):
            app.main()

        configure.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
