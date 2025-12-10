#!/usr/bin/env python3
"""
Extract reference files from nixpkgs commits for validation.

This script reads the single_fetcher_2025-08-01_2025-11-20_validated.csv dataset
and extracts all files in the same directory as the package.nix/default.nix files
from the original nixpkgs commits. The output folder structure mirrors the CI
output structure from packagerix2, allowing easy comparison.
"""

import subprocess
import csv
import os
import sys
from pathlib import Path
from typing import Optional, List
import shutil


def get_package_file_path(commit_hash: str, package_name: str) -> Optional[str]:
    """
    Find the package.nix or default.nix file path for a package in a commit.

    Args:
        commit_hash: Git commit hash
        package_name: Name of the package

    Returns:
        Path to the package file, or None if not found
    """
    # Get all added package/default.nix files in this commit
    cmd = ['git', 'diff-tree', '--no-commit-id', '--name-only', '--diff-filter=A', '-r', commit_hash]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    files = result.stdout.strip().split('\n')

    # Look for package.nix or default.nix files in pkgs/
    for filepath in files:
        if filepath.startswith('pkgs/') and (filepath.endswith('/package.nix') or filepath.endswith('/default.nix')):
            # Check if this file is for the package we're looking for
            # The package name should be in the path or we can verify by checking the content
            if package_name in filepath or _verify_package_file(commit_hash, filepath, package_name):
                return filepath

    return None


def _verify_package_file(commit_hash: str, filepath: str, package_name: str) -> bool:
    """
    Verify if a package file is for the expected package by checking pname.

    Args:
        commit_hash: Git commit hash
        filepath: Path to the package file
        package_name: Expected package name

    Returns:
        True if the file is for the expected package
    """
    try:
        content = get_file_content(commit_hash, filepath)
        # Simple heuristic: check if pname matches
        import re
        pname_match = re.search(r'pname\s*=\s*["\']([^"\']+)["\']', content)
        if pname_match:
            return pname_match.group(1) == package_name
    except:
        pass
    return False


def get_file_content(commit_hash: str, filepath: str) -> str:
    """Get file content from a specific commit."""
    cmd = ['git', 'show', f'{commit_hash}:{filepath}']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def get_directory_files(commit_hash: str, directory: str) -> List[str]:
    """
    Get all files in a directory at a specific commit.

    Args:
        commit_hash: Git commit hash
        directory: Directory path

    Returns:
        List of file paths in the directory
    """
    cmd = ['git', 'ls-tree', '-r', '--name-only', commit_hash, directory]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    files = result.stdout.strip().split('\n')

    # Filter to only files in the exact directory (not subdirectories)
    directory_files = []
    for filepath in files:
        if filepath and filepath.startswith(directory):
            # Check if it's in the exact directory (no further subdirectories)
            relative = filepath[len(directory):].lstrip('/')
            if '/' not in relative:
                directory_files.append(filepath)

    return directory_files


def extract_package_files(commit_hash: str, package_name: str, pname: str, output_dir: Path) -> bool:
    """
    Extract all files from the package directory at the given commit.

    Args:
        commit_hash: Git commit hash
        package_name: Name attribute of the package (e.g., "python3Packages.foo")
        pname: The pname value from the CSV
        output_dir: Directory to save files to

    Returns:
        True if files were extracted successfully
    """
    # Find the package file
    package_file = get_package_file_path(commit_hash, pname)
    if not package_file:
        print(f"ERROR: Could not find package file for {package_name} in {commit_hash[:8]}", file=sys.stderr)
        return False

    # Get the directory containing the package file
    package_dir = str(Path(package_file).parent)

    # Get all files in that directory
    files = get_directory_files(commit_hash, package_dir)

    if not files:
        print(f"WARNING: No files found in {package_dir} for {package_name}", file=sys.stderr)
        return False

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Extract each file
    extracted_count = 0
    for filepath in files:
        try:
            content = get_file_content(commit_hash, filepath)
            filename = Path(filepath).name
            output_file = output_dir / filename

            with open(output_file, 'w') as f:
                f.write(content)

            extracted_count += 1
        except subprocess.CalledProcessError as e:
            print(f"WARNING: Failed to extract {filepath}: {e}", file=sys.stderr)

    print(f"  Extracted {extracted_count} files to {output_dir}", file=sys.stderr)
    return extracted_count > 0


def get_folder_name_from_csv_id(csv_id: int, package_name: str, pname: str) -> str:
    """
    Generate folder name matching the CI output structure.

    The CI creates folders like: <csv_id>-<package_name>-<pname>
    For example: 43-ocb-ocb

    Args:
        csv_id: The random_order ID from the CSV
        package_name: The package_name from CSV
        pname: The pname from CSV

    Returns:
        Folder name string
    """
    return f"{csv_id}-{package_name}-{pname}"


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 extract_reference_files.py <output_directory> [csv_file]")
        print("Example: python3 extract_reference_files.py ./reference_files")
        print("         python3 extract_reference_files.py ./reference_files single_fetcher_2025-08-01_2025-11-20_validated.csv")
        sys.exit(1)

    output_base = Path(sys.argv[1])
    csv_file = sys.argv[2] if len(sys.argv) > 2 else 'single_fetcher_2025-08-01_2025-11-20_validated.csv'

    # Read the CSV file
    print(f"Reading dataset from {csv_file}...", file=sys.stderr)
    packages = []

    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            packages.append({
                'random_order': int(row['random_order']),
                'commit_hash': row['commit_hash'],
                'package_name': row['package_name'],
                'pname': row['pname'],
                'version': row['version'],
            })

    print(f"Found {len(packages)} packages in dataset", file=sys.stderr)

    # Extract files for each package
    success_count = 0
    failure_count = 0

    for i, pkg in enumerate(packages, 1):
        csv_id = pkg['random_order']
        commit_hash = pkg['commit_hash']
        package_name = pkg['package_name']
        pname = pkg['pname']

        print(f"\n[{i}/{len(packages)}] Processing {package_name} (ID: {csv_id}, commit: {commit_hash[:8]})...", file=sys.stderr)

        # Create output directory with CI-style naming
        folder_name = get_folder_name_from_csv_id(csv_id, package_name, pname)
        # Nest the package files under a subdirectory named after pname (matching CI structure)
        output_dir = output_base / folder_name / pname

        if extract_package_files(commit_hash, package_name, pname, output_dir):
            success_count += 1
        else:
            failure_count += 1

    # Print summary
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"SUMMARY", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(f"Total packages:    {len(packages)}", file=sys.stderr)
    print(f"Successfully extracted: {success_count}", file=sys.stderr)
    print(f"Failed:            {failure_count}", file=sys.stderr)
    print(f"Output directory:  {output_base.absolute()}", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)


if __name__ == "__main__":
    main()
