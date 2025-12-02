#!/usr/bin/env python3
"""
Extract fetcher functions from new packages.
Reads new_packages CSV and extracts all fetch* function calls from each package.
"""

import subprocess
import re
import csv
import sys
from dataclasses import dataclass, field
from typing import List, Dict

# Indirect fetchers - fetch locked dependencies without any parameters about the origin like a url
INDIRECT_FETCHERS = [
    'fetchCargoVendor',
    'fetchNpmDeps',
    'fetchDeps',
    'fetchYarnDeps',
]

@dataclass
class PackageInfo:
    commit_hash: str
    date: str
    package_name: str
    subject: str
    test_base_commit: str
    build_time: float
    package_file: str = None
    fetchers: List[Dict[str, str]] = field(default_factory=list)  # List of {type, content}
    raw_fetcher_count: int = 0  # Total count of all fetchers
    direct_fetcher_count: int = 0  # Count excluding indirect fetchers
    pname: str = None
    version: str = None
    exclusion_reasons: set = field(default_factory=set)


def get_package_file_from_commit(commit_hash: str) -> str:
    """Get the package.nix or default.nix file path from a commit"""
    cmd = ['git', 'diff-tree', '--no-commit-id', '--name-only', '--diff-filter=A', '-r', commit_hash]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    files = result.stdout.strip().split('\n')

    # Find package.nix or default.nix files in pkgs/
    for f in files:
        if f.startswith('pkgs/') and (f.endswith('/package.nix') or f.endswith('/default.nix')):
            return f
    return None


def get_file_content(commit_hash: str, filepath: str) -> str:
    """Get file content from a specific commit"""
    cmd = ['git', 'show', f'{commit_hash}:{filepath}']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def extract_pname_version(content: str) -> tuple[str, str]:
    """
    Extract pname and version from package content.
    Returns (pname, version) tuple, with None for values not found.
    """
    pname = None
    version = None

    # Pattern for pname = "value"; or pname = ''value'';
    pname_match = re.search(r'pname\s*=\s*["\']([^"\']+)["\']', content)
    if pname_match:
        pname = pname_match.group(1)

    # Pattern for version = "value"; or version = ''value'';
    version_match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    if version_match:
        version = version_match.group(1)

    return pname, version


def extract_fetchers(content: str) -> List[Dict[str, str]]:
    """
    Extract all fetch* function calls from package content.
    Uses a generic regex to match any function starting with 'fetch' followed by
    alphanumeric characters (e.g., fetchFromGitHub, fetchPypi, fetchpatch, etc.)

    Returns list of dicts with 'type' and 'content' keys.
    """
    fetchers = []

    # Pattern to match any fetch* function call with its arguments
    # Matches: fetch[alphanumeric]+ { ... } or fetch[alphanumeric]+ rec { ... }
    # \w+ matches one or more word characters (letters, digits, underscore)
    pattern = r'(fetch\w+)\s+(?:rec\s+)?\{'

    # Find all fetch function calls
    matches = re.finditer(pattern, content)

    for match in matches:
        fetcher_type = match.group(1)
        start_pos = match.start()

        # Find the matching closing brace
        # Count braces to handle nesting
        brace_count = 0
        in_string = False
        escape_next = False
        i = match.end() - 1  # Start from the opening brace

        for j, char in enumerate(content[i:], start=i):
            if escape_next:
                escape_next = False
                continue

            if char == '\\':
                escape_next = True
                continue

            if char == '"' and not in_string:
                in_string = True
            elif char == '"' and in_string:
                in_string = False

            if not in_string:
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        # Found the matching closing brace
                        end_pos = j + 1
                        fetcher_content = content[start_pos:end_pos]
                        fetchers.append({
                            'type': fetcher_type,
                            'content': fetcher_content
                        })
                        break

    return fetchers


