from .app import mcp
from .lifecycle import run_stdio


def main() -> None:
    run_stdio(mcp)


if __name__ == "__main__":
    main()
