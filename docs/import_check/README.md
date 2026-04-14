<!-- @summary
Import check tool documentation: spec, design, implementation, engineering guide, module tests, and enhancements (spec, design, implementation) for post-refactoring Python import repair.
@end-summary -->

# docs/import_check

## Overview

Engineering documentation for the import check tool — a post-refactoring utility that detects and repairs broken Python imports using AST analysis, then verifies correctness without runtime loading.

## Files

| File | Purpose |
| --- | --- |
| `IMPORT_CHECK_SPEC.md` | Import check tool specification (symbol inventory, deterministic fixer, smoke test checker, API/CLI) |
| `IMPORT_CHECK_SPEC_SUMMARY.md` | Concise summary of import check spec |
| `IMPORT_CHECK_DESIGN.md` | Import check design document (task decomposition, contracts) |
| `IMPORT_CHECK_IMPLEMENTATION.md` | Import check implementation guide |
| `IMPORT_CHECK_ENGINEERING_GUIDE.md` | Import check engineering guide |
| `IMPORT_CHECK_MODULE_TESTS.md` | Import check module-level test specifications |
| `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` | Enhancements specification (relative imports, `__getattr__` fallback, stub files, inline suppression) |
| `IMPORT_CHECK_ENHANCEMENTS_SPEC_SUMMARY.md` | Concise summary of enhancements spec |
| `IMPORT_CHECK_ENHANCEMENTS_DESIGN.md` | Enhancements design document |
| `IMPORT_CHECK_ENHANCEMENTS_IMPLEMENTATION.md` | Enhancements implementation guide |

## Key Starting Points

- **Understanding the tool?** Start with `IMPORT_CHECK_SPEC_SUMMARY.md`
- **Full requirements?** Read `IMPORT_CHECK_SPEC.md`
- **Implementation details?** See `IMPORT_CHECK_ENGINEERING_GUIDE.md`
- **Enhancements deep dive?** `IMPORT_CHECK_ENHANCEMENTS_SPEC.md` + `IMPORT_CHECK_ENHANCEMENTS_DESIGN.md`
