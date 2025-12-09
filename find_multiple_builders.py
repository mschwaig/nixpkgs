#!/usr/bin/env python3
"""
Script to identify packages in the CSV that use more than one builder function.
Checks out the file at the specific commit and analyzes it.
"""

import csv
import sys
import subprocess
from pathlib import Path
from typing import Set, Dict, List, Tuple
from find_builder_functions import find_builder_functions
import tempfile
import shutil

def get_file_at_commit(repo_path: Path, commit: str, file_path: str) -> str | None:
    """Get the content of a file at a specific commit."""
    try:
        result = subprocess.run(
            ['git', 'show', f'{commit}:{file_path}'],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return result.stdout
        else:
            return None
    except Exception as e:
        print(f"Error getting file {file_path} at {commit}: {e}", file=sys.stderr)
        return None

def find_nix_file_for_package(repo_path: Path, commit: str, package_name: str, pname: str) -> str | None:
    """Try to find the .nix file for a package at a specific commit."""
    # Common patterns where package files might be
    common_paths = [
        f'pkgs/by-name/{pname[:2]}/{pname}/package.nix',
        f'pkgs/development/python-modules/{pname}/default.nix',
        f'pkgs/development/python-modules/{package_name}/default.nix',
        f'pkgs/applications/{pname}/default.nix',
        f'pkgs/tools/{pname}/default.nix',
    ]

    for path in common_paths:
        content = get_file_at_commit(repo_path, commit, path)
        if content:
            return path

    # Try using git ls-tree to find files
    try:
        result = subprocess.run(
            ['git', 'ls-tree', '-r', '--name-only', commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            files = result.stdout.strip().split('\n')
            # Look for files containing pname or package_name
            candidates = [
                f for f in files
                if (pname in f or package_name in f) and f.endswith('.nix')
            ]
            if candidates:
                # Try the most likely candidate (shortest path in pkgs/)
                pkgs_candidates = [c for c in candidates if c.startswith('pkgs/')]
                if pkgs_candidates:
                    return sorted(pkgs_candidates, key=len)[0]
                return candidates[0]
    except Exception as e:
        print(f"Error searching for {package_name}: {e}", file=sys.stderr)

    return None

def strip_namespace(builder_name: str) -> str:
    """Strip namespace from builder function name (e.g., 'rustPlatform.buildRustPackage' -> 'buildRustPackage')."""
    if '.' in builder_name:
        return builder_name.split('.')[-1]
    return builder_name

def analyze_csv(csv_path: Path, repo_path: Path, min_id: int = None, max_id: int = None) -> Tuple[List[Dict], Dict[str, int], int, int]:
    """Analyze the CSV file and find packages with multiple builders.

    Args:
        csv_path: Path to the CSV file
        repo_path: Path to the repository
        min_id: Minimum random_order value to process (inclusive)
        max_id: Maximum random_order value to process (inclusive)

    Returns:
        - List of packages with multiple builders
        - Dictionary of single builder usage counts (excludes multi-builder packages)
        - Total packages analyzed
        - Total packages where we couldn't find the nix file
    """
    multi_builder_packages = []
    single_builder_counts = {}
    total_analyzed = 0
    not_found = 0

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader):
            # Filter by random_order if specified
            if 'random_order' in row:
                try:
                    random_order = int(row['random_order'])
                    if min_id is not None and random_order < min_id:
                        continue
                    if max_id is not None and random_order > max_id:
                        continue
                except ValueError:
                    pass  # Skip if random_order is not a valid integer
            commit = row['commit_hash']
            package_name = row['package_name']
            pname = row['pname']

            if i % 10 == 0:
                print(f"Processing row {i}: {package_name}", file=sys.stderr)

            # Find the .nix file
            nix_file = find_nix_file_for_package(repo_path, commit, package_name, pname)
            if not nix_file:
                print(f"  Could not find .nix file for {package_name} at {commit}", file=sys.stderr)
                not_found += 1
                continue

            # Get the file content
            content = get_file_at_commit(repo_path, commit, nix_file)
            if not content:
                print(f"  Could not get content for {nix_file} at {commit}", file=sys.stderr)
                not_found += 1
                continue

            # Write to a temp file and analyze
            with tempfile.NamedTemporaryFile(mode='w', suffix='.nix', delete=False) as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)

            try:
                builders = find_builder_functions(tmp_path)

                # Strip namespaces from all builder names
                builders_no_namespace = {strip_namespace(b) for b in builders}

                total_analyzed += 1

                if len(builders_no_namespace) > 1:
                    # Multi-builder package
                    multi_builder_packages.append({
                        'package_name': package_name,
                        'pname': pname,
                        'commit': commit,
                        'file': nix_file,
                        'builders': sorted(list(builders_no_namespace)),
                        'num_builders': len(builders_no_namespace)
                    })
                    print(f"  Found {len(builders_no_namespace)} builders in {package_name}: {', '.join(sorted(builders_no_namespace))}", file=sys.stderr)
                elif len(builders_no_namespace) == 1:
                    # Single builder package - count it
                    builder = list(builders_no_namespace)[0]
                    single_builder_counts[builder] = single_builder_counts.get(builder, 0) + 1
                # If no builders found, we just don't count it
            finally:
                tmp_path.unlink()

    return multi_builder_packages, single_builder_counts, total_analyzed, not_found

def main():
    if len(sys.argv) < 2:
        print("Usage: find_multiple_builders.py <csv_file> [repo_path] [--range MIN-MAX]")
        print("Example: find_multiple_builders.py data.csv . --range 1-30")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    repo_path = Path.cwd()
    min_id = None
    max_id = None

    # Parse arguments
    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == '--range':
            if i + 1 < len(sys.argv):
                range_str = sys.argv[i + 1]
                try:
                    parts = range_str.split('-')
                    if len(parts) == 2:
                        min_id = int(parts[0])
                        max_id = int(parts[1])
                except ValueError:
                    print(f"Error: Invalid range format '{range_str}'. Use MIN-MAX (e.g., 1-30)", file=sys.stderr)
                    sys.exit(1)
                i += 2
            else:
                print("Error: --range requires an argument (e.g., 1-30)", file=sys.stderr)
                sys.exit(1)
        else:
            # Assume it's the repo path
            repo_path = Path(arg)
            i += 1

    print(f"Analyzing CSV: {csv_path}", file=sys.stderr)
    print(f"Repository: {repo_path}", file=sys.stderr)
    if min_id is not None or max_id is not None:
        print(f"Range filter: {min_id if min_id is not None else 'start'} to {max_id if max_id is not None else 'end'}", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    multi_builder_packages, single_builder_counts, total_analyzed, not_found = analyze_csv(csv_path, repo_path, min_id, max_id)

    print("\n" + "=" * 80, file=sys.stderr)
    print("RESULTS", file=sys.stderr)
    print("=" * 80, file=sys.stderr)
    print(f"Total packages analyzed: {total_analyzed}", file=sys.stderr)
    print(f"Packages not found: {not_found}", file=sys.stderr)
    print(f"Multi-builder packages: {len(multi_builder_packages)}", file=sys.stderr)

    # Print multi-builder packages as CSV to stdout
    if multi_builder_packages:
        fieldnames = ['package_name', 'pname', 'commit', 'file', 'num_builders', 'builders']
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()

        for result in sorted(multi_builder_packages, key=lambda x: (-x['num_builders'], x['package_name'])):
            # Convert builders list to string
            result_copy = result.copy()
            result_copy['builders'] = ', '.join(result['builders'])
            writer.writerow(result_copy)

    # Print statistics
    print("\n" + "=" * 80, file=sys.stderr)
    print("BUILDER DISTRIBUTION (single-builder packages only)", file=sys.stderr)
    print("=" * 80, file=sys.stderr)

    total_single = sum(single_builder_counts.values())
    total_with_multi = total_single + len(multi_builder_packages)

    print(f"\nCategory breakdown (adds up to 100%):", file=sys.stderr)
    print(f"  Multi-builder: {len(multi_builder_packages)} ({100.0 * len(multi_builder_packages) / total_with_multi:.2f}%)", file=sys.stderr)

    for builder, count in sorted(single_builder_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / total_with_multi
        print(f"  {builder}: {count} ({pct:.2f}%)", file=sys.stderr)

    print(f"\nTotal: {total_with_multi} (100.00%)", file=sys.stderr)

if __name__ == "__main__":
    main()
