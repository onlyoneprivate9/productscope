from __future__ import annotations

import sys


REQUIRED_MODULES = ("pandas", "openpyxl", "matplotlib", "tkinter")


def main() -> int:
    missing: list[str] = []
    for name in REQUIRED_MODULES:
        try:
            __import__(name)
        except Exception as exc:
            missing.append(f"{name} ({exc})")

    if not missing:
        return 0

    print("Missing or broken dependencies:")
    for item in missing:
        print(f"  - {item}")
    print()
    print("Install dependencies from this folder with:")
    print(f"  {sys.executable} -m pip install -r requirements.txt")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
