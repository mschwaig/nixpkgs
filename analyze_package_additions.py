#!/usr/bin/env python3
"""
Analyze git commits that added package.nix files in pkgs/by-name/
Classifies commits into:
- NEW: Clearly adds a new package (after exclusion rules)
- EXCLUDED: New packages that match exclusion criteria (e.g., requires_patching)
- OTHER_CHANGES: Migrates/moves existing package to by-name or updates version
- MANUAL: Needs manual review
"""

import subprocess
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Set
import sys

# Classification patterns
NEW_PATTERNS = [
    r'\binit\b.*\bat\b',  # "init at X.Y.Z"
    r'^[^:]+:\s*init\b',  # "package: init"
]

OTHER_CHANGES_PATTERNS = [
    r'by-name',              # Any mention of by-name or pkgs/by-name
    r'top-level',            # Any mention of top-level
    r'migrate (from|to)',    # "migrate from/to X"
    r'move (from|to)',       # "move from/to X"
    r'extract (from|to)',    # "extract from/to X"
    r'refactor',             # Refactoring existing packages
    r'reinstate',            # Reinstating removed packages
    r'restore',              # Restoring removed packages
    r'repackage',            # Repackaging existing packages
    r'rewrite',              # Rewriting existing packages
    r'->',                   # Version updates like "package: 1.0 -> 2.0"
    r'^revert\b',            # Reverts like "Revert \"package: init at 1.0\""
    r'^reapply\b',           # Reapplying previous commits
]

@dataclass
class CommitInfo:
    hash: str
    short_hash: str
    date: str
    author: str
    subject: str
    files: List[str]
    exclusion_reasons: Set[str] = field(default_factory=set)

    def classify(self) -> str:
        """Classify commit based on subject line"""
        subject_lower = self.subject.lower()

        # Check for new package patterns
        for pattern in NEW_PATTERNS:
            if re.search(pattern, self.subject, re.IGNORECASE):
                return "NEW"

        # Check for moved/migrated/updated package patterns
        for pattern in OTHER_CHANGES_PATTERNS:
            if re.search(pattern, subject_lower):
                return "OTHER_CHANGES"

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


def get_all_commit_files(commit_hash: str) -> List[str]:
    """Get all files touched in a commit"""
    cmd = ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]


def apply_exclusion_rules(commits: List[CommitInfo]) -> tuple[List[CommitInfo], List[CommitInfo]]:
    """
    Apply exclusion rules to NEW commits.
    Returns (included_commits, excluded_commits)
    """
    included = []
    excluded = []

    for commit in commits:
        # Check if commit adds multiple packages
        if len(commit.files) > 1:
            commit.exclusion_reasons.add('multiple_packages')

        # Get all files in the commit
        all_files = get_all_commit_files(commit.hash)

        # Check if commit modifies other package.nix files (beyond the ones it adds)
        all_package_nix = [f for f in all_files if f.endswith('/package.nix') and f.startswith('pkgs/by-name/')]
        added_package_nix = set(commit.files)
        if any(pkg for pkg in all_package_nix if pkg not in added_package_nix):
            commit.exclusion_reasons.add('modifies_other_packages')

        # Check for .patch files
        if any(f.endswith('.patch') for f in all_files):
            commit.exclusion_reasons.add('requires_patching')

        # Check for lock files
        if any(f.endswith('.lock') or f.endswith('lock.json') or f.endswith('deps.json') for f in all_files):
            commit.exclusion_reasons.add('has_lock_files')

        # Check if commit touches all-packages.nix
        if 'pkgs/top-level/all-packages.nix' in all_files:
            commit.exclusion_reasons.add('touches_all_packages')

        # If any exclusion reasons were found, move to excluded
        if commit.exclusion_reasons:
            excluded.append(commit)
        else:
            included.append(commit)

    return included, excluded


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

    # Apply exclusion rules to NEW commits
    print(f"Applying exclusion rules to {len(classified['NEW'])} NEW commits...", file=sys.stderr)
    included_new, excluded_new = apply_exclusion_rules(classified['NEW'])
    classified['NEW'] = included_new
    classified['EXCLUDED'] = excluded_new

    # Print summary to stderr
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"SUMMARY: Found {len(commits)} commits that added package.nix files", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(f"NEW packages:     {len(classified['NEW']):4d}", file=sys.stderr)
    print(f"EXCLUDED:         {len(classified['EXCLUDED']):4d}", file=sys.stderr)
    print(f"OTHER changes:    {len(classified['OTHER_CHANGES']):4d}", file=sys.stderr)
    print(f"MANUAL review:    {len(classified['MANUAL']):4d}", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    # Write results to files with date range in filename
    output_files = {
        'NEW': f'new_packages_{since}_{until}.txt',
        'EXCLUDED': f'excluded_packages_{since}_{until}.txt',
        'OTHER_CHANGES': f'other_changes_{since}_{until}.txt',
        'MANUAL': f'manual_review_{since}_{until}.txt'
    }

    for category, filename in output_files.items():
        commits_in_category = classified[category]
        with open(filename, 'w') as f:
            for commit in commits_in_category:
                packages = commit.get_package_names()
                pkg_list = ','.join(packages)

                # For excluded commits, include reasons
                if category == 'EXCLUDED' and commit.exclusion_reasons:
                    reasons = ','.join(sorted(commit.exclusion_reasons))
                    f.write(f"{commit.hash} {commit.date} [{pkg_list}] {commit.subject} [EXCLUDED: {reasons}]\n")
                else:
                    # Format: hash date packages subject
                    f.write(f"{commit.hash} {commit.date} [{pkg_list}] {commit.subject}\n")

        print(f"Written {len(commits_in_category)} commits to {filename}", file=sys.stderr)


if __name__ == "__main__":
    main()
