import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from j4s_ods_tool import __main__ as app
from j4s_ods_tool import independent_slope_analysis as slope
from j4s_ods_tool.sensitivity_analysis import LogRecord
from j4s_ods_tool.sr_mechanical_analysis import MotorMetadata


def records(
    values: list[int], startup_samples: int | None = None
) -> list[LogRecord]:
    if startup_samples is None:
        startup_samples = slope.DEFAULT_PARAMETERS.startup_samples
    return [
        LogRecord(i + 1, value, ())
        for i, value in enumerate([0] * startup_samples + values)
    ]


class DetectionTests(unittest.TestCase):
    def test_detects_signal_without_s_or_r_and_uses_minimum_not_closure(self) -> None:
        found = slope.analyze_records(records(
            [300 - 4 * i for i in range(11)] + [261, 284]
        ), "motor")
        self.assertEqual(len(found), 1)
        m = found[0]
        self.assertEqual((m.start_index, m.end_index), (100, 110))
        self.assertEqual((m.peak_value, m.minimum_value, m.amplitude), (300, 260, 40))
        self.assertEqual(m.duration_ms, 200)
        self.assertEqual((m.status, m.closure, m.file), ("VALID", "REBOUND", "motor"))

    def test_s_and_r_markers_do_not_change_signal_boundaries(self) -> None:
        source = records([300 - 4 * i for i in range(31)] + [204])
        marked = [
            replace(r, events=("S",) if i % 3 == 0 else ("R",))
            for i, r in enumerate(source)
        ]
        self.assertEqual(slope.analyze_records(source), slope.analyze_records(marked))

    def test_start_drop_threshold_and_amplitude_validation(self) -> None:
        self.assertEqual(slope.analyze_records(records([300, 269])), [])
        m = slope.analyze_records(records([300, 268]))[0]
        self.assertEqual(m.status, "INVALID")
        self.assertEqual(m.reason, "TOO_SHORT")

    def test_length_and_amplitude_thresholds_are_inclusive(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        for length, amplitude, reason in (
            (9, 32, "TOO_SHORT"),
            (10, 31, "INSUFFICIENT_AMPLITUDE"),
            (10, 32, ""),
            (10, 500, ""),
            (10, 501, "EXCESSIVE_AMPLITUDE"),
        ):
            with self.subTest(length=length, amplitude=amplitude):
                values = [1000 - (amplitude * i // length) for i in range(length + 1)]
                m = slope.analyze_records(records(values), parameters=parameters)[0]
                self.assertEqual(m.reason, reason)
                self.assertEqual(m.amplitude, amplitude)

    def test_joins_small_fragments_at_idle_limit_but_closes_after_limit(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        for gap, count in ((15, 1), (16, 2)):
            with self.subTest(gap=gap):
                values = [300, 280] + [280] * gap + [260, 244]
                found = slope.analyze_records(records(values), parameters=parameters)
                self.assertEqual(len(found), count)
                if count == 1:
                    self.assertEqual(found[0].amplitude, 56)
                    self.assertEqual(found[0].status, "VALID")
                else:
                    self.assertEqual(found[0].closure, "INACTIVITY")

    def test_cumulative_progress_resets_inactivity_counter(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        values = [300, 284]
        for i in range(1, 9):
            values.extend([284 - i] * 3)
        found = slope.analyze_records(records(values), parameters=parameters)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].end_index, 123)
        self.assertEqual(found[0].closure, "BLOCK_BOUNDARY")

    def test_rebound_threshold_and_new_peak_after_closure(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        for rebound, expected_count in ((23, 1), (24, 2)):
            with self.subTest(rebound=rebound):
                values = [300, 280, 280 + rebound, 260, 244]
                found = slope.analyze_records(records(values), parameters=parameters)
                self.assertEqual(len(found), expected_count)
                if expected_count == 2:
                    self.assertEqual(found[0].closure, "REBOUND")
                    self.assertEqual(found[1].start_index, 102)

    def test_plateau_peaks_use_latest_index_minimum_uses_first(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        m = slope.analyze_records(
            records([300, 300, 280, 280, 304]), parameters=parameters
        )[0]
        self.assertEqual((m.start_index, m.end_index), (101, 102))

    def test_startup_samples_and_empty_inputs_produce_no_candidates(self) -> None:
        self.assertEqual(slope.analyze_records([]), [])
        self.assertEqual(slope.analyze_records(records([])), [])
        source = [LogRecord(i + 1, 1000 - i * 4, ()) for i in range(100)]
        source += [LogRecord(101, 500, ()), LogRecord(102, 500, ())]
        self.assertEqual(slope.analyze_records(source), [])

    def test_zero_breaks_block_without_joining_across_it(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        found = slope.analyze_records(
            records([300, 280, 0, 250, 230]), parameters=parameters
        )
        self.assertEqual(len(found), 2)
        self.assertEqual([m.closure for m in found], ["BLOCK_BOUNDARY"] * 2)
        self.assertEqual([(m.start_index, m.end_index) for m in found],
                         [(100, 101), (103, 104)])

    def test_obstacle_zone_inclusive_edges_and_s_replacement(self) -> None:
        source = records([300] * 150)
        source[210] = replace(source[210], events=("S",))
        source[230] = replace(source[230], events=("S",))
        source[240] = replace(source[240], events=("E",))
        excluded = slope._excluded_records(source)
        self.assertFalse(excluded[129])
        self.assertTrue(all(excluded[130:241]))
        self.assertFalse(excluded[241])

    def test_obstacle_protection_splits_active_slope(self) -> None:
        parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
        source = records([500] * 150)
        source[128] = replace(source[128], ods=480)
        source[229] = replace(source[229], events=("S",))
        source[239] = replace(source[239], events=("E",))
        source[240] = replace(source[240], ods=400)
        source[241] = replace(source[241], ods=360)
        found = slope.analyze_records(source, parameters=parameters)
        self.assertEqual(len(found), 2)
        self.assertEqual((found[0].start_index, found[0].end_index), (127, 128))
        self.assertEqual(found[0].closure, "BLOCK_BOUNDARY")
        self.assertEqual((found[1].start_index, found[1].end_index), (240, 241))

    def test_x_closes_recorded_start_without_obstacle_zone(self) -> None:
        source = records([300] * 130)
        source[200] = replace(source[200], events=("S",))
        source[201] = replace(source[201], events=("X",))
        source[220] = replace(source[220], events=("E",))
        self.assertFalse(any(slope._excluded_records(source)[100:]))

    def test_rejects_multiple_terminal_markers(self) -> None:
        source = records([300])
        source[100] = replace(source[100], events=("R", "E"))
        with self.assertRaisesRegex(ValueError, "multiple terminal events"):
            slope.analyze_records(source)

    def test_custom_parameters_change_detection_and_acceptance(self) -> None:
        parameters = replace(
            slope.DEFAULT_PARAMETERS,
            startup_samples=0,
            start_drop=10,
            end_rebound=5,
            min_duration_intervals=2,
            min_amplitude=5,
            max_amplitude=20,
        )
        found = slope.analyze_records(
            records([100, 90, 85, 90], startup_samples=0),
            parameters=parameters,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(
            (found[0].start_index, found[0].end_index, found[0].amplitude),
            (0, 2, 15),
        )
        self.assertEqual((found[0].status, found[0].closure), ("VALID", "REBOUND"))

    def test_custom_progress_and_inactivity_parameters_close_slope(self) -> None:
        parameters = replace(
            slope.DEFAULT_PARAMETERS,
            startup_samples=0,
            start_drop=5,
            progress_drop=100,
            max_idle_intervals=0,
            min_duration_intervals=0,
            min_amplitude=0,
            max_amplitude=1000,
        )
        found = slope.analyze_records(
            records([100, 90, 80], startup_samples=0),
            parameters=parameters,
        )
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].closure, "INACTIVITY")

    def test_custom_startup_and_obstacle_exclusion_parameters(self) -> None:
        parameters = replace(
            slope.DEFAULT_PARAMETERS,
            startup_samples=2,
            exclusion_before_obstacle_s=2,
        )
        source = records([500] * 8, startup_samples=0)
        source[4] = replace(source[4], events=("S",))
        source[6] = replace(source[6], events=("E",))
        excluded = slope._excluded_records(source, parameters)
        self.assertEqual(excluded[:2], [True, True])
        self.assertEqual(excluded[2:7], [True] * 5)
        self.assertFalse(excluded[7])


class ParameterSettingsTests(unittest.TestCase):
    def test_missing_settings_use_defaults_without_creating_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            self.assertEqual(slope.load_parameters(path), slope.DEFAULT_PARAMETERS)
            self.assertFalse(path.exists())

    def test_settings_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            parameters = replace(slope.DEFAULT_PARAMETERS, startup_samples=125)
            slope.save_parameters(parameters, path)
            self.assertEqual(slope.load_parameters(path), parameters)

    def test_invalid_settings_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                slope.load_parameters(path)
            path.write_text('{"unknown": 1}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid parameter fields"):
                slope.load_parameters(path)

    def test_invalid_parameter_values_are_rejected(self) -> None:
        for parameters in (
            replace(slope.DEFAULT_PARAMETERS, startup_samples=-1),
            replace(slope.DEFAULT_PARAMETERS, min_amplitude=501),
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValueError):
                    slope.validate_parameters(parameters)

    def test_settings_menu_saves_edits_and_restores_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            edit_answers = (
                ["1", "125"] + [""] * (len(slope.PARAMETER_LABELS) - 1) + ["0"]
            )
            with patch("builtins.input", side_effect=edit_answers), \
                    redirect_stdout(io.StringIO()):
                slope.configure_parameters(path)
            self.assertEqual(
                slope.load_parameters(path),
                replace(slope.DEFAULT_PARAMETERS, startup_samples=125),
            )
            with patch("builtins.input", side_effect=["2", "y", "0"]), \
                    redirect_stdout(io.StringIO()):
                slope.configure_parameters(path)
            self.assertEqual(slope.load_parameters(path), slope.DEFAULT_PARAMETERS)


class ReportTests(unittest.TestCase):
    @staticmethod
    def write_input(path: Path, values: list[int]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(f"0001\t0002\t0003\t{r.ods:04X}\t\t\t\n" for r in records(values)),
            encoding="utf-8",
        )

    def test_reports_include_metadata_pooled_statistics_and_invalid_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "input" / "Group" / "first_cleaned.txt"
            second = root / "input" / "second_cleaned.txt"
            self.write_input(first, [300 - 4 * i for i in range(11)] + [284])
            self.write_input(second, [500 - 10 * i for i in range(11)] + [424, 400])
            original = first.read_bytes()
            metadata = MotorMetadata("J4S IO", "SLE", "A15", "6", "High")
            parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
            rows, found, paths = slope.analyze_files(
                [first, second], source_dir=root / "input",
                reports_dir=root / "reports", timestamp="test",
                metadata_by_folder={"Group": metadata},
                parameters=parameters,
            )
            self.assertIsNotNone(paths)
            self.assertEqual(first.read_bytes(), original)
            self.assertEqual(rows[-1]["File"], "ALL_FILES_POOLED")
            self.assertEqual(rows[-1]["Slope_Count"], 2)
            self.assertEqual(rows[-1]["Invalid_Slope_Count"], 1)
            self.assertEqual(rows[-1]["Average_Amplitude"], 70)
            self.assertEqual(rows[-1]["P95_Amplitude"], 97)
            self.assertEqual(rows[-1]["Amplitude_STD"], 42.43)
            self.assertEqual(rows[-1]["Average_Duration_ms"], 200)
            self.assertEqual(rows[-1]["Project"], "")
            self.assertEqual(found[0].metadata, metadata.as_values())
            with paths[0].open(newline="", encoding="utf-8") as handle:
                saved = list(csv.DictReader(handle))
            with paths[1].open(newline="", encoding="utf-8") as handle:
                details = list(csv.DictReader(handle))
            self.assertEqual(list(saved[0]), slope.SUMMARY_FIELDS)
            self.assertEqual(list(details[0]), slope.DETAIL_FIELDS)
            self.assertEqual(details[0]["Project"], "J4S IO")
            self.assertEqual(details[-1]["Status"], "INVALID")
            self.assertEqual(len(details), 3)

    def test_all_invalid_creates_reports_but_no_candidates_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "input" / "invalid_cleaned.txt"
            self.write_input(path, [300, 280])
            parameters = replace(slope.DEFAULT_PARAMETERS, start_drop=16)
            rows, _, reports = slope.analyze_files(
                [path], source_dir=path.parent, reports_dir=root / "reports",
                parameters=parameters,
            )
            self.assertIsNotNone(reports)
            self.assertEqual(rows[-1]["Average_Amplitude"], "")
            before = list((root / "reports").iterdir())
            self.write_input(path, [300, 300])
            _, found, reports = slope.analyze_files(
                [path], source_dir=path.parent, reports_dir=root / "reports",
                parameters=parameters,
            )
            self.assertEqual(found, [])
            self.assertIsNone(reports)
            self.assertEqual(before, list((root / "reports").iterdir()))

    def test_report_pair_collision_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            existing = root / "independent_slope_details_test.csv"
            existing.write_text("keep", encoding="utf-8")
            paths = slope.write_reports([], [], root, "test")
            self.assertEqual(existing.read_text(), "keep")
            self.assertEqual(paths[0].name, "independent_slope_summary_test_002.csv")
            self.assertEqual(paths[1].name, "independent_slope_details_test_002.csv")


class MenuTests(unittest.TestCase):
    def test_application_dispatches_option_four(self) -> None:
        with patch("builtins.input", side_effect=["4", "0", ""]), \
                patch.object(slope, "main") as run, redirect_stdout(io.StringIO()):
            app.main()
        run.assert_called_once_with()

    def test_back_does_not_start_processing(self) -> None:
        with patch.object(slope, "load_parameters", return_value=slope.DEFAULT_PARAMETERS), \
                patch.object(slope, "select_source", return_value=None), \
                patch.object(slope, "analyze_files") as analyze:
            slope.main()
        analyze.assert_not_called()

    def test_main_wires_source_metadata_and_reports_no_candidates(self) -> None:
        source = Path("input")
        files = [source / "motor_cleaned.txt"]
        metadata = {".": MotorMetadata()}
        with patch.object(slope, "load_parameters", return_value=slope.DEFAULT_PARAMETERS), \
                patch.object(slope, "select_source", return_value=source), \
                patch.object(slope, "select_cleaned_files", return_value=files), \
                patch.object(slope, "resolve_motor_metadata", return_value=metadata), \
                patch.object(slope, "analyze_files", return_value=([], [], None)) as analyze, \
                redirect_stdout(io.StringIO()) as output:
            slope.main()
        analyze.assert_called_once_with(
            files,
            source_dir=source,
            metadata_by_folder=metadata,
            parameters=slope.DEFAULT_PARAMETERS,
        )
        self.assertIn("No slope candidates", output.getvalue())

    def test_application_dispatches_parameter_configuration(self) -> None:
        with patch("builtins.input", side_effect=["5", "0", ""]), \
                patch.object(slope, "configure_parameters") as configure, \
                redirect_stdout(io.StringIO()):
            app.main()
        configure.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
