from __future__ import annotations

import argparse
import sys
from pathlib import Path

from core.config import ConfigError
from core.runtime import build_runtime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aimo v3 runtime bootstrap")
    parser.add_argument("--config", default="aimo.conf", help="Path to aimo.conf")
    parser.add_argument(
        "--require-secrets",
        action="store_true",
        help="Require production secrets such as Discord and OpenAI credentials",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate runtime configuration without starting integrations",
    )
    args = parser.parse_args(argv)

    try:
        runtime = build_runtime(Path(args.config), require_secrets=args.require_secrets)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"Startup validation error: {exc}", file=sys.stderr)
        return 2

    if args.check:
        language = runtime.config.bot.language.value
        print(f"Aimo config OK: language={language}")
        return 0

    print("Aimo v3 runtime foundation is valid; production integrations are not wired yet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

