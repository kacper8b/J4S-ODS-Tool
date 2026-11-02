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
    OUTPUT_DIR,
    REJECTED_DIR,
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

    def test_discards_suffixes_on_required_fields(self) -> None:
        fields = ["254C", "1CE4", "2EAC", "0000"]
        for index in range(4):
            for suffix in ("B\u2592", "B", "\u2592@"):
                with self.subTest(index=index, suffix=suffix):
                    tokens = fields.copy()
                    tokens[index] += suffix
                    self.assertEqual(
                        parse_line(" ".join(tokens)),
                        ("254C", "1CE4", "2EAC", "0000", "", "", ""),
                    )

    def test_rejects_missing_or_invalid_required_hex_prefix(self) -> None:
        for field in ("000", "00G0B", "G000B", "\u25920000"):
            with self.subTest(field=field):
                self.assertIsNone(parse_line(f"254C 1CE4 2EAC {field}"))

    def test_discards_two_byte_hex_number_attached_to_e_symbol(self) -> None:
        for suffix in ("0", "9", "FF", "940", "0940", "FFFF", "ffff", "000FFFF", "000E"):
            with self.subTest(suffix=suffix):
                self.assertEqual(
                    parse_line(f"25C0 1EB2 3225 3225 E{suffix} 03AC"),
                    ("25C0", "1EB2", "3225", "3225", "03AC", "E", ""),
                )

    def test_rejects_invalid_number_attached_to_e_symbol(self) -> None:
        for suffix in ("10000", "1000E", "FFFFF", "-1", "+1", "0x940", "94G"):
            with self.subTest(suffix=suffix):
                self.assertIsNone(
                    parse_line(f"25C0 1EB2 3225 3225 E{suffix} 03AC")
                )

    def test_discards_non_hex_suffix_attached_to_value_when_e_is_present(self) -> None:
        for symbol in ("E", "E309", "E9", "EFFFF", "E000E"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    parse_line(f"2580 2041 36AB 36AB {symbol} 0135▒@▒"),
                    ("2580", "2041", "36AB", "36AB", "0135", "E", ""),
                )

    def test_rejects_invalid_record_shapes(self) -> None:
        invalid_lines = (
            "header",
            "2571 22C3 3D1F",
            "2571 22C3 3D1F 3D1F 0135 013D",
            "2571 22C3 3D1F 3D1F 0135▒@▒",
            "2571 22C3 3D1F 3D1F Q",
            "2571 22C3 3D1F 3D1F S R E",
        )

        for line in invalid_lines:
            with self.subTest(line=line):
                self.assertIsNone(parse_line(line))


