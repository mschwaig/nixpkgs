#!/usr/bin/env python3
"""
Validate fetchers from CSV by evaluating them with Nix.
This script tests whether fetchers can be successfully evaluated (not built).
"""

import csv
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict
import sys

def read_fetchers_csv(csv_path: str) -> List[Dict]:
    """Read fetchers from CSV file."""
    fetchers = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            fetchers.append(row)
    return fetchers

def evaluate_fetcher(fetcher_content: str, version: str, pname: str) -> Tuple[bool, str]:
    """
    Evaluate a fetcher expression using nix instantiate (fast, no actual evaluation).

    Returns (success, error_message).
    """
    wrapped_expr = f'rec {{ pname = "{pname}"; finalAttrs.pname = pname; version = "{version}"; finalAttrs.version = version; src = {fetcher_content}; }}'

    nix_expr = f"""with import <nixpkgs> {{}}; ({wrapped_expr}).src"""

    cmd = [
        'nix-instantiate',
        '--eval',
        '--strict',
        '--json',
        '--expr',
        nix_expr
    ]

    try:
        result = subprocess.run(
            cmd,
            cwd='/home/mschwaig/nixpkgs',
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Timeout (>10s)"
    except Exception as e:
        return False, f"Exception: {str(e)}"

def fetch_source(fetcher_content: str, version: str, pname: str) -> Tuple[bool, str, str]:
    """
    Fetch the actual source code using the fetcher expression.

    Args:
        fetcher_content: The fetcher expression (e.g., fetchFromGitHub { ... })
        version: The version string
        pname: The package name

    Returns:
        (success, source_path, error_message)
    """
    wrapped_expr = f'rec {{ pname = "{pname}"; finalAttrs.pname = pname; version = "{version}"; finalAttrs.version = version; src = {fetcher_content}; }}'
    nix_expr = f"with import <nixpkgs> {{}}; ({wrapped_expr}).src"

    try:
        result = subprocess.run(
            ['nix-build', '--no-out-link', '--expr', nix_expr],
            cwd='/home/mschwaig/nixpkgs',
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode != 0:
            return False, "", f"Source fetch failed: {result.stderr.strip()}"

        source_path = result.stdout.strip()
        return True, source_path, ""
    except subprocess.TimeoutExpired:
        return False, "", "Source fetch timeout (>300s)"
    except Exception as e:
        return False, "", f"Exception: {str(e)}"


def check_for_nix_files(source_path: str) -> bool:
    """
    Check if a source directory contains any .nix files.

    Args:
        source_path: Path to the source directory

    Returns:
        True if .nix files are found, False otherwise
    """
    import os

    try:
        for root, dirs, files in os.walk(source_path):
            for file in files:
                if file.endswith('.nix'):
                    return True
        return False
    except Exception as e:
        print(f"Warning: Could not scan {source_path}: {e}", file=sys.stderr)
        return False


def categorize_error(error_msg: str) -> str:
    """Categorize error messages into common failure types."""
    error_lower = error_msg.lower()

    if 'contains_nix_code' in error_lower:
        return 'contains_nix_code'
    elif 'finalattr' in error_lower and 'undefined' in error_lower:
        return 'finalAttr typo (should be finalAttrs)'
    elif 'finalattrs' in error_lower and 'undefined' in error_lower:
        return 'finalAttrs not defined'
    elif 'version' in error_lower and 'undefined' in error_lower:
        return 'version undefined'
    elif 'pname' in error_lower and 'undefined' in error_lower:
        return 'pname undefined'
    elif 'timeout' in error_lower:
        return 'Timeout'
    elif 'syntax error' in error_lower:
        return 'Syntax error'
    elif 'hash mismatch' in error_lower:
        return 'Hash mismatch'
    elif 'attribute' in error_lower and 'missing' in error_lower:
        return 'Missing attribute'
    else:
        return 'Other error'

def main():
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        csv_path = '/home/mschwaig/nixpkgs/single_fetcher_2025-08-01_2025-11-20.csv'

    print(f"Reading CSV file: {csv_path}")
    fetchers = read_fetchers_csv(csv_path)
    total = len(fetchers)
    print(f"Found {total} fetchers to validate\n")

    success_count = 0
    failure_count = 0
    failures = []
    successes = []  # Track successful fetchers for filtered CSV
    error_categories = defaultdict(int)

    print("Validating fetchers (this may take a while)...")
    print("=" * 80)

    for i, row in enumerate(fetchers, 1):
        package_name = row['package_name']
        pname = row['pname']
        version = row['version']
        fetcher = row['fetcher']

        success, error = evaluate_fetcher(fetcher, version, pname)

        if success:
            # Evaluation succeeded, now fetch source and check for .nix files
            print(f"  [{i}/{total}] Evaluating {package_name}... ✓ ", end='', flush=True)

            fetch_success, source_path, fetch_error = fetch_source(fetcher, version, pname)

            if fetch_success:
                # Check for .nix files in the source
                has_nix_files = check_for_nix_files(source_path)

                if has_nix_files:
                    # Treat as a failure with specific category
                    failure_count += 1
                    category = 'contains_nix_code'
                    error_categories[category] += 1
                    failures.append({
                        'package_name': package_name,
                        'pname': pname,
                        'version': version,
                        'fetcher': fetcher,
                        'error': 'contains_nix_code',
                        'category': category
                    })
                    print(f"Fetching... ✓ Scanning... ✗ {category}")
                else:
                    # All checks passed
                    success_count += 1
                    successes.append(row)  # Keep the original row for filtered CSV
                    print(f"Fetching... ✓ Scanning... ✓")
            else:
                # Source fetch failed - treat as a failure
                failure_count += 1
                category = categorize_error(fetch_error)
                error_categories[category] += 1
                failures.append({
                    'package_name': package_name,
                    'pname': pname,
                    'version': version,
                    'fetcher': fetcher,
                    'error': fetch_error,
                    'category': category
                })
                print(f"Fetching... ✗ {category}")
        else:
            failure_count += 1
            category = categorize_error(error)
            error_categories[category] += 1
            failures.append({
                'package_name': package_name,
                'pname': pname,
                'version': version,
                'fetcher': fetcher,
                'error': error,
                'category': category
            })
            print(f"  [{i}/{total}] ✗ {package_name}: {category}")

    # Print summary
    print("\n" + "=" * 80)
    print("VALIDATION SUMMARY")
    print("=" * 80)
    print(f"Total fetchers:     {total}")
    print(f"Successful:         {success_count} ({100*success_count/total:.1f}%)")
    print(f"Failed:             {failure_count} ({100*failure_count/total:.1f}%)")
    print()

    if error_categories:
        print("ERROR CATEGORIES:")
        print("-" * 80)
        for category, count in sorted(error_categories.items(), key=lambda x: -x[1]):
            print(f"  {category:40} {count:5} ({100*count/failure_count:.1f}%)")
        print()

    # Write detailed failure report
    if failures:
        report_path = '/home/mschwaig/nixpkgs/fetcher_validation_failures.json'
        with open(report_path, 'w') as f:
            json.dump(failures, f, indent=2)
        print(f"Detailed failure report written to: {report_path}")

        # Also write a CSV summary
        csv_report_path = '/home/mschwaig/nixpkgs/fetcher_validation_failures.csv'
        with open(csv_report_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['package_name', 'pname', 'version', 'category', 'error'], lineterminator='\n')
            writer.writeheader()
            for failure in failures:
                writer.writerow({
                    'package_name': failure['package_name'],
                    'pname': failure['pname'],
                    'version': failure['version'],
                    'category': failure['category'],
                    'error': failure['error'][:200]  # Truncate long errors
                })
        print(f"CSV failure report written to: {csv_report_path}")

    # Write filtered CSV with only successful fetchers
    if successes:
        # Determine output path based on input
        input_path = Path(csv_path)
        filtered_csv_path = input_path.parent / f"{input_path.stem}_validated{input_path.suffix}"

        with open(filtered_csv_path, 'w', newline='', encoding='utf-8') as f:
            # Use the same fieldnames as the input CSV
            fieldnames = list(successes[0].keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
            writer.writeheader()
            writer.writerows(successes)

        print(f"Filtered CSV (validated fetchers only) written to: {filtered_csv_path}")
        print(f"  Contains {len(successes)} validated fetchers")

    # Write exclusions CSV (failures with reasons)
    if failures:
        input_path = Path(csv_path)
        exclusions_csv_path = input_path.parent / f"{input_path.stem}_exclusions{input_path.suffix}"

        with open(exclusions_csv_path, 'w', newline='', encoding='utf-8') as f:
            # Include all original fields plus exclusion_reason
            if fetchers:
                fieldnames = list(fetchers[0].keys()) + ['exclusion_reason']
                writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n')
                writer.writeheader()

                for failure in failures:
                    # Find the original row data
                    original_row = None
                    for row in fetchers:
                        if row['package_name'] == failure['package_name']:
                            original_row = row
                            break

                    if original_row:
                        row_data = original_row.copy()
                        row_data['exclusion_reason'] = failure['category']
                        writer.writerow(row_data)

        print(f"Exclusions CSV (failed fetchers with reasons) written to: {exclusions_csv_path}")
        print(f"  Contains {len(failures)} excluded fetchers")

    print()
    print("=" * 80)

    # Show all failures with complete fetcher code
    if failures:
        print("\nALL FAILURES WITH COMPLETE FETCHER CODE:")
        print("=" * 80)
        for i, failure in enumerate(failures, 1):
            print(f"\n[{i}/{len(failures)}] {failure['package_name']}")
            print(f"Category: {failure['category']}")
            print(f"Pname: {failure['pname']}")
            print(f"Version: {failure['version']}")
            print(f"\nFetcher code:")
            print("-" * 80)
            print(failure['fetcher'])
            print("-" * 80)
            print(f"\nError (first 300 chars):")
            print(failure['error'][:300])
            if i < len(failures):
                print("\n" + "=" * 80)

if __name__ == '__main__':
    main()
