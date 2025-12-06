#!/usr/bin/env python3
"""
Generate a commit loss report for the dataset creation pipeline.

This script analyzes the CSV files produced by the three-phase pipeline
(analyze_package_additions.py, extract_fetchers.py, validate_fetchers.py)
and reports how many commits are excluded at each step and why.
"""

import csv
from collections import defaultdict


def main():
    print("=" * 80)
    print("DATASET CREATION PIPELINE - COMMIT LOSS REPORT")
    print("=" * 80)
    print()

    # Phase 0: Starting point
    print("STARTING POINT")
    print("-" * 80)

    # Count actual commits
    excluded_phase1 = sum(1 for _ in open('excluded_packages_2025-08-01_2025-11-20.csv')) - 1
    passed_phase1 = sum(1 for _ in open('new_packages_2025-08-01_2025-11-20.csv')) - 1
    total_commits = excluded_phase1 + passed_phase1

    print(f"Total commits with new packages in date range: {total_commits}")
    print()

    # Phase 1: analyze_package_additions.py
    print("PHASE 1: analyze_package_additions.py")
    print("-" * 80)
    print("Applies: substantial package checks, build testing, exclusion rules")
    print()

    phase1_single_reasons = defaultdict(int)
    phase1_multiple_reasons = 0

    with open('excluded_packages_2025-08-01_2025-11-20.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            reasons = row['exclusion_reasons'].strip()
            if reasons:
                reason_list = [r.strip() for r in reasons.split(',') if r.strip()]
                if len(reason_list) > 1:
                    phase1_multiple_reasons += 1
                elif len(reason_list) == 1:
                    phase1_single_reasons[reason_list[0]] += 1

    print(f"Commits EXCLUDED in Phase 1: {excluded_phase1}")
    for reason, count in sorted(phase1_single_reasons.items(), key=lambda x: -x[1]):
        print(f"  - {reason}: {count}")
    if phase1_multiple_reasons > 0:
        print(f"  - multiple_reasons: {phase1_multiple_reasons}")
    print()
    print(f"Commits PASSING Phase 1: {passed_phase1}")
    print()

    # Phase 2: extract_fetchers.py
    print("PHASE 2: extract_fetchers.py")
    print("-" * 80)
    print("Applies: pname/version extraction, fetcher counting")
    print()

    single_fetcher_commits = set()
    with open('single_fetcher_2025-08-01_2025-11-20.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            single_fetcher_commits.add(row['commit_hash'])

    multiple_fetchers_commits = set()
    with open('multiple_fetchers_2025-08-01_2025-11-20.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            multiple_fetchers_commits.add(row['commit_hash'])

    excluded_phase2_commits = set()
    phase2_reasons = defaultdict(int)
    with open('fetcher_exclusions_2025-08-01_2025-11-20.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            excluded_phase2_commits.add(row['commit_hash'])
            reason = row['exclusion_reasons'].strip()
            if reason:
                phase2_reasons[reason] += 1

    # Combine all Phase 2 exclusions
    total_excluded_phase2 = len(excluded_phase2_commits) + len(multiple_fetchers_commits)

    print(f"Commits EXCLUDED in Phase 2: {total_excluded_phase2}")
    for reason, count in sorted(phase2_reasons.items(), key=lambda x: -x[1]):
        print(f"  - {reason}: {count}")
    print(f"  - multiple_fetchers: {len(multiple_fetchers_commits)}")
    print()
    print(f"Commits PASSING Phase 2: {len(single_fetcher_commits)}")
    print()

    # Phase 3: validate_fetchers.py
    print("PHASE 3: validate_fetchers.py")
    print("-" * 80)
    print("Applies: Nix evaluation test, source fetching, .nix file check")
    print()

    validated_commits = set()
    with open('single_fetcher_2025-08-01_2025-11-20_validated.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            validated_commits.add(row['commit_hash'])

    excluded_phase3_commits = set()
    with open('single_fetcher_2025-08-01_2025-11-20_exclusions.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            excluded_phase3_commits.add(row['commit_hash'])

    phase3_reasons = defaultdict(int)
    with open('fetcher_validation_failures.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            category = row['category'].strip()
            if category:
                phase3_reasons[category] += 1

    print(f"Commits EXCLUDED in Phase 3: {len(excluded_phase3_commits)}")
    for reason, count in sorted(phase3_reasons.items(), key=lambda x: -x[1]):
        print(f"  - {reason}: {count}")
    print()
    print(f"Commits PASSING Phase 3 (final dataset): {len(validated_commits)}")
    print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()
    print(f"Starting commits:                      {total_commits:>6}  (100.0%)")
    print(f"├─ Excluded in Phase 1:                {excluded_phase1:>6}  ({excluded_phase1/total_commits*100:>5.1f}%)")
    print(f"└─ Passed Phase 1:                     {passed_phase1:>6}  ({passed_phase1/total_commits*100:>5.1f}%)")
    print(f"   ├─ Excluded in Phase 2:             {total_excluded_phase2:>6}  ({total_excluded_phase2/total_commits*100:>5.1f}%)")
    print(f"   └─ Passed Phase 2:                  {len(single_fetcher_commits):>6}  ({len(single_fetcher_commits)/total_commits*100:>5.1f}%)")
    print(f"      ├─ Excluded in Phase 3:          {len(excluded_phase3_commits):>6}  ({len(excluded_phase3_commits)/total_commits*100:>5.1f}%)")
    print(f"      └─ FINAL DATASET:                {len(validated_commits):>6}  ({len(validated_commits)/total_commits*100:>5.1f}%)")
    print()

    total_excluded = excluded_phase1 + total_excluded_phase2 + len(excluded_phase3_commits)
    print(f"Total commits excluded:                {total_excluded:>6}  ({total_excluded/total_commits*100:>5.1f}%)")
    print(f"Final dataset size:                    {len(validated_commits):>6}  ({len(validated_commits)/total_commits*100:>5.1f}%)")
    print()
    print("=" * 80)

    # Verification
    print()
    print("VERIFICATION")
    print("-" * 80)
    expected = excluded_phase1 + passed_phase1
    actual = total_commits
    print(f"Phase 1: {excluded_phase1} excluded + {passed_phase1} passed = {expected} (expected {actual}) ✓" if expected == actual else f"Phase 1: MISMATCH")

    expected = total_excluded_phase2 + len(single_fetcher_commits)
    actual = passed_phase1
    print(f"Phase 2: {total_excluded_phase2} excluded + {len(single_fetcher_commits)} passed = {expected} (expected {actual}) ✓" if expected == actual else f"Phase 2: MISMATCH")

    expected = len(excluded_phase3_commits) + len(validated_commits)
    actual = len(single_fetcher_commits)
    print(f"Phase 3: {len(excluded_phase3_commits)} excluded + {len(validated_commits)} passed = {expected} (expected {actual}) ✓" if expected == actual else f"Phase 3: MISMATCH")


if __name__ == '__main__':
    main()
