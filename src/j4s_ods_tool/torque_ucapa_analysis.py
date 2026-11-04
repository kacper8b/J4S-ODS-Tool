from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import sensitivity_analysis
from .sensitivity_analysis import parse_cleaned_file

SAMPLE_INTERVAL_SECONDS = Decimal("0.02")
CLEANED_FILE_PATTERN = "*_cleaned.txt"


def parse_time_interval(
    start_text: str,
    end_text: str,
) -> tuple[Decimal, Decimal]:
    try:
        start_seconds = Decimal(start_text.strip())
        end_seconds = Decimal(end_text.strip())
    except InvalidOperation as error:
        raise ValueError("Enter the interval in seconds as numeric values.") from error

    if not start_seconds.is_finite() or not end_seconds.is_finite():
        raise ValueError("Interval times must be finite numbers.")
    if start_seconds < 0 or end_seconds < 0:
        raise ValueError("Interval times cannot be negative.")
    if start_seconds > end_seconds:
        raise ValueError("The interval start must not be after its end.")

    return start_seconds, end_seconds


def read_time_interval() -> tuple[Decimal, Decimal]:
    while True:
        start_text = input("\nInterval start in seconds: ")
        end_text = input("Interval end in seconds: ")
        try:
            return parse_time_interval(start_text, end_text)
        except ValueError as error:
            print(error)


def list_source_folders(source_dir: Path) -> list[Path]:
    return sorted(
        folder
        for folder in source_dir.iterdir()
        if folder.is_dir()
        and next(folder.rglob(CLEANED_FILE_PATTERN), None) is not None
    )


def _select_folder(
    source_dir: Path,
    folders: list[Path],
    prompt: str,
) -> Path | None:
    while True:
        print()
        for index, folder in enumerate(folders, start=1):
            print(f"{index}. {folder.relative_to(source_dir)}")
        print("0. Back")
        choice = input(f"\n{prompt}: ").strip()
        if choice == "0":
            return None

        try:
            selected_index = int(choice)
        except ValueError:
            print("Enter a number.")
            continue

        if 1 <= selected_index <= len(folders):
            return folders[selected_index - 1]
        print("Invalid number.")


def select_folder_pair(source_dir: Path) -> tuple[Path, Path] | None:
    folders = list_source_folders(source_dir)
    if len(folders) < 2:
        print("At least two folders with cleaned TXT files are required.")
        return None

    first_folder = _select_folder(source_dir, folders, "Choose the first folder")
    if first_folder is None:
        return None

    remaining_folders = [folder for folder in folders if folder != first_folder]
    second_folder = _select_folder(
        source_dir,
        remaining_folders,
        "Choose the second folder",
    )
    if second_folder is None:
        return None

    return first_folder, second_folder


def calculate_folder_mean(
    folder: Path,
    start_seconds: Decimal,
    end_seconds: Decimal,
) -> Decimal | None:
    total = 0
    count = 0

    for file_path in sorted(folder.rglob(CLEANED_FILE_PATTERN)):
        records = parse_cleaned_file(file_path)
        for record_index, record in enumerate(records):
            sample_time = SAMPLE_INTERVAL_SECONDS * record_index
            if start_seconds <= sample_time <= end_seconds:
                total += record.ods
                count += 1

    if count == 0:
        return None
    return Decimal(total) / count


def main() -> None:
    for directory in (
        sensitivity_analysis.OUTPUT_DIR,
        sensitivity_analysis.INPUT_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    source_dir = sensitivity_analysis.select_source()
    if source_dir is None:
        return

    folders = select_folder_pair(source_dir)
    if folders is None:
        return

    start_seconds, end_seconds = read_time_interval()
    first_folder, second_folder = folders
    first_mean = calculate_folder_mean(first_folder, start_seconds, end_seconds)
    second_mean = calculate_folder_mean(second_folder, start_seconds, end_seconds)

    if first_mean is None or second_mean is None:
        missing_folders = [
            folder.name
            for folder, mean in (
                (first_folder, first_mean),
                (second_folder, second_mean),
            )
            if mean is None
        ]
        print(
            "\nNo records fall within the selected interval for: "
            + ", ".join(missing_folders)
        )
        print("The comparison was not calculated.")
        return

    difference = second_mean - first_mean
    print("\nTorque vs Ucapa")
    print(f"Interval: {start_seconds} to {end_seconds} seconds (inclusive)")
    print(f"{first_folder.name} mean Ucap: {first_mean:.2f}")
    print(f"{second_folder.name} mean Ucap: {second_mean:.2f}")
    print(f"Difference (second folder - first): {difference:.2f}")
