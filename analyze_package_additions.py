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
import csv
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Set
import sys

# Processing limit for faster iteration (set to None for no limit)
COMMIT_LIMIT = 100

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
    test_base_commit: str = None
    build_success: bool = None
    build_error: str = None
    build_time: float = None  # Build time in seconds
    build_log_file: str = None  # Path to build log file for failures

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
            # Match pkgs/by-name/XX/name/package.nix
            match = re.search(r'pkgs/by-name/[^/]+/([^/]+)/package\.nix', filepath)
            if match:
                packages.append(match.group(1))
                continue

            # Match pkgs/.../name/default.nix - extract the parent directory name
            match = re.search(r'pkgs/.*/([^/]+)/default\.nix$', filepath)
            if match:
                packages.append(match.group(1))
        return packages

    def get_package_attr(self) -> str:
        """
        Extract package attribute from commit subject.
        Assumes format like "packageName: init at 1.0" or "python3Packages.foo: init at 1.0"
        Returns the part before the first colon.
        """
        if ':' in self.subject:
            return self.subject.split(':', 1)[0].strip()
        return None


def fetch_commits(since: str, until: str) -> List[CommitInfo]:
    """Fetch commits that added package.nix or default.nix files in pkgs/"""
    cmd = [
        "git", "log",
        "--diff-filter=A",  # Only additions
        "--name-only",
        "--pretty=format:%H|%ai|%an|%s",
        f"--since={since}",
        f"--until={until}",
        "--",
        "pkgs/by-name/*/*/package.nix",
        "pkgs/**/default.nix"
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
        elif line.startswith('pkgs/'):
            current_files.append(line)
        elif line.strip() == '':
            # Empty line between commits
            continue

    # Don't forget the last commit
    if current_commit:
        commits.append(current_commit)

    return commits


def get_all_commit_files(commit_hash: str) -> List[str]:
    """Get all files touched in a commit (excluding deletions)"""
    cmd = ['git', 'diff-tree', '--no-commit-id', '--name-only', '--diff-filter=AM', '-r', commit_hash]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]


def get_file_content_from_commit(commit_hash: str, filepath: str) -> str:
    """Get the content of a file as it was added in a commit"""
    cmd = ['git', 'show', f'{commit_hash}:{filepath}']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return result.stdout


def is_ancestor(ancestor_commit: str, descendant_commit: str) -> bool:
    """Check if ancestor_commit is an ancestor of descendant_commit"""
    cmd = ['git', 'merge-base', '--is-ancestor', ancestor_commit, descendant_commit]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def find_test_base_commit(package_commit: str, channel_bumps: List[str]) -> str:
    """
    Find the newest channel bump commit that IS an ancestor of package_commit.
    This gives us the newest channel state before the package was added.

    Args:
        package_commit: The commit that adds the package
        channel_bumps: List of channel bump commits, sorted newest to oldest

    Returns:
        The commit hash of the appropriate test base, or None if not found
    """
    for bump_commit in channel_bumps:
        if is_ancestor(bump_commit, package_commit):
            # This channel bump is in the package's history (happened before)
            return bump_commit
    return None


def load_channel_bumps(filepath: str) -> List[str]:
    """Load channel bump commits from a file (format: hash date time timezone)"""
    with open(filepath, 'r') as f:
        commits = []
        for line in f:
            line = line.strip()
            if line:
                # Extract just the commit hash (first field)
                commit_hash = line.split()[0]
                commits.append(commit_hash)
        return commits


def get_package_name_without_set(package_attr: str) -> str:
    """
    Extract package name without package set prefix.
    E.g., 'python3Packages.foo' -> 'foo', 'bar' -> 'bar'
    """
    if '.' in package_attr:
        return package_attr.split('.')[-1]
    return package_attr


