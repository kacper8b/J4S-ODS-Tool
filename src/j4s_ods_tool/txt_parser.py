from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
INPUT_DIR = WORKSPACE_DIR / "input"
OUTPUT_DIR = WORKSPACE_DIR / "output"
REJECTED_DIR = WORKSPACE_DIR / "rejected"

VALID_SYMBOLS = {"S", "R", "E", "N", "X", "Y"}
SYMBOL_PRIORITY = {
    "S": 1,
    "R": 2,
    "E": 3,
    "N": 4,
    "Y": 5,
    "X": 6,
}


@dataclass(frozen=True)
class ProcessingResult:
    input_path: Path
    output_path: Path
    rejected_path: Path | None
    valid_count: int
    rejected_count: int
    fixed_symbol_count: int


def ensure_directories() -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REJECTED_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return re.sub(r"\s+", "_", name)


def is_hex4(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Fa-f]{4}", value))


def is_e_symbol(token: str) -> bool:
    return token == "E" or (
        re.fullmatch(r"E[0-9A-Fa-f]+", token) is not None
        and int(token[1:], 16) <= 0xFFFF
    )


def fix_stuck_symbols(line: str) -> str:
    previous = None

    while previous != line:
        previous = line
        line = re.sub(
            r"\bE[0-9A-Fa-f]+\b|([0-9A-Fa-f]{4})([SRNEXY])\b",
            lambda match: (
                f"{match.group(1)} {match.group(2)}"
                if match.group(1) is not None
                else match.group(0)
            ),
            line,
        )

    return line


def parse_line(line: str) -> tuple[str, str, str, str, str, str, str] | None:
    tokens = re.split(r"\s+", fix_stuck_symbols(line).strip())

    if len(tokens) < 4:
        return None

    first_four = [token[:4] for token in tokens[:4]]

    if not all(is_hex4(token) for token in first_four):
        return None

    value = ""
    symbols = []
    extra_tokens = tokens[4:]
    has_e_symbol = any(is_e_symbol(token) for token in extra_tokens)

    for token in extra_tokens:
        value_with_suffix = re.fullmatch(
            r"([0-9A-Fa-f]{4})([^0-9A-Fa-f].*)", token
        )

        if is_e_symbol(token):
            symbols.append("E")
        elif has_e_symbol and value_with_suffix:
            if value:
                return None
            value = value_with_suffix.group(1)
        elif is_hex4(token):
            if value:
                return None
            value = token
        elif token in VALID_SYMBOLS:
            symbols.append(token)
        else:
            return None

    if len(symbols) > 2:
        return None

    symbols.sort(key=SYMBOL_PRIORITY.__getitem__)
    symbol_1 = symbols[0] if symbols else ""
    symbol_2 = symbols[1] if len(symbols) == 2 else ""

    return (
        first_four[0],
        first_four[1],
        first_four[2],
        first_four[3],
        value,
        symbol_1,
        symbol_2,
    )


def process_file(
    file_path: Path,
    output_name: str | None = None,
    *,
    output_dir: Path = OUTPUT_DIR,
    rejected_dir: Path = REJECTED_DIR,
) -> ProcessingResult:
    valid_rows = []
    rejected_rows = []
    fixed_symbol_count = 0

    with file_path.open("r", encoding="utf-8", errors="ignore") as source:
        lines = source.readlines()

    for original_line in lines:
        stripped = original_line.strip()

        if not stripped or stripped.lower() == "<br>":
            continue

        fixed = fix_stuck_symbols(stripped)
        if fixed != stripped:
            fixed_symbol_count += 1

        parsed = parse_line(fixed)
        if parsed is None:
            rejected_rows.append(stripped)
        else:
            valid_rows.append("\t".join(parsed))

    base_name = output_name if output_name else file_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    processed_path = output_dir / f"{base_name}_processed.txt"
    processed_path.write_text("\n".join(valid_rows), encoding="utf-8")

    rejected_path = None
    if rejected_rows:
        rejected_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = rejected_dir / f"{base_name}_rejected.txt"
        rejected_path.write_text("\n".join(rejected_rows), encoding="utf-8")

    result = ProcessingResult(
        input_path=file_path,
        output_path=processed_path,
        rejected_path=rejected_path,
        valid_count=len(valid_rows),
        rejected_count=len(rejected_rows),
        fixed_symbol_count=fixed_symbol_count,
    )
    print_result(result)
    return result


def print_result(result: ProcessingResult) -> None:
    print()
    print(f"File               : {result.input_path.name}")
    print(f"Valid records      : {result.valid_count}")
    print(f"Rejected records   : {result.rejected_count}")
    print(f"Repaired symbols   : {result.fixed_symbol_count}")
    print(f"Output             : {result.output_path.name}")
    if result.rejected_path is not None:
        print(f"Rejected           : {result.rejected_path.name}")
    else:
        print("Rejected           : none")


def get_txt_files(input_dir: Path = INPUT_DIR) -> list[Path]:
    return sorted(input_dir.rglob("*.txt"))


def get_loose_txt_files(input_dir: Path = INPUT_DIR) -> list[Path]:
    return sorted(input_dir.glob("*.txt"))


def get_input_folders(input_dir: Path = INPUT_DIR) -> list[Path]:
    return sorted(path for path in input_dir.iterdir() if path.is_dir())


