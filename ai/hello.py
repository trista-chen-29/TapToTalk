"""AI hello. Returns its input unchanged and prints that result."""

from __future__ import annotations


def echo(value: object) -> object:
    """Return the input unchanged."""
    return value


def main() -> None:
    print(echo("taptotalk ai hello"))


if __name__ == "__main__":
    main()