def try_build_package(commit: 'CommitInfo', repo_path: str, log_dir: str) -> tuple[bool, str, float, str]:
    """
    Try to build a package by overlaying it onto the test base commit.

    Args:
        commit: CommitInfo with the package details
        repo_path: Path to the nixpkgs repository
        log_dir: Directory to store build logs

    Returns:
        (success, error_message, build_time_seconds, log_file_path)
    """
    import tempfile
    import os
    import time

    if not commit.test_base_commit:
        return (False, "No test base commit available", 0.0, None)

    package_attr = commit.get_package_attr()
    if not package_attr:
        return (False, "Cannot extract package attribute from commit subject", 0.0, None)

    # Get the package name without set prefix
    pkg_name = get_package_name_without_set(package_attr)

    # Get the first package file (should only be one for NEW packages)
    if not commit.files:
        return (False, "No package files found", 0.0, None)
    package_file = commit.files[0]

    # Get package file content from the commit
    try:
        package_content = get_file_content_from_commit(commit.hash, package_file)
    except subprocess.CalledProcessError as e:
        return (False, f"Failed to get package content: {e}", 0.0, None)

    # Determine if this is in a package set or top-level
    if '.' in package_attr:
        # Package set member (e.g., python3Packages.foo)
        package_set = package_attr.rsplit('.', 1)[0]

        # Create overlay that adds to the package set
        overlay_code = f'''
  overlay = self: super: {{
    {package_set} = super.{package_set} // {{
      {pkg_name} = self.{package_set}.callPackage (
        # Package content from commit
        {package_content}
      ) {{}};
    }};
  }};
'''
        build_attr = package_attr
    else:
        # Top-level package
        overlay_code = f'''
  overlay = self: super: {{
    {pkg_name} = self.callPackage (
      # Package content from commit
      {package_content}
    ) {{}};
  }};
'''
        build_attr = pkg_name

    # Create a temporary Nix expression to build the package
    nix_expr = f'''
let
  baseRepo = builtins.fetchTree {{
    type = "git";
    url = "file://{repo_path}";
    rev = "{commit.test_base_commit}";
  }};

  basePkgs = import baseRepo {{}};

  # Create overlay with our package
{overlay_code}

  pkgs = import baseRepo {{
    overlays = [ overlay ];
  }};
in
  pkgs.{build_attr}
'''

    # Write to temporary file and try to build
    with tempfile.NamedTemporaryFile(mode='w', suffix='.nix', delete=False) as f:
        f.write(nix_expr)
        temp_nix_file = f.name

    # Prepare log file path
    log_file = None
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    try:
        # Start timing
        start_time = time.time()

        # Run build and capture output to log file if it fails
        result = subprocess.run(
            ['nix', 'build', '--impure', '--expr', f'import {temp_nix_file}', '--no-link'],
            capture_output=True,
            text=True,
            timeout=900  # 15 minute timeout
        )

        build_time = time.time() - start_time

        if result.returncode == 0:
            return (True, "", build_time, None)
        else:
            # Save build log
            log_file = os.path.join(log_dir, f"{commit.hash}_build.log")
            with open(log_file, 'w') as lf:
                lf.write(f"Build command: nix build --impure --expr 'import {temp_nix_file}' --no-link\n")
                lf.write(f"Exit code: {result.returncode}\n")
                lf.write(f"Build time: {build_time:.2f}s\n")
                lf.write(f"\n=== STDOUT ===\n{result.stdout}\n")
                lf.write(f"\n=== STDERR ===\n{result.stderr}\n")
            return (False, f"Build failed with exit code {result.returncode}", build_time, log_file)
    except subprocess.TimeoutExpired:
        build_time = 900.0  # Timeout duration
        log_file = os.path.join(log_dir, f"{commit.hash}_build.log")
        with open(log_file, 'w') as lf:
            lf.write(f"Build command: nix build --impure --expr 'import {temp_nix_file}' --no-link\n")
            lf.write(f"Build timed out after {build_time}s\n")
        return (False, "Build timeout (15 minutes)", build_time, log_file)
    except Exception as e:
        return (False, str(e), 0.0, None)
    finally:
        os.unlink(temp_nix_file)


