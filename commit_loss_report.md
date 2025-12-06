# Dataset Creation Pipeline - Commit Loss Report

## Summary

The 3-script data cleaning pipeline processes **911 commits** and produces a final dataset of **532 commits** (58.4% retention rate).

## Breakdown by Phase

### Phase 1: `analyze_package_additions.py`

- **Input:** 911 commits
- **Excluded:** 289 commits (31.7%)
  - build_failed: 142
  - requires_patching: 36
  - unfree: 28
  - has_lock_files: 20
  - no_test_base: 10
  - modifies_other_packages: 7
  - touches_all_packages: 6
  - eval_timeout: 6
  - multiple_packages: 3
  - broken: 2
  - multiple_reasons: 29
- **Output:** 622 commits (68.3%)

### Phase 2: `extract_fetchers.py`

- **Input:** 622 commits
- **Excluded:** 19 commits (2.1%)
  - multiple_fetchers: 16
  - version_missing: 2
  - no_fetchers_found: 1
- **Output:** 603 commits (66.2%)

### Phase 3: `validate_fetchers.py`

- **Input:** 603 commits
- **Excluded:** 71 commits (7.8%)
  - contains_nix_code: 62
  - finalAttr typo (should be finalAttrs): 9
- **Output:** 532 commits (58.4% - final dataset)

## Overall Statistics

- **Total exclusions:** 379 commits (41.6%)
- **Final dataset:** 532 commits (58.4%)
- Phase 1 accounts for the largest loss (31.7%), primarily due to build failures
- Phase 2 has minimal loss (2.1%)
- Phase 3 removes 7.8%, mainly for .nix code in source

## Pipeline Flow

```
Starting commits:                         911  (100.0%)
├─ Excluded in Phase 1:                   289  ( 31.7%)
└─ Passed Phase 1:                        622  ( 68.3%)
   ├─ Excluded in Phase 2:                 19  (  2.1%)
   └─ Passed Phase 2:                     603  ( 66.2%)
      ├─ Excluded in Phase 3:              71  (  7.8%)
      └─ FINAL DATASET:                   532  ( 58.4%)
```
