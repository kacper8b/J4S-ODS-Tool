from contextlib import redirect_stdout
import io
import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from j4s_ods_tool import txt_parser
from j4s_ods_tool.txt_parser import (
    INPUT_DIR,
    WORKSPACE_DIR,
    get_input_folders,
    get_loose_txt_files,
    get_txt_files,
    parse_line,
    process_file,
    process_files,
)


class ParseLineTests(unittest.TestCase):
    def test_parses_record_and_orders_symbols(self) -> None:
        parsed = parse_line("2571 22C3 3D1F 3D1F Y 0135 R")

        self.assertEqual(
            parsed,
            ("2571", "22C3", "3D1F", "3D1F", "0135", "R", "Y"),
        )

    def test_repairs_symbol_attached_to_hex_value(self) -> None:
        parsed = parse_line("2570 2303 3DC3 3D18N")

        self.assertEqual(
            parsed,
            ("2570", "2303", "3DC3", "3D18", "", "N", ""),
        )

    def test_rejects_invalid_record_shapes(self) -> None:
        invalid_lines = (
            "header",
            "2571 22C3 3D1F",
            "2571 22C3 3D1F 3D1F 0135 013D",
            "2571 22C3 3D1F 3D1F Q",
            "2571 22C3 3D1F 3D1F S R E",
        )

        for line in invalid_lines:
            with self.subTest(line=line):
                self.assertIsNone(parse_line(line))


class ProcessFileTests(unittest.TestCase):
    def test_default_data_directories_are_under_workspace(self) -> None:
        self.assertEqual(INPUT_DIR, WORKSPACE_DIR / "input")
        self.assertEqual(WORKSPACE_DIR.name, "workspace")

    def test_writes_processed_and_rejected_rows_and_reports_repairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_path = root / "motor.txt"
            output_dir = root / "output"
            rejected_dir = root / "rejected"
            input_path.write_text(
                "Reset ODS\n"
                "\n"
                "<br>\n"
                "2571 22C3 3D1F 3D1F S 0135\n"
                "2570 2303 3DC3 3D18N\n",
                encoding="utf-8",
            )

            result = process_file(
                input_path,
                output_dir=output_dir,
            )

            self.assertEqual(result.valid_count, 2)
            self.assertEqual(result.rejected_count, 1)
            self.assertEqual(result.fixed_symbol_count, 1)
            self.assertEqual(
                result.output_path.read_text(encoding="utf-8"),
                "2571\t22C3\t3D1F\t3D1F\t0135\tS\t\n"
                "2570\t2303\t3DC3\t3D18\t\tN\t",
            )
            self.assertEqual(result.rejected_path, output_dir / "motor_rejected.txt")
            self.assertEqual(
                result.rejected_path.read_text(encoding="utf-8"),
                "Reset ODS",
            )
            self.assertFalse(rejected_dir.exists())

    def test_discovers_loose_files_and_nested_folder_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_dir = Path(temporary_directory)
            loose_file = input_dir / "loose.txt"
            nested_file = input_dir / "Group" / "Subgroup" / "nested.txt"
            loose_file.parent.mkdir(parents=True, exist_ok=True)
            nested_file.parent.mkdir(parents=True)
            loose_file.write_text("", encoding="utf-8")
            nested_file.write_text("", encoding="utf-8")

            self.assertEqual(get_loose_txt_files(input_dir), [loose_file])
            self.assertEqual(get_input_folders(input_dir), [input_dir / "Group"])
            self.assertEqual(get_txt_files(input_dir), [nested_file, loose_file])

    def test_outputs_from_nested_folders_are_flat_and_folder_prefixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            files = [
                input_dir / "Group One" / "capture.txt",
                input_dir / "Group Two" / "capture.txt",
            ]
            for file_path in files:
                file_path.parent.mkdir(parents=True)
                file_path.write_text(
                    "2571 22C3 3D1F 3D1F S 0135\nReset ODS\n",
                    encoding="utf-8",
                )

            results = process_files(
                files,
                input_dir,
                naming_mode=3,
                base_name="",
                prefix="",
                output_dir=output_dir,
            )

            self.assertEqual(
                [result.output_path.name for result in results],
                [
                    "Group_One_capture_processed.txt",
                    "Group_Two_capture_processed.txt",
                ],
            )
            for result in results:
                self.assertEqual(result.rejected_path.parent, output_dir)
                self.assertTrue(result.output_path.exists())
                self.assertTrue(result.rejected_path.exists())
            self.assertEqual(len(list(output_dir.iterdir())), 4)

    def test_duplicate_flattened_folder_names_get_unique_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            files = [
                input_dir / "a_b" / "c" / "run.txt",
                input_dir / "a" / "b_c" / "run.txt",
            ]
            for file_path in files:
                file_path.parent.mkdir(parents=True)
                file_path.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")

            results = process_files(
                files,
                input_dir,
                naming_mode=3,
                base_name="",
                prefix="",
                output_dir=output_dir,
            )

            self.assertEqual(
                [result.output_path.name for result in results],
                [
                    "a_b_c_run_processed.txt",
                    "a_b_c_run_002_processed.txt",
                ],
            )

    def test_main_processes_all_files_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            loose_file = input_dir / "loose.txt"
            nested_file = input_dir / "Group" / "nested.txt"
            nested_file.parent.mkdir(parents=True)
            loose_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")
            nested_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch("builtins.input", side_effect=["1", "3", ""]),
                redirect_stdout(io.StringIO()),
            ):
                txt_parser.main()

            self.assertTrue((output_dir / "loose_processed.txt").exists())
            self.assertTrue((output_dir / "Group_nested_processed.txt").exists())

    def test_main_processes_a_selected_folder_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            nested_file = input_dir / "Group" / "Subgroup" / "run.txt"
            nested_file.parent.mkdir(parents=True)
            nested_file.write_text("2571 22C3 3D1F 3D1F S 0135\n", encoding="utf-8")

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch("builtins.input", side_effect=["3", "1", "3", ""]),
                redirect_stdout(io.StringIO()),
            ):
                txt_parser.main()

            self.assertTrue(
                (output_dir / "Group_Subgroup_run_processed.txt").exists()
            )

    def test_can_return_from_folder_selection_to_process_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            loose_file = input_dir / "loose.txt"
            nested_file = input_dir / "Group" / "nested.txt"
            nested_file.parent.mkdir(parents=True)
            loose_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")
            nested_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")
            captured_output = io.StringIO()

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch("builtins.input", side_effect=["3", "0", "1", "3", ""]),
                redirect_stdout(captured_output),
            ):
                txt_parser.main()

            self.assertTrue((output_dir / "loose_processed.txt").exists())
            self.assertTrue((output_dir / "Group_nested_processed.txt").exists())
            self.assertIn("0. Back to main menu", captured_output.getvalue())

    def test_main_processes_a_selected_loose_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            input_dir.mkdir()
            loose_file = input_dir / "run.txt"
            loose_file.write_text("2571 22C3 3D1F 3D1F S 0135\n", encoding="utf-8")

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch("builtins.input", side_effect=["2", "1", "3", ""]),
                redirect_stdout(io.StringIO()),
            ):
                txt_parser.main()

            self.assertTrue((output_dir / "run_processed.txt").exists())


if __name__ == "__main__":
    unittest.main()
