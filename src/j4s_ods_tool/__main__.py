from . import (
    independent_slope_analysis,
    sensitivity_analysis,
    sr_mechanical_analysis,
    txt_parser,
)


def main() -> None:
    while True:
        print("\nJ4S ODS TOOL")
        print("1 - Parse raw motor logs")
        print("2 - Obstacle measurement")
        print("3 - S-R mechanical analysis")
        print("4 - Independent slope analysis")
        print("0 - Exit")
        choice = input("\nChoice: ").strip()

        if choice == "1":
            txt_parser.main()
        elif choice == "2":
            sensitivity_analysis.main()
        elif choice == "3":
            sr_mechanical_analysis.main()
        elif choice == "4":
            independent_slope_analysis.main()
        elif choice == "0":
            input("\nPress ENTER to exit...")
            return
        else:
            print("Unknown option.")


if __name__ == "__main__":
    main()