def analyze_package(pkg: PackageInfo) -> None:
    """Extract fetcher information for a package"""
    # Get package file path
    pkg.package_file = get_package_file_from_commit(pkg.commit_hash)
    if not pkg.package_file:
        raise Exception(f"No package file found for {pkg.package_name} ({pkg.commit_hash})")

    # Get file content
    content = get_file_content(pkg.commit_hash, pkg.package_file)

    # Extract pname and version
    pkg.pname, pkg.version = extract_pname_version(content)

    # Check for missing pname or version
    if pkg.pname is None:
        pkg.exclusion_reasons.add('pname_missing')
    if pkg.version is None:
        pkg.exclusion_reasons.add('version_missing')

    # Extract fetchers
    pkg.fetchers = extract_fetchers(content)
    pkg.raw_fetcher_count = len(pkg.fetchers)

    # Calculate direct fetcher count (excluding indirect fetchers)
    direct_fetchers = [f for f in pkg.fetchers if f['type'] not in INDIRECT_FETCHERS]
    pkg.direct_fetcher_count = len(direct_fetchers)


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 extract_fetchers.py <new_packages.csv>")
        print("Example: python3 extract_fetchers.py new_packages_2025-08-01_2025-12-31.csv")
        sys.exit(1)

    input_csv = sys.argv[1]

    # Derive output filenames from input
    base_name = input_csv.replace('new_packages_', '').replace('.csv', '')
    fetchers_csv = f'fetchers_{base_name}.csv'
    single_fetcher_csv = f'single_fetcher_{base_name}.csv'
    multiple_fetchers_csv = f'multiple_fetchers_{base_name}.csv'

    # Read input CSV
    packages = []
    print(f"Reading {input_csv}...", file=sys.stderr)
    with open(input_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pkg = PackageInfo(
                commit_hash=row['commit_hash'],
                date=row['date'],
                package_name=row['packages'],
                subject=row['subject'],
                test_base_commit=row['test_base_commit'],
                build_time=float(row['build_time']) if row['build_time'] else 0.0
            )
            packages.append(pkg)

    print(f"Found {len(packages)} packages", file=sys.stderr)

    # Analyze each package
    print("Extracting fetchers...", file=sys.stderr)
    for i, pkg in enumerate(packages, 1):
        print(f"  [{i}/{len(packages)}] {pkg.package_name}...", file=sys.stderr)
        analyze_package(pkg)

    # Write results
    print(f"\nWriting results to {fetchers_csv}...", file=sys.stderr)
    with open(fetchers_csv, 'w', newline='') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['commit_hash', 'package_name', 'raw_fetcher_count', 'direct_fetcher_count', 'fetcher_types', 'nixpkgs_target_bump'])

        for pkg in packages:
            fetcher_types = ','.join([f['type'] for f in pkg.fetchers])
            writer.writerow([
                pkg.commit_hash,
                pkg.package_name,
                pkg.raw_fetcher_count,
                pkg.direct_fetcher_count,
                fetcher_types,
                pkg.test_base_commit
            ])

    # Filter packages with exclusion reasons
    excluded_pkgs = [pkg for pkg in packages if pkg.exclusion_reasons]
    included_pkgs = [pkg for pkg in packages if not pkg.exclusion_reasons]

    # Write exclusions file
    if excluded_pkgs:
        exclusions_csv = f'fetcher_exclusions_{base_name}.csv'
        print(f"\nWriting {len(excluded_pkgs)} excluded packages to {exclusions_csv}...", file=sys.stderr)
        with open(exclusions_csv, 'w', newline='') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(['commit_hash', 'exclusion_reasons', 'nixpkgs_target_bump'])

            for pkg in excluded_pkgs:
                writer.writerow([
                    pkg.commit_hash,
                    ','.join(sorted(pkg.exclusion_reasons)),
                    pkg.test_base_commit
                ])

    # Filter and write packages with single direct fetcher (only from included packages)
    single_fetcher_pkgs = [pkg for pkg in included_pkgs if pkg.direct_fetcher_count == 1]
    print(f"\nWriting {len(single_fetcher_pkgs)} packages with single fetcher to {single_fetcher_csv}...", file=sys.stderr)

    with open(single_fetcher_csv, 'w', newline='') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['commit_hash', 'package_name', 'pname', 'version', 'fetcher', 'nixpkgs_target_bump'])

        for pkg in single_fetcher_pkgs:
            fetcher = pkg.fetchers[0]  # Only one fetcher
            writer.writerow([
                pkg.commit_hash,
                pkg.package_name,
                pkg.pname,
                pkg.version,
                fetcher['content'],
                pkg.test_base_commit
            ])

    # Filter and write packages with multiple direct fetchers (only from included packages)
    multiple_fetchers = [pkg for pkg in included_pkgs if pkg.direct_fetcher_count > 1]
    print(f"Writing {len(multiple_fetchers)} packages with multiple fetchers to {multiple_fetchers_csv}...", file=sys.stderr)

    with open(multiple_fetchers_csv, 'w', newline='') as f:
        writer = csv.writer(f, lineterminator='\n')
        writer.writerow(['commit_hash', 'package_name', 'raw_fetcher_count', 'direct_fetcher_count', 'fetcher_types', 'nixpkgs_target_bump'])

        for pkg in multiple_fetchers:
            fetcher_types = ','.join([f['type'] for f in pkg.fetchers])
            writer.writerow([
                pkg.commit_hash,
                pkg.package_name,
                pkg.raw_fetcher_count,
                pkg.direct_fetcher_count,
                fetcher_types,
                pkg.test_base_commit
            ])

    # Print summary
    print(f"\n{'='*80}", file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(f"Total packages: {len(packages)}", file=sys.stderr)
    print(f"Excluded packages: {len(excluded_pkgs)}", file=sys.stderr)
    if excluded_pkgs:
        # Show exclusion reason breakdown
        exclusion_reason_counts = {}
        for pkg in excluded_pkgs:
            for reason in pkg.exclusion_reasons:
                exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1
        print(f"  Exclusion reasons:", file=sys.stderr)
        for reason, count in sorted(exclusion_reason_counts.items()):
            print(f"    - {reason}: {count}", file=sys.stderr)
    print(f"Included packages: {len(included_pkgs)}", file=sys.stderr)
    print(f"  - with 0 direct fetchers: {len([p for p in included_pkgs if p.direct_fetcher_count == 0])}", file=sys.stderr)
    print(f"  - with 1 direct fetcher: {len([p for p in included_pkgs if p.direct_fetcher_count == 1])}", file=sys.stderr)
    print(f"  - with >1 direct fetchers: {len([p for p in included_pkgs if p.direct_fetcher_count > 1])}", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)

    # Show fetcher type distribution (only for included packages)
    all_fetcher_counts = {}
    single_fetcher_counts = {}
    multiple_fetcher_counts = {}

    for pkg in included_pkgs:
        is_single = pkg.direct_fetcher_count == 1
        for fetcher in pkg.fetchers:
            fetcher_type = fetcher['type']
            all_fetcher_counts[fetcher_type] = all_fetcher_counts.get(fetcher_type, 0) + 1

            if is_single:
                single_fetcher_counts[fetcher_type] = single_fetcher_counts.get(fetcher_type, 0) + 1
            else:
                multiple_fetcher_counts[fetcher_type] = multiple_fetcher_counts.get(fetcher_type, 0) + 1

    print("\nFetcher type distribution (all packages):", file=sys.stderr)
    for fetcher_type, count in sorted(all_fetcher_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {fetcher_type}: {count}", file=sys.stderr)

    print("\nFetcher type distribution (single-fetcher packages only):", file=sys.stderr)
    for fetcher_type, count in sorted(single_fetcher_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {fetcher_type}: {count}", file=sys.stderr)

    print("\nFetcher type distribution (multi-fetcher packages only):", file=sys.stderr)
    if multiple_fetcher_counts:
        for fetcher_type, count in sorted(multiple_fetcher_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {fetcher_type}: {count}", file=sys.stderr)
    else:
        print("  (none)", file=sys.stderr)


if __name__ == "__main__":
    main()