class ProcessFileTests(unittest.TestCase):
    def test_default_data_directories_are_under_workspace(self) -> None:
        self.assertEqual(INPUT_DIR, WORKSPACE_DIR / "parser" / "input")
        self.assertEqual(OUTPUT_DIR, WORKSPACE_DIR / "parser" / "output")
        self.assertEqual(REJECTED_DIR, WORKSPACE_DIR / "parser" / "rejected")
        self.assertEqual(WORKSPACE_DIR.name, "workspace")

    def test_writes_cleaned_and_rejected_rows_and_reports_repairs(self) -> None:
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
                "2570 2303 3DC3 3D18N\n"
                "254C 1CE4 2EAC 0000B\u2592\n",
                encoding="utf-8",
            )

            result = process_file(
                input_path,
                output_dir=output_dir,
                rejected_dir=rejected_dir,
            )

            self.assertEqual(result.valid_count, 3)
            self.assertEqual(result.rejected_count, 1)
            self.assertEqual(result.fixed_symbol_count, 1)
            self.assertEqual(
                result.output_path.read_text(encoding="utf-8"),
                "2571\t22C3\t3D1F\t3D1F\t0135\tS\t\n"
                "2570\t2303\t3DC3\t3D18\t\tN\t\n"
                "254C\t1CE4\t2EAC\t0000\t\t\t",
            )
            self.assertEqual(result.rejected_path, rejected_dir / "motor_rejected.txt")
            self.assertEqual(
                result.rejected_path.read_text(encoding="utf-8"),
                "Reset ODS",
            )
            self.assertFalse((output_dir / "motor_rejected.txt").exists())

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

    def test_outputs_from_nested_folders_preserve_input_folder_structure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            rejected_dir = root / "rejected"
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
                rejected_dir=rejected_dir,
            )

            self.assertEqual(
                [result.output_path for result in results],
                [
                    output_dir / "Group One" / "capture_cleaned.txt",
                    output_dir / "Group Two" / "capture_cleaned.txt",
                ],
            )
            for result in results:
                self.assertEqual(result.rejected_path.parent, rejected_dir)
                self.assertTrue(result.output_path.exists())
                self.assertTrue(result.rejected_path.exists())
            self.assertEqual(len(list(output_dir.iterdir())), 2)
            self.assertEqual(len(list(rejected_dir.iterdir())), 2)

    def test_similar_nested_paths_keep_outputs_in_separate_folders(self) -> None:
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
                file_path.write_text(
                    "2571 22C3 3D1F 3D1F\nReset ODS\n",
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
                [result.output_path for result in results],
                [
                    output_dir / "a_b" / "c" / "run_cleaned.txt",
                    output_dir / "a" / "b_c" / "run_cleaned.txt",
                ],
            )
            self.assertEqual(
                [result.rejected_path.name for result in results],
                [
                    "a_b_c_run_rejected.txt",
                    "a_b_c_run_002_rejected.txt",
                ],
            )

    def test_main_processes_all_files_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            rejected_dir = root / "rejected"
            loose_file = input_dir / "loose.txt"
            nested_file = input_dir / "Group" / "nested.txt"
            nested_file.parent.mkdir(parents=True)
            loose_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")
            nested_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch.object(txt_parser, "REJECTED_DIR", rejected_dir),
                patch("builtins.input", side_effect=["1", "3", "2", ""]),
                redirect_stdout(io.StringIO()),
            ):
                txt_parser.main()

            self.assertTrue((output_dir / "loose_cleaned.txt").exists())
            self.assertTrue(
                (output_dir / "Group" / "nested_cleaned.txt").exists()
            )

    def test_main_processes_a_selected_folder_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            rejected_dir = root / "rejected"
            nested_file = input_dir / "Group" / "Subgroup" / "run.txt"
            nested_file.parent.mkdir(parents=True)
            nested_file.write_text("2571 22C3 3D1F 3D1F S 0135\n", encoding="utf-8")

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch.object(txt_parser, "REJECTED_DIR", rejected_dir),
                patch("builtins.input", side_effect=["3", "1", "3", "2", ""]),
                redirect_stdout(io.StringIO()),
            ):
                txt_parser.main()

            self.assertTrue(
                (output_dir / "Group" / "Subgroup" / "run_cleaned.txt").exists()
            )

    def test_can_return_from_folder_selection_to_process_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            rejected_dir = root / "rejected"
            loose_file = input_dir / "loose.txt"
            nested_file = input_dir / "Group" / "nested.txt"
            nested_file.parent.mkdir(parents=True)
            loose_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")
            nested_file.write_text("2571 22C3 3D1F 3D1F\n", encoding="utf-8")
            captured_output = io.StringIO()

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch.object(txt_parser, "REJECTED_DIR", rejected_dir),
                patch("builtins.input", side_effect=["3", "0", "1", "3", "2", ""]),
                redirect_stdout(captured_output),
            ):
                txt_parser.main()

            self.assertTrue((output_dir / "loose_cleaned.txt").exists())
            self.assertTrue(
                (output_dir / "Group" / "nested_cleaned.txt").exists()
            )
            self.assertIn("0. Back to main menu", captured_output.getvalue())

    def test_main_processes_a_selected_loose_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            input_dir = root / "input"
            output_dir = root / "output"
            rejected_dir = root / "rejected"
            input_dir.mkdir()
            loose_file = input_dir / "run.txt"
            loose_file.write_text(
                "2571 22C3 3D1F 3D1F S 0135\nReset ODS\n",
                encoding="utf-8",
            )

            with (
                patch.object(txt_parser, "INPUT_DIR", input_dir),
                patch.object(txt_parser, "OUTPUT_DIR", output_dir),
                patch.object(txt_parser, "REJECTED_DIR", rejected_dir),
                patch.object(txt_parser, "date") as mocked_date,
                patch("builtins.input", side_effect=["2", "1", "3", "1", ""]),
                redirect_stdout(io.StringIO()),
            ):
                mocked_date.today.return_value.isoformat.return_value = "2026-11-02"
                txt_parser.main()

            self.assertTrue(
                (output_dir / "run_2026-11-02_cleaned.txt").exists()
            )
            self.assertTrue(
                (rejected_dir / "run_2026-11-02_rejected.txt").exists()
            )


if __name__ == "__main__":
    unittest.main()
