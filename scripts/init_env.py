#!/usr/bin/env python3
"""Create a .env template in the workspace root.

The AI running the skill calls this, then asks the user to fill in the values.
Keeping it in a script (rather than hand-writing the file) means the path is
always the one the resolver will actually read.

Usage:
    python scripts/init_env.py            # create <cwd>/.env if absent
    python scripts/init_env.py --show     # print where it would go
    python scripts/init_env.py --force    # overwrite
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--show", action="store_true", help="print the path only")
    ap.add_argument("--force", action="store_true", help="overwrite an existing file")
    args = ap.parse_args()

    path, source = config.resolve_env_file()

    if args.show:
        print(f"{path}\n({source})")
        return 0

    if path.exists() and not args.force:
        print(f"already exists: {path}")
        print("(use --force to overwrite)")
        return 0

    target, created = config.write_env_template(path, force=args.force)
    if created:
        print(f"created: {target}")
        print()
        print("Fill in your ZJU CAS credentials:")
        print("  CAS_USERNAME=<学号>")
        print("  CAS_PASSWORD=<密码>")
        print()
        print("This file stays local and should not be committed.")
    else:
        print(f"not created (already present): {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
