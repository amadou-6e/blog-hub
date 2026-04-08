#!/usr/bin/env python3
"""
mermaid-export.py
=================
Extract every ```mermaid``` block from one or more Markdown files, save the
source as a .mmd file and download a rendered PNG from mermaid.ink, then
replace the fenced code block in the Markdown with an image reference.

Output layout (relative to the source .md file):
  assets/<md-stem>/diagram-1.mmd
  assets/<md-stem>/diagram-1.png
  assets/<md-stem>/diagram-2.mmd
  ...

Usage
-----
  # Single file
  python3 scripts/mermaid-export.py .spec/backend/agent/service.md

  # Glob — shell expansion
  python3 scripts/mermaid-export.py .spec/backend/*/service.md

  # Recursive glob (Python-level, use quotes to prevent shell expansion)
  python3 scripts/mermaid-export.py ".spec/**/*.md"

  # All service.md files at once
  python3 scripts/mermaid-export.py ".spec/backend/**/service.md" ".spec/backend/**/*.md"

Flags
-----
  --dry-run   Show what would change without writing any files.
  --force     Re-download PNGs even when the image file already exists.
"""

import argparse
import base64
import glob
import re
import sys
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex: matches a full ```mermaid … ``` fence (non-greedy, DOTALL)
# ---------------------------------------------------------------------------
MERMAID_FENCE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)

BASE_URL = "https://mermaid.ink/img"
USER_AGENT = "mermaid-export/1.0 (github.com/acisse/blog-hub)"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def ink_url(source: str) -> str:
    """Return the mermaid.ink PNG URL for a diagram source string."""
    encoded = base64.urlsafe_b64encode(source.encode()).decode()
    return f"{BASE_URL}/{encoded}"


def download_png(url: str, dest: Path, timeout: int = 20, retries: int = 3) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                dest.write_bytes(resp.read())
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 503 and attempt < retries:
                wait = 2**attempt  # 2s, 4s
                print(f"  rate-limited (503), retrying in {wait}s (attempt {attempt}/{retries})...")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as exc:
            if attempt < retries:
                time.sleep(2)
                continue
            raise


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


def process_md(md_path: Path, *, dry_run: bool, force: bool) -> int:
    """
    Process one Markdown file.
    Returns the number of diagrams replaced.
    """
    content = md_path.read_text(encoding="utf-8")
    # Normalise Windows CRLF so the regex works regardless of line endings
    content = content.replace("\r\n", "\n")
    original_crlf = "\r\n" in md_path.read_bytes().decode("utf-8", errors="replace")

    md_stem = md_path.stem
    assets_dir = md_path.parent / "assets" / md_stem

    counter = 0
    replaced = 0

    def replace_block(match: re.Match) -> str:
        nonlocal counter, replaced
        counter += 1
        source = match.group(1).strip()
        stem = f"diagram-{counter}"
        mmd_file = assets_dir / f"{stem}.mmd"
        png_file = assets_dir / f"{stem}.png"

        if dry_run:
            print(f"  [dry-run] would write {mmd_file.relative_to(md_path.parent)}")
            print(f"  [dry-run] would fetch  {png_file.relative_to(md_path.parent)}")
            replaced += 1
            rel = (assets_dir / f"{stem}.png").relative_to(md_path.parent).as_posix()
            return f"![{stem}]({rel})"

        # Create assets directory on first use
        assets_dir.mkdir(parents=True, exist_ok=True)

        # Save .mmd source
        mmd_file.write_text(source, encoding="utf-8")
        print(f"  wrote  {mmd_file.relative_to(md_path.parent)}")

        # Download PNG (skip if already present and --force not set)
        if png_file.exists() and not force:
            print(
                f"  skip   {png_file.relative_to(md_path.parent)} (already exists, use --force to re-download)"
            )
        else:
            url = ink_url(source)
            try:
                download_png(url, png_file)
                print(f"  fetched {png_file.relative_to(md_path.parent)}")
            except Exception as exc:
                print(f"  WARNING: PNG download failed for diagram-{counter}: {exc}")
                # Fall back: embed the mermaid.ink URL directly (no local file)
                replaced += 1
                return f"![{stem}]({url})"

        replaced += 1
        rel = png_file.relative_to(md_path.parent).as_posix()
        return f"![{stem}]({rel})"

    new_content = MERMAID_FENCE.sub(replace_block, content)

    if replaced == 0:
        print(f"  (no mermaid blocks found)")
        return 0

    if not dry_run and new_content != content:
        # Restore CRLF if the original file used it
        write_content = new_content.replace("\n", "\r\n") if original_crlf else new_content
        md_path.write_text(write_content, encoding="utf-8")
        print(f"  updated {md_path}")

    return replaced


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def resolve_paths(patterns: list[str]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        matched = glob.glob(pattern, recursive=True)
        if matched:
            paths.extend(Path(p) for p in sorted(matched))
        else:
            p = Path(pattern)
            if p.exists():
                paths.append(p)
            else:
                print(f"WARNING: no files matched '{pattern}'", file=sys.stderr)
    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            unique.append(p)
    return unique


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export mermaid blocks from Markdown to .mmd + .png files.")
    parser.add_argument(
        "files",
        nargs="+",
        metavar="FILE_OR_GLOB",
        help="Markdown file(s) or glob pattern(s) to process.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing any files.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download PNG even when it already exists.",
    )
    args = parser.parse_args()

    paths = resolve_paths(args.files)
    if not paths:
        print("No files to process.", file=sys.stderr)
        sys.exit(1)

    total_diagrams = 0
    for md_path in paths:
        print(f"\nProcessing {md_path} ...")
        count = process_md(md_path, dry_run=args.dry_run, force=args.force)
        total_diagrams += count

    print(f"\nDone. {total_diagrams} diagram(s) processed across {len(paths)} file(s).")


if __name__ == "__main__":
    main()
