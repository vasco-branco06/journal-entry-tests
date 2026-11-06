# Next steps

What is still untested. `spec/` wins over this file.
Delete an item once its test passes, and delete this file when nothing is left except the optional U8.

## Still to test

Status of the 27 tests in `spec/TESTS.xml`: 24 fully passing, 2 not started (U7, manual, owner), 1 optional (U8, outside v1).

| Unit | Manual tests |
|---|---|
| U7 | test.budget_zero (owner reads the month's invoices), test.publish_permission (only the maintainer can publish the tag; `gh api` already lists one collaborator, the owner confirms in Settings) |
| U8 (optional, outside v1) | test.word_scope |

### Checks outside the test list

- A `results.xlsx` really held open by Excel: the tests force `os.replace` to fail, and no run has used a real lock with `analyze`.
- Specification network still marked unverified: the official checker is unavailable.

## Before publishing

- Merge pull request #1 (owner decision), then tag `v0.1.0` on GitHub (owner decision). No PyPI publication in version 1.
