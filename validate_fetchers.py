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
    Mimics the EXACT structure from run.py:242-244:
    rec { version = "..."; finalAttrs.version = version; src = <fetcher>; }

    NOTE: pname is NOT set in this context, only version!
    Returns (success, error_message).
    """
    # Match the exact expression from run.py:242-244
    # version_attrs = f'version = "{version}"; finalAttrs.version = version;' if version else ''
    # wrapped_expr = f"rec {{ {version_attrs} src = {content}; }}"

    version_attrs = f'version = "{version}"; finalAttrs.version = version;' if version else ''
    wrapped_expr = f"rec {{ {version_attrs} src = {fetcher_content}; }}"

    # Use the same pattern as run.py but with nix-instantiate for speed
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

def categorize_error(error_msg: str) -> str:
    """Categorize error messages into common failure types."""
    error_lower = error_msg.lower()

    if 'finalattr' in error_lower and 'undefined' in error_lower:
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
    csv_path = '/home/mschwaig/nixpkgs/single_fetcher_2025-08-01_2025-11-20.csv'

    print("Reading CSV file...")
    fetchers = read_fetchers_csv(csv_path)
    total = len(fetchers)
    print(f"Found {total} fetchers to validate\n")

    success_count = 0
    failure_count = 0
    failures = []
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
            success_count += 1
            print(f"  [{i}/{total}] ✓ {package_name}")
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
        with open(csv_report_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['package_name', 'pname', 'version', 'category', 'error'])
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
