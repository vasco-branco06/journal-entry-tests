# Next steps

What is still untested. `spec/` wins over this file.
Delete an item once its test passes, and delete this file when nothing is left except the optional U8.

## Still to test

Status of the 27 tests in `spec/TESTS.xml`: 23 fully passing, 3 not started (U7, manual), 1 optional (U8, outside v1).

| Unit | Manual tests |
|---|---|
| U7 | test.ci_matrix (green on the 4 jobs: Python 3.11 and 3.14, Ubuntu and Windows; needs a commit and a push), test.budget_zero (owner reads the month's invoices), test.publish_permission (only the maintainer can publish the tag) |
| U8 (optional, outside v1) | test.word_scope |

### Checks outside the test list

- Run on Ubuntu: so far everything ran only on Windows. Covered by test.ci_matrix.
- A `results.xlsx` really held open by Excel: the tests force `os.replace` to fail, and no run has used a real lock with `analyze`.
- Specification network still marked unverified: the official checker is unavailable.

## Before publishing

- Ask the owner about each commit, about the author email (the first commit would make `braancovaasco@gmail.com` public), about creating the public repository and the first push, and about tag `v0.1.0`. No PyPI publication in version 1.
- Check the CI badge and clone URL in `README.md` against the final repository name.
