#!/usr/bin/env python3
"""
Analyze git commits that added package.nix files in pkgs/by-name/
Classifies commits into:
- NEW: Clearly adds a new package
- MOVED: Clearly migrates/moves an existing package to by-name
- MANUAL: Needs manual review
"""

import subprocess
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import List
import sys

# Classification patterns
NEW_PATTERNS = [
    r'\binit\b.*\bat\b',  # "init at X.Y.Z"
    r'^[^:]+:\s*init\b',  # "package: init"
]

MOVED_PATTERNS = [
    r'migrate to by-name',
    r'move to by-name',
    r'treewide.*by-name',
    r'moved to by-name',
    r'migrated to by-name',
]

@dataclass
class CommitInfo:
    hash: str
    short_hash: str
    date: str
    author: str
    subject: str
    files: List[str]

    def classify(self) -> str:
        """Classify commit based on subject line"""
        subject_lower = self.subject.lower()

        # Check for new package patterns
        for pattern in NEW_PATTERNS:
            if re.search(pattern, self.subject, re.IGNORECASE):
                return "NEW"

        # Check for moved/migrated package patterns
        for pattern in MOVED_PATTERNS:
            if re.search(pattern, subject_lower):
                return "MOVED"

        # Everything else needs manual review
        return "MANUAL"

    def get_package_names(self) -> List[str]:
        """Extract package names from file paths"""
        packages = []
        for filepath in self.files:
            match = re.search(r'pkgs/by-name/[^/]+/([^/]+)/package\.nix', filepath)
            if match:
                packages.append(match.group(1))
        return packages


def fetch_commits(since: str, until: str) -> List[CommitInfo]:
    """Fetch commits that added package.nix files in pkgs/by-name/"""
    cmd = [
        "git", "log",
        "--diff-filter=A",  # Only additions
        "--name-only",
        "--pretty=format:%H|%ai|%an|%s",
        f"--since={since}",
        f"--until={until}",
        "--",
        "pkgs/by-name/*/*/package.nix"
    ]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    lines = result.stdout.strip().split('\n')

    # Parse output
    commits = []
    current_commit = None
    current_files = []

    for line in lines:
        if '|' in line:  # Commit header line
            # Save previous commit if exists
            if current_commit:
                commits.append(current_commit)

            parts = line.split('|', 3)
            current_commit = CommitInfo(
                hash=parts[0],
                short_hash=parts[0][:8],
                date=parts[1][:10],
                author=parts[2],
                subject=parts[3],
                files=[]
            )
            current_files = current_commit.files
        elif line.startswith('pkgs/by-name/'):
            current_files.append(line)
        elif line.strip() == '':
            # Empty line between commits
            continue

    # Don't forget the last commit
    if current_commit:
        commits.append(current_commit)

    return commits


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 analyze_package_additions.py <since_date> <until_date>")
        print("Example: python3 analyze_package_additions.py 2025-07-01 2025-08-31")
        sys.exit(1)

    since = sys.argv[1]
    until = sys.argv[2]

    print(f"Fetching commits from {since} to {until}...", file=sys.stderr)
    commits = fetch_commits(since, until)

    # Classify commits
    classified = defaultdict(list)
    for commit in commits:
        category = commit.classify()
        classified[category].append(commit)

    # Print summary to stderr
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"SUMMARY: Found {len(commits)} commits that added package.nix files", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(f"NEW packages:     {len(classified['NEW']):4d}", file=sys.stderr)
    print(f"MOVED packages:   {len(classified['MOVED']):4d}", file=sys.stderr)
    print(f"MANUAL review:    {len(classified['MANUAL']):4d}", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    # Write results to files with date range in filename
    output_files = {
        'NEW': f'new_packages_{since}_{until}.txt',
        'MOVED': f'moved_packages_{since}_{until}.txt',
        'MANUAL': f'manual_review_{since}_{until}.txt'
    }

    for category, filename in output_files.items():
        commits_in_category = classified[category]
        with open(filename, 'w') as f:
            for commit in commits_in_category:
                packages = commit.get_package_names()
                pkg_list = ','.join(packages)
                # Format: hash date packages subject
                f.write(f"{commit.hash} {commit.date} [{pkg_list}] {commit.subject}\n")

        print(f"Written {len(commits_in_category)} commits to {filename}", file=sys.stderr)


if __name__ == "__main__":
    main()
