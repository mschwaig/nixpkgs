#!/usr/bin/env python3
"""
Terminal UI for reviewing AI-generated packages against nixpkgs originals.

This tool displays diffs using difftastic and allows manual review with keybindings
to mark packages as equivalent/not equivalent. Results are saved to CSV.
"""

import curses
import subprocess
import csv
import sys
import os
import shutil
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class PackageReview:
    """Represents a package to review."""
    csv_id: int
    package_name: str
    pname: str
    ai_dir: Path
    ref_dir: Path
    decision: Optional[str] = None  # "equivalent", "not_equivalent", "skip"
    notes: str = ""


@dataclass
class ReviewSession:
    """Manages the review session state."""
    packages: List[PackageReview]
    current_index: int = 0
    output_csv: Path = Path("review_results.csv")
    decisions: Dict[int, Dict] = field(default_factory=dict)

    def load_existing_decisions(self):
        """Load existing decisions from CSV if it exists."""
        if self.output_csv.exists():
            with open(self.output_csv, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    csv_id = int(row['csv_id'])
                    self.decisions[csv_id] = {
                        'decision': row['decision'],
                        'notes': row.get('notes', '')
                    }
                    # Update package objects
                    for pkg in self.packages:
                        if pkg.csv_id == csv_id:
                            pkg.decision = row['decision']
                            pkg.notes = row.get('notes', '')

    def save_decision(self, pkg: PackageReview):
        """Save a single decision to the CSV file."""
        self.decisions[pkg.csv_id] = {
            'decision': pkg.decision,
            'notes': pkg.notes
        }
        self._write_csv()

    def _write_csv(self):
        """Write all decisions to CSV."""
        with open(self.output_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['csv_id', 'package_name', 'pname', 'decision', 'notes'])

            for pkg in self.packages:
                if pkg.csv_id in self.decisions:
                    decision_data = self.decisions[pkg.csv_id]
                    writer.writerow([
                        pkg.csv_id,
                        pkg.package_name,
                        pkg.pname,
                        decision_data['decision'],
                        decision_data['notes']
                    ])

    def get_current_package(self) -> Optional[PackageReview]:
        """Get the current package being reviewed."""
        if 0 <= self.current_index < len(self.packages):
            return self.packages[self.current_index]
        return None

    def next_package(self) -> bool:
        """Move to next package. Returns True if successful."""
        if self.current_index < len(self.packages) - 1:
            self.current_index += 1
            return True
        return False

    def prev_package(self) -> bool:
        """Move to previous package. Returns True if successful."""
        if self.current_index > 0:
            self.current_index -= 1
            return True
        return False

    def get_progress(self) -> Tuple[int, int, int]:
        """Returns (current, total, reviewed_count)."""
        reviewed = sum(1 for pkg in self.packages if pkg.decision)
        return (self.current_index + 1, len(self.packages), reviewed)


def find_main_package_file(directory: Path) -> Optional[Path]:
    """Find the main package file (package.nix or default.nix)."""
    if (directory / "package.nix").exists():
        return directory / "package.nix"
    elif (directory / "default.nix").exists():
        return directory / "default.nix"
    return None


def get_supplemental_files(directory: Path) -> List[Path]:
    """Get all supplemental files in a directory (excluding main package file)."""
    if not directory.exists():
        return []

    main_file = find_main_package_file(directory)
    files = []

    for file in sorted(directory.iterdir()):
        if file.is_file() and file != main_file:
            files.append(file)

    return files


def run_difftastic(file1: Path, file2: Path, color: bool = True) -> str:
    """Run difftastic on two files and return the output."""
    # Check if difftastic is available
    if shutil.which('difftastic'):
        if color:
            cmd = ['difftastic', '--color', 'always', str(file1), str(file2)]
        else:
            cmd = ['difftastic', '--color', 'never', str(file1), str(file2)]
    else:
        # Fallback to diff
        if color:
            cmd = ['diff', '-u', '--color=always', str(file1), str(file2)]
        else:
            cmd = ['diff', '-u', str(file1), str(file2)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout
    except Exception as e:
        return f"Error running diff: {e}"


def run_diff_on_content(content1: str, content2: str, label1: str = "AI", label2: str = "Ref", color: bool = True) -> str:
    """Run diff on string content."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.nix', delete=False) as f1:
        f1.write(content1)
        f1_path = f1.name

    with tempfile.NamedTemporaryFile(mode='w', suffix='.nix', delete=False) as f2:
        f2.write(content2)
        f2_path = f2.name

    try:
        result = run_difftastic(Path(f1_path), Path(f2_path), color=color)
    finally:
        os.unlink(f1_path)
        os.unlink(f2_path)

    return result


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    import re
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


class PackageReviewTUI:
    """Terminal UI for package review."""

    def __init__(self, session: ReviewSession):
        self.session = session
        self.current_view = "diff"  # "diff", "ai_file", "ref_file", "help"
        self.current_supplemental_index = 0
        self.scroll_offset = 0
        self.cached_diff = None
        self.status_message = ""

    def run(self, stdscr):
        """Main TUI loop."""
        curses.curs_set(0)  # Hide cursor
        stdscr.clear()

        # Initialize color pairs
        curses.start_color()
        curses.use_default_colors()

        # Define color pairs for diff output
        curses.init_pair(1, curses.COLOR_GREEN, -1)   # Additions
        curses.init_pair(2, curses.COLOR_RED, -1)     # Deletions
        curses.init_pair(3, curses.COLOR_CYAN, -1)    # Hunk headers
        curses.init_pair(4, curses.COLOR_YELLOW, -1)  # Modified lines

        while True:
            pkg = self.session.get_current_package()
            if not pkg:
                break

            stdscr.clear()
            height, width = stdscr.getmaxyx()

            # Draw header
            self._draw_header(stdscr, pkg, width)

            # Draw main content area
            content_start = 4
            content_height = height - content_start - 3  # Leave space for footer

            if self.current_view == "diff":
                self._draw_diff_view(stdscr, pkg, content_start, content_height, width)
            elif self.current_view == "help":
                self._draw_help_view(stdscr, content_start, content_height, width)
            elif self.current_view.startswith("supp_"):
                self._draw_supplemental_view(stdscr, pkg, content_start, content_height, width)

            # Draw footer
            self._draw_footer(stdscr, height - 2, width)

            stdscr.refresh()

            # Handle input
            try:
                key = stdscr.getch()
                action = self._handle_key(key, pkg)

                if action == "quit":
                    break
                elif action == "next":
                    if not self.session.next_package():
                        self.status_message = "Last package!"
                    else:
                        self._reset_view_state()
                elif action == "prev":
                    if not self.session.prev_package():
                        self.status_message = "First package!"
                    else:
                        self._reset_view_state()
            except KeyboardInterrupt:
                break

        return self.session

    def _reset_view_state(self):
        """Reset view state when changing packages."""
        self.current_view = "diff"
        self.scroll_offset = 0
        self.cached_diff = None
        self.current_supplemental_index = 0
        self.status_message = ""

    def _draw_header(self, stdscr, pkg: PackageReview, width: int):
        """Draw the header with package info and progress."""
        current, total, reviewed = self.session.get_progress()

        # Line 1: Package info
        header1 = f"Package: {pkg.package_name} (pname: {pkg.pname}, ID: {pkg.csv_id})"
        stdscr.addstr(0, 0, header1[:width-1], curses.A_BOLD)

        # Line 2: Progress and decision
        decision_str = f"Decision: {pkg.decision or 'NONE'}"
        progress_str = f"[{current}/{total}] Reviewed: {reviewed}"
        header2 = f"{decision_str}  |  {progress_str}"
        stdscr.addstr(1, 0, header2[:width-1])

        # Line 3: Status message
        if self.status_message:
            stdscr.addstr(2, 0, self.status_message[:width-1], curses.A_REVERSE)

        # Separator
        stdscr.addstr(3, 0, "─" * (width - 1))

    def _draw_diff_view(self, stdscr, pkg: PackageReview, start_y: int, height: int, width: int):
        """Draw the main diff view."""
        # Find main package files
        ai_file = find_main_package_file(pkg.ai_dir)
        ref_file = find_main_package_file(pkg.ref_dir)

        if not ai_file or not ref_file:
            msg = "Error: Could not find package files"
            if not ai_file:
                msg += f"\n  AI file not found in {pkg.ai_dir}"
            if not ref_file:
                msg += f"\n  Ref file not found in {pkg.ref_dir}"
            stdscr.addstr(start_y, 0, msg[:width-1])
            return

        # Generate diff if not cached (without color for curses)
        # Swap order: ref_file first, ai_file second, so AI additions show as green (+)
        if not self.cached_diff:
            self.cached_diff = run_difftastic(ref_file, ai_file, color=False)

        # Display diff with scrolling
        lines = self.cached_diff.split('\n')
        for i, line in enumerate(lines[self.scroll_offset:self.scroll_offset + height]):
            if start_y + i >= start_y + height:
                break
            try:
                # Apply basic diff coloring
                display_line = line[:width-1]
                attr = curses.A_NORMAL

                # Color diff lines
                if line.startswith('+'):
                    attr = curses.color_pair(1)  # Green for additions
                elif line.startswith('-'):
                    attr = curses.color_pair(2)  # Red for deletions
                elif line.startswith('@'):
                    attr = curses.color_pair(3)  # Cyan for hunk headers

                stdscr.addstr(start_y + i, 0, display_line, attr)
            except:
                pass  # Ignore curses errors for out-of-bounds writes

        # Show scroll indicator
        if len(lines) > height:
            scroll_info = f"[{self.scroll_offset}/{len(lines)-height}]"
            try:
                stdscr.addstr(start_y + height - 1, width - len(scroll_info) - 1, scroll_info, curses.A_REVERSE)
            except:
                pass

    def _draw_help_view(self, stdscr, start_y: int, height: int, width: int):
        """Draw the help screen."""
        help_text = [
            "KEYBINDINGS:",
            "",
            "  Navigation:",
            "    n, →      - Next package",
            "    p, ←      - Previous package",
            "    j, ↓      - Scroll down",
            "    k, ↑      - Scroll up",
            "    q         - Quit",
            "",
            "  Decisions:",
            "    y         - Mark as EQUIVALENT",
            "    n         - Mark as NOT EQUIVALENT",
            "    s         - Mark as SKIP",
            "    u         - Clear decision (UNMARK)",
            "",
            "  Views:",
            "    d         - Show diff (main view)",
            "    1-9       - View supplemental file #N",
            "    h, ?      - Show this help",
            "",
            "Press any key to return to diff view..."
        ]

        for i, line in enumerate(help_text):
            if i >= height:
                break
            stdscr.addstr(start_y + i, 2, line[:width-3])

    def _draw_supplemental_view(self, stdscr, pkg: PackageReview, start_y: int, height: int, width: int):
        """Draw supplemental file view."""
        supp_files_ai = get_supplemental_files(pkg.ai_dir)
        supp_files_ref = get_supplemental_files(pkg.ref_dir)

        # Get all unique supplemental files
        all_supp_names = set()
        if supp_files_ai:
            all_supp_names.update(f.name for f in supp_files_ai)
        if supp_files_ref:
            all_supp_names.update(f.name for f in supp_files_ref)

        all_supp_names = sorted(all_supp_names)

        if not all_supp_names:
            stdscr.addstr(start_y, 0, "No supplemental files found")
            return

        if self.current_supplemental_index >= len(all_supp_names):
            self.current_supplemental_index = 0

        filename = all_supp_names[self.current_supplemental_index]

        # Find files
        ai_supp = pkg.ai_dir / filename
        ref_supp = pkg.ref_dir / filename

        # Show header
        header = f"Supplemental file: {filename} ({self.current_supplemental_index + 1}/{len(all_supp_names)})"
        stdscr.addstr(start_y, 0, header[:width-1], curses.A_BOLD)
        start_y += 2
        height -= 2

        # Show diff or individual files
        if ai_supp.exists() and ref_supp.exists():
            # Swap order: ref first, ai second, so AI additions show as green (+)
            diff = run_difftastic(ref_supp, ai_supp, color=False)
            lines = diff.split('\n')
            for i, line in enumerate(lines[self.scroll_offset:self.scroll_offset + height]):
                if i >= height:
                    break
                try:
                    # Apply basic diff coloring
                    attr = curses.A_NORMAL
                    if line.startswith('+'):
                        attr = curses.color_pair(1)
                    elif line.startswith('-'):
                        attr = curses.color_pair(2)
                    elif line.startswith('@'):
                        attr = curses.color_pair(3)

                    stdscr.addstr(start_y + i, 0, line[:width-1], attr)
                except:
                    pass
        elif ai_supp.exists():
            stdscr.addstr(start_y, 0, f"File only in AI: {ai_supp}")
            with open(ai_supp) as f:
                lines = f.readlines()
                for i, line in enumerate(lines[self.scroll_offset:self.scroll_offset + height - 1]):
                    if i >= height - 1:
                        break
                    try:
                        stdscr.addstr(start_y + 1 + i, 2, line.rstrip()[:width-3])
                    except:
                        pass
        elif ref_supp.exists():
            stdscr.addstr(start_y, 0, f"File only in Reference: {ref_supp}")
            with open(ref_supp) as f:
                lines = f.readlines()
                for i, line in enumerate(lines[self.scroll_offset:self.scroll_offset + height - 1]):
                    if i >= height - 1:
                        break
                    try:
                        stdscr.addstr(start_y + 1 + i, 2, line.rstrip()[:width-3])
                    except:
                        pass

    def _draw_footer(self, stdscr, y: int, width: int):
        """Draw the footer with keybinding hints."""
        footer = "y:Equiv  n:NotEquiv  s:Skip  u:Unmark  |  →:Next  ←:Prev  ↑↓:Scroll  |  d:Diff  1-9:Supp  h:Help  q:Quit"
        try:
            stdscr.addstr(y, 0, "─" * (width - 1))
            stdscr.addstr(y + 1, 0, footer[:width-1], curses.A_REVERSE)
        except:
            pass

    def _handle_key(self, key: int, pkg: PackageReview) -> Optional[str]:
        """Handle keyboard input. Returns action string or None."""
        self.status_message = ""  # Clear previous status

        # Navigation
        if key in (ord('q'), ord('Q')):
            return "quit"
        elif key in (ord('n'), curses.KEY_RIGHT):
            return "next"
        elif key in (ord('p'), curses.KEY_LEFT):
            return "prev"

        # Scrolling
        elif key in (ord('j'), curses.KEY_DOWN):
            self.scroll_offset += 1
        elif key in (ord('k'), curses.KEY_UP):
            self.scroll_offset = max(0, self.scroll_offset - 1)

        # Decisions
        elif key == ord('y'):
            pkg.decision = "equivalent"
            self.session.save_decision(pkg)
            self.status_message = "Marked as EQUIVALENT"
        elif key == ord('N'):
            pkg.decision = "not_equivalent"
            self.session.save_decision(pkg)
            self.status_message = "Marked as NOT EQUIVALENT"
        elif key == ord('s'):
            pkg.decision = "skip"
            self.session.save_decision(pkg)
            self.status_message = "Marked as SKIP"
        elif key == ord('u'):
            pkg.decision = None
            if pkg.csv_id in self.session.decisions:
                del self.session.decisions[pkg.csv_id]
            self.session._write_csv()
            self.status_message = "Decision cleared"

        # Views
        elif key == ord('d'):
            self.current_view = "diff"
            self.scroll_offset = 0
        elif key in (ord('h'), ord('?')):
            self.current_view = "help"
            self.scroll_offset = 0
        elif ord('1') <= key <= ord('9'):
            supp_index = key - ord('1')
            self.current_supplemental_index = supp_index
            self.current_view = f"supp_{supp_index}"
            self.scroll_offset = 0

        return None


def load_packages_from_csv(csv_file: Path, ai_base: Path, ref_base: Path, id_range: str = "1-30") -> List[PackageReview]:
    """
    Load packages from CSV and match with directories.

    Args:
        csv_file: Path to the CSV file with package data
        ai_base: Base directory for AI-generated packages
        ref_base: Base directory for reference packages
        id_range: Range of IDs to process (e.g., "1-30", "1-10,15,20-25")

    Returns:
        List of PackageReview objects
    """
    packages = []

    # Parse ID range
    selected_ids = parse_id_range(id_range)

    # Read CSV to get ID to package mapping
    if not csv_file.exists():
        print(f"Error: CSV file not found: {csv_file}", file=sys.stderr)
        return []

    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                csv_id = int(row['random_order'])
            except (ValueError, KeyError):
                continue

            # Check if in selected range
            if csv_id not in selected_ids:
                continue

            package_name = row['package_name']
            pname = row['pname']

            # AI directory format: <package_name>-<pname>
            ai_dir_name = f"{package_name}-{pname}"
            ai_dir = ai_base / ai_dir_name

            # Reference directory format: <id>-<package_name>-<pname>
            ref_dir_name = f"{csv_id}-{package_name}-{pname}"
            ref_dir = ref_base / ref_dir_name

            # Find the actual package subdirectory
            ai_pkg_dir = ai_dir / pname
            ref_pkg_dir = ref_dir / pname

            if not ai_pkg_dir.exists():
                print(f"Warning: AI package directory not found: {ai_pkg_dir}", file=sys.stderr)
                continue

            if not ref_pkg_dir.exists():
                print(f"Warning: Reference package directory not found: {ref_pkg_dir}", file=sys.stderr)
                continue

            packages.append(PackageReview(
                csv_id=csv_id,
                package_name=package_name,
                pname=pname,
                ai_dir=ai_pkg_dir,
                ref_dir=ref_pkg_dir
            ))

    return packages


def parse_id_range(range_str: str) -> set:
    """
    Parse ID range string into set of IDs.
    Supports: "1-30", "1,2,3", "1-10,15,20-25"
    """
    ids = set()

    for part in range_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            ids.update(range(int(start), int(end) + 1))
        else:
            ids.add(int(part))

    return ids


def main():
    if len(sys.argv) < 4:
        print("Usage: python3 review_packages_tui.py <csv_file> <ai_output_dir> <reference_dir> [id_range] [output_csv]")
        print()
        print("Arguments:")
        print("  csv_file        - CSV file with package data (e.g., single_fetcher_2025-08-01_2025-11-20_validated.csv)")
        print("  ai_output_dir   - Directory with AI-generated packages (e.g., vibenix_results2/refinement)")
        print("  reference_dir   - Directory with reference packages (from extract_reference_files.py)")
        print("  id_range        - Optional: Range of package IDs to review (default: 1-30)")
        print("                    Examples: '1-30', '1-10,15,20-25', '5'")
        print("  output_csv      - Optional: Output CSV file (default: review_results.csv)")
        print()
        print("Example:")
        print("  python3 review_packages_tui.py single_fetcher_2025-08-01_2025-11-20_validated.csv \\")
        print("                                  ~/git/vibenix_results2/refinement ./reference_files 1-30")
        sys.exit(1)

    csv_file = Path(sys.argv[1])
    ai_base = Path(sys.argv[2])
    ref_base = Path(sys.argv[3])
    id_range = sys.argv[4] if len(sys.argv) > 4 else "1-30"
    output_csv = Path(sys.argv[5]) if len(sys.argv) > 5 else Path("review_results.csv")

    # Load packages
    print(f"Loading packages from CSV: {csv_file}", file=sys.stderr)
    print(f"AI output: {ai_base}", file=sys.stderr)
    print(f"Reference: {ref_base}", file=sys.stderr)
    print(f"ID range: {id_range}", file=sys.stderr)

    packages = load_packages_from_csv(csv_file, ai_base, ref_base, id_range)

    if not packages:
        print("Error: No packages found to review", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(packages)} packages to review", file=sys.stderr)

    # Create session
    session = ReviewSession(packages=packages, output_csv=output_csv)
    session.load_existing_decisions()

    print(f"Loaded {len(session.decisions)} existing decisions", file=sys.stderr)
    print("Starting TUI... (press 'h' for help)", file=sys.stderr)

    # Run TUI
    tui = PackageReviewTUI(session)

    try:
        curses.wrapper(tui.run)
    except KeyboardInterrupt:
        print("\nReview interrupted by user", file=sys.stderr)

    # Print summary
    print(f"\nReview session complete!", file=sys.stderr)
    print(f"Reviewed: {len(session.decisions)}/{len(packages)} packages", file=sys.stderr)
    print(f"Results saved to: {output_csv}", file=sys.stderr)


if __name__ == "__main__":
    main()