def ask_naming_mode() -> tuple[int, str, str]:
    print("\nFile naming:")
    print("1 - New base name + numbering")
    print("2 - Add prefix")
    print("3 - Keep original names")

    mode = input("\nNaming choice: ").strip()
    if mode == "1":
        base_name = sanitize_filename(input("Enter new base name: "))
        return 1, base_name, ""
    if mode == "2":
        prefix = sanitize_filename(input("Enter prefix: "))
        return 2, "", prefix
    return 3, "", ""


def ask_include_date() -> bool:
    print("\nAdd current date to output filenames?")
    print("1 - Yes")
    print("2 - No")

    while True:
        choice = input("\nDate choice: ").strip()
        if choice == "1":
            return True
        if choice == "2":
            return False
        print("Choose 1 or 2.")


def choose_file(files: list[Path], prompt: str) -> Path | None:
    print(f"\n{prompt}\n")
    for index, file_path in enumerate(files, start=1):
        print(f"{index}. {file_path.name}")

    try:
        choice = int(input("\nChoose a file number: "))
        if not 1 <= choice <= len(files):
            print("Invalid number.")
            return None
        return files[choice - 1]
    except ValueError:
        print("Enter a number.")
        return None


def choose_folder(folders: list[Path]) -> Path | None:
    print("\nAvailable folders:\n")
    for index, folder in enumerate(folders, start=1):
        print(f"{index}. {folder.name}")
    print("0. Back to main menu")

    try:
        choice = int(input("\nChoose a folder number: "))
        if choice == 0:
            return None
        if not 1 <= choice <= len(folders):
            print("Invalid number.")
            return None
        return folders[choice - 1]
    except ValueError:
        print("Enter a number.")
        return None


def build_output_name(
    file_path: Path,
    input_dir: Path,
    naming_mode: int,
    base_name: str,
    prefix: str,
    index: int,
    current_date: str | None = None,
) -> str:
    if naming_mode == 1:
        name = f"{base_name}_{index:03d}"
    elif naming_mode == 2:
        name = f"{prefix}_{file_path.stem}"
    else:
        name = file_path.stem

    relative_parent = file_path.parent.relative_to(input_dir)
    folder_prefix = sanitize_filename("_".join(relative_parent.parts))
    name = f"{folder_prefix}_{name}" if folder_prefix else name
    return f"{name}_{current_date}" if current_date else name


def process_files(
    files: list[Path],
    input_dir: Path,
    naming_mode: int,
    base_name: str,
    prefix: str,
    *,
    output_dir: Path | None = None,
    rejected_dir: Path | None = None,
    include_date: bool = False,
) -> list[ProcessingResult]:
    if output_dir is None:
        output_dir = OUTPUT_DIR
    if rejected_dir is None:
        rejected_dir = REJECTED_DIR

    results = []
    used_names = set()
    current_date = date.today().isoformat() if include_date else None
    for index, file_path in enumerate(files, start=1):
        output_name = build_output_name(
            file_path,
            input_dir,
            naming_mode,
            base_name,
            prefix,
            index,
            current_date,
        )
        unique_name = output_name
        suffix = 2
        while unique_name.casefold() in used_names:
            unique_name = f"{output_name}_{suffix:03d}"
            suffix += 1
        used_names.add(unique_name.casefold())
        results.append(
            process_file(
                file_path,
                unique_name,
                output_dir=output_dir,
                rejected_dir=rejected_dir,
            )
        )
    return results


def main() -> None:
    ensure_directories()
    files = get_txt_files(INPUT_DIR)
    loose_files = get_loose_txt_files(INPUT_DIR)
    folders = get_input_folders(INPUT_DIR)

    print("=" * 60)
    print("MOTOR DATA PARSER")
    print("=" * 60)

    if not files:
        print("\nNo TXT files found in the input folder or its subfolders.")
        print(f"\nPath:\n{INPUT_DIR}")
        input("\nPress ENTER to exit...")
        return

    selected_files = []
    while True:
        print("\nOptions:")
        print(f"1 - All files ({len(files)})")
        if loose_files:
            print(f"2 - One file from input root ({len(loose_files)})")
        if folders:
            print(f"3 - One folder ({len(folders)})")
        print("0 - Exit")
        choice = input("\nChoice: ").strip()

        if choice == "1":
            selected_files = files
            break
        if choice == "2" and loose_files:
            selected_file = choose_file(loose_files, "Loose files in input root:")
            if selected_file is not None:
                selected_files = [selected_file]
                break
            continue
        if choice == "3" and folders:
            selected_folder = choose_folder(folders)
            if selected_folder is None:
                continue
            selected_files = get_txt_files(selected_folder)
            if not selected_files:
                print("No TXT files found in the selected folder or its subfolders.")
                continue
            break
        if choice == "0":
            break
        print("Unknown option.")

    if selected_files:
        naming_mode, base_name, prefix = ask_naming_mode()
        include_date = ask_include_date()
        process_files(
            selected_files,
            INPUT_DIR,
            naming_mode,
            base_name,
            prefix,
            include_date=include_date,
        )

    input("\nPress ENTER to exit...")


if __name__ == "__main__":
    main()