def check_package_viability(commit_hash: str, package_attr: str) -> tuple[bool, List[str]]:
    """
    Check if a package is viable for the dataset using nix flakes.
    Returns (is_viable, [reasons_for_exclusion])

    Checks:
    - Not broken (meta.broken)
    - Not unfree (meta.license)
    - Supported on Linux
    """
    reasons = []
    flake_ref = f"nixpkgs/{commit_hash}#{package_attr}"
    base_cmd = ['nix', 'eval', '--raw']

    # Check if package is broken
    try:
        result = subprocess.run(
            base_cmd + [f'{flake_ref}.meta.broken', '--apply', 'x: if x then "true" else "false"'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip() == 'true':
            reasons.append('broken')
    except subprocess.TimeoutExpired:
        reasons.append('eval_timeout')
        return (False, reasons)
    except subprocess.CalledProcessError:
        reasons.append('eval_failed')
        return (False, reasons)

    # Check if package is unfree
    try:
        expr = 'x: let license = x.meta.license or null; in if license == null then "false" else if builtins.isList license then (if builtins.any (l: !(l.free or true)) license then "true" else "false") else (if !(license.free or true) then "true" else "false")'
        result = subprocess.run(
            base_cmd + [f'{flake_ref}', '--apply', expr],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip() == 'true':
            reasons.append('unfree')
    except subprocess.TimeoutExpired:
        reasons.append('eval_timeout')

    # Check if package supports Linux (x86_64-linux)
    try:
        result = subprocess.run(
            base_cmd + [f'{flake_ref}.meta', '--apply',
                       'meta: if (meta ? availableOn) then (if meta.availableOn {{ system = "x86_64-linux"; }} then "true" else "false") else "true"'],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip() == 'false':
            reasons.append('not_on_linux')
    except subprocess.TimeoutExpired:
        reasons.append('eval_timeout')

    return (len(reasons) == 0, reasons)


def is_substantial_package(commit_hash: str, filepath: str) -> bool:
    """
    Check if a file is a substantial package definition.
    Criteria:
    - At least 6 lines AND
    - Contains "meta" AND
    - Contains pattern matching "src" = "fetch" (with possible whitespace)
    """
    content = get_file_content_from_commit(commit_hash, filepath)
    lines = content.split('\n')

    # Check line count
    if len(lines) < 6:
        return False

    # Check for "meta" in content
    if 'meta' not in content:
        return False

    # Check for src = fetch pattern (with flexible whitespace)
    # Matches: src = fetchXXX, src=fetchXXX, etc.
    if not re.search(r'src\s*=\s*fetch', content):
        return False

    return True


def apply_exclusion_rules(commits: List[CommitInfo]) -> tuple[List[CommitInfo], List[CommitInfo]]:
    """
    Apply exclusion rules to NEW commits.
    Returns (included_commits, excluded_commits)
    """
    included = []
    excluded = []

    for commit in commits:
        # Filter for substantial packages in added files
        substantial_added = [
            f for f in commit.files
            if is_substantial_package(commit.hash, f)
        ]

        # Check if commit adds multiple substantial packages
        if len(substantial_added) > 1:
            commit.exclusion_reasons.add('multiple_packages')

        # Get all files in the commit
        all_files = get_all_commit_files(commit.hash)

        # Check if commit modifies other substantial package files (beyond the ones it adds)
        # Look for both package.nix and default.nix files
        potential_packages = [
            f for f in all_files
            if (f.endswith('/package.nix') or f.endswith('/default.nix'))
            and f.startswith('pkgs/')
        ]

        # Filter for substantial packages in all files
        all_substantial = [
            f for f in potential_packages
            if is_substantial_package(commit.hash, f)
        ]

        added_substantial_set = set(substantial_added)
        if any(pkg for pkg in all_substantial if pkg not in added_substantial_set):
            commit.exclusion_reasons.add('modifies_other_packages')

        # Check for .patch or .diff files
        if any(f.endswith('.patch') or f.endswith('.diff') for f in all_files):
            commit.exclusion_reasons.add('requires_patching')

        # Check for lock files
        if any(f.endswith('.lock') or f.endswith('lock.json') or f.endswith('deps.json') for f in all_files):
            commit.exclusion_reasons.add('has_lock_files')

        # Check if commit touches os-specific packages
        if any(f.startswith('pkgs/os-specific') for f in all_files):
            commit.exclusion_reasons.add('os_specific')

        # Check if commit touches all-packages.nix
        if 'pkgs/top-level/all-packages.nix' in all_files:
            commit.exclusion_reasons.add('touches_all_packages')

        # Check package viability using nix (broken, unfree, linux support)
        package_attr = commit.get_package_attr()
        if package_attr:
            is_viable, viability_reasons = check_package_viability(commit.hash, package_attr)
            if not is_viable:
                for reason in viability_reasons:
                    commit.exclusion_reasons.add(reason)

        # If any exclusion reasons were found, move to excluded
        if commit.exclusion_reasons:
            excluded.append(commit)
        else:
            included.append(commit)

    return included, excluded


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 analyze_package_additions.py <since_date> <until_date> [channel_bumps_file]")
        print("Example: python3 analyze_package_additions.py 2025-07-01 2025-08-31 channel_bumps.txt")
        sys.exit(1)

    since = sys.argv[1]
    until = sys.argv[2]
    channel_bumps_file = sys.argv[3] if len(sys.argv) > 3 else None

    # Load channel bumps if provided
    channel_bumps = []
    if channel_bumps_file:
        print(f"Loading channel bumps from {channel_bumps_file}...", file=sys.stderr)
        channel_bumps = load_channel_bumps(channel_bumps_file)
        print(f"Loaded {len(channel_bumps)} channel bump commits", file=sys.stderr)

    print(f"Fetching commits from {since} to {until}...", file=sys.stderr)
    all_commits = fetch_commits(since, until)

    # Filter to only commits that added at least one substantial package
    print(f"Filtering {len(all_commits)} commits for substantial packages...", file=sys.stderr)
    commits = []
    for commit in all_commits:
        substantial_added = [
            f for f in commit.files
            if is_substantial_package(commit.hash, f)
        ]
        if substantial_added:
            commits.append(commit)

    print(f"Found {len(commits)} commits with substantial packages", file=sys.stderr)

    # Limit commits for faster iteration
    if COMMIT_LIMIT and len(commits) > COMMIT_LIMIT:
        print(f"Limiting to first {COMMIT_LIMIT} commits for faster iteration", file=sys.stderr)
        commits = commits[:COMMIT_LIMIT]

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

    # Find test base commits if channel bumps were provided
    if channel_bumps:
        print(f"Finding test base commits...", file=sys.stderr)
        no_test_base = []
        for commit in commits:
            test_base = find_test_base_commit(commit.hash, channel_bumps)
            commit.test_base_commit = test_base
            if test_base is None:
                print(f"WARNING: Could not find test base commit for {commit.hash} ({commit.subject})", file=sys.stderr)
                commit.exclusion_reasons.add('no_test_base')
                no_test_base.append(commit)

        # Move commits without test bases to EXCLUDED if they're in NEW
        for commit in no_test_base:
            if commit in classified['NEW']:
                classified['NEW'].remove(commit)
                classified['EXCLUDED'].append(commit)

        with_base = len(commits) - len(no_test_base)
        print(f"Found test bases for {with_base}/{len(commits)} commits", file=sys.stderr)
        if no_test_base:
            print(f"Excluded {len(no_test_base)} commits without test bases", file=sys.stderr)

        # Try building NEW packages
        print(f"Trying to build {len(classified['NEW'])} NEW packages...", file=sys.stderr)
        import os
        repo_path = os.getcwd()
        log_dir = f"build_logs_{since}_{until}"
        build_successes = 0
        build_failures = []

        for i, commit in enumerate(classified['NEW'], 1):
            print(f"  Building {i}/{len(classified['NEW'])}: {commit.get_package_attr()}...", file=sys.stderr)
            success, error, build_time, log_file = try_build_package(commit, repo_path, log_dir)
            commit.build_success = success
            commit.build_error = error if not success else None
            commit.build_time = build_time
            commit.build_log_file = log_file

            if success:
                build_successes += 1
            else:
                build_failures.append(commit)

        # Move build failures to EXCLUDED
        if build_failures:
            for commit in build_failures:
                commit.exclusion_reasons.add('build_failed')
                classified['NEW'].remove(commit)
                classified['EXCLUDED'].append(commit)

        print(f"Successfully built {build_successes}/{build_successes + len(build_failures)} packages", file=sys.stderr)
        if build_failures:
            print(f"Moved {len(build_failures)} build failures to EXCLUDED", file=sys.stderr)
            print(f"Build logs saved in {log_dir}/", file=sys.stderr)

    # Print summary to stderr
    print(f"\n{'='*80}", file=sys.stderr)
    print(f"SUMMARY: Found {len(commits)} commits that added package.nix or default.nix files", file=sys.stderr)
    print(f"{'='*80}", file=sys.stderr)
    print(f"NEW packages:     {len(classified['NEW']):4d}", file=sys.stderr)
    print(f"EXCLUDED:         {len(classified['EXCLUDED']):4d}", file=sys.stderr)
    print(f"OTHER changes:    {len(classified['OTHER_CHANGES']):4d}", file=sys.stderr)
    print(f"MANUAL review:    {len(classified['MANUAL']):4d}", file=sys.stderr)
    print(f"{'='*80}\n", file=sys.stderr)

    # Write results to CSV files with date range in filename
    output_files = {
        'NEW': f'new_packages_{since}_{until}.csv',
        'EXCLUDED': f'excluded_packages_{since}_{until}.csv',
        'OTHER_CHANGES': f'other_changes_{since}_{until}.csv',
        'MANUAL': f'manual_review_{since}_{until}.csv'
    }

    for category, filename in output_files.items():
        commits_in_category = classified[category]
        with open(filename, 'w', newline='') as f:
            writer = csv.writer(f, lineterminator='\n')

            # Write header
            if category == 'EXCLUDED':
                writer.writerow(['commit_hash', 'date', 'packages', 'subject', 'test_base_commit', 'exclusion_reasons', 'build_time', 'build_log_file'])
            elif category == 'NEW':
                writer.writerow(['commit_hash', 'date', 'packages', 'subject', 'test_base_commit', 'build_time'])
            else:
                writer.writerow(['commit_hash', 'date', 'packages', 'subject', 'test_base_commit'])

            # Write data
            for commit in commits_in_category:
                packages = commit.get_package_names()
                pkg_list = ','.join(packages)

                row = [
                    commit.hash,
                    commit.date,
                    pkg_list,
                    commit.subject,
                    commit.test_base_commit or ''
                ]

                # For excluded commits, add exclusion reasons and build info
                if category == 'EXCLUDED':
                    reasons = ','.join(sorted(commit.exclusion_reasons))
                    row.append(reasons)
                    row.append(f"{commit.build_time:.2f}" if commit.build_time is not None else '')
                    row.append(commit.build_log_file or '')
                # For new commits, add build time
                elif category == 'NEW':
                    row.append(f"{commit.build_time:.2f}" if commit.build_time is not None else '')

                writer.writerow(row)

        print(f"Written {len(commits_in_category)} commits to {filename}", file=sys.stderr)


if __name__ == "__main__":
    main()
