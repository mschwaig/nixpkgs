#!/usr/bin/env python3
"""
Review commits interactively using git show
Usage: python3 review_commits.py <file>
Example: python3 review_commits.py new_packages.txt
"""

import subprocess
import sys

def review_commits(filename):
    """Read commits from file and show them interactively"""
    try:
        with open(filename, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found")
        sys.exit(1)

    print(f"Reviewing commits from: {filename}")
    print("Press 'q' to skip to next commit, Ctrl+C to stop")
    print("-" * 80)
    print()

    for line in lines:
        # Extract just the commit hash (first field)
        commit_hash = line.split()[0]

        # Run git show and pipe through less to always have pagination
        # -R preserves colors, -K allows Ctrl+C to exit less
        try:
            git_process = subprocess.Popen(
                ['git', 'show', '--color=always', "--stat", commit_hash],
                stdout=subprocess.PIPE
            )
            subprocess.run(
                ['less', '-R', '-K'],
                stdin=git_process.stdout
            )
            git_process.stdout.close()
            git_process.wait()
        except KeyboardInterrupt:
            print("\n\nStopped by user")
            sys.exit(0)

        print()

    print(f"Done reviewing all commits in {filename}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 review_commits.py <commit_file>")
        print("Example: python3 review_commits.py new_packages.txt")
        sys.exit(1)

    review_commits(sys.argv[1])


if __name__ == "__main__":
    main()
