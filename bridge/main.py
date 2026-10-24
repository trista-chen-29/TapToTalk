"""Bridge hello. Prints one line and the size of the locked catalog."""

from __future__ import annotations

from bridge.phrases import load_phrases


def main() -> None:
    catalog = load_phrases()
    count = len(catalog["phrases"])
    print(f"taptotalk bridge hello ({count} phrases)")


if __name__ == "__main__":
    main()
