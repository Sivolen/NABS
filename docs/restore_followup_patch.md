# Restore Engine follow-up patch

This patch addresses the first safety and integration items from the review of `restore_stage1_16.zip`.

## Changes

- Added `app/modules/access.py`, the shared fail-closed permission helper required by RestoreService and ProfileService. It uses the legacy NABS `rights`/`user_id` session fields and the existing `get_allowed_devices_by_right()` permission query for non-sadmin users.
- Added missing test bootstrap files `tests/nabs_test_stubs.py` and `tests/view_test_support.py`. They keep unit tests from initializing the production app, use the real Flask test client when Flask is installed, and load templates from `app/templates`.
- Added an audited manual-resolution path for `unknown` and `rollback_failed` jobs. It requires a meaningful note, exact device hostname/IP confirmation, and an explicit choice that the target or pre-restore state was manually verified. An uncertain result can be recorded without closing the job.
- Kept unresolved restore configurations protected. `failed` jobs are released from retention only when diagnostics explicitly say the device was not touched. `resolved_manual` jobs are released only when diagnostics show an explicit verified resolution. Manual config deletion and device deletion are blocked while an unresolved job still needs the associated config.
- Added explicit adapter finalization for Cisco and Huawei. Temporary files are removed after success or confirmed rollback, retained for `unknown`/failed rollback, and cleanup failures are written to the job summary, diagnostics and journal.
- Verified remote Huawei and Cisco file deletion rather than treating a returned CLI prompt as proof of deletion. Precheck cleanup failures now appear as warnings and are bound into the precheck fingerprint.
- Enforced an aggregate verification deadline between engine steps and bounded adapter read/reconnect attempts by the remaining budget. S-series verification timeout was increased to cover reconnect attempts plus read-back verification; the schema limit was updated accordingly.
- Increased Huawei CE trial duration to cover verification, final commit, save, and a safety margin. The exact trial command and allowed duration still require validation on each target VRP version.
- Huawei S-series rollback now restores the original startup filename after confirming the pre-restore running configuration. A device already configured to boot from a `nabs-restore-*` file is blocked until the previous restore is manually resolved.
- Updated docs and regression tests.

## Validation performed in this patch environment

- Python compilation: passed for `app/modules`, `app/views`, and `tests`.
- Jinja compilation: passed for all `restore*.html` templates.
- Automated tests: 382 selected tests covering access helpers, engine/state logic, Cisco/Huawei simulated adapters, profile/schema handling, services, and database retention guards passed.

The full UI test suite was not executed in this environment because Flask and Flask-SQLAlchemy are not installed here. The archive is a feature patch rather than a complete runnable NABS checkout. Run the full suite inside the project's normal virtual environment.

## Before using on hardware

- Generate/review/apply the database migration through the existing Flask-Migrate workflow in the full NABS checkout.
- Run all tests in the project's virtual environment and inspect the migration against a copy of the current database.
- Keep `RESTORE_ENABLE_UNVERIFIED_ADAPTERS = False` in production.
- Run the documented Cisco, Huawei CE and Huawei S-series hardware acceptance scenarios with console access. Simulators do not validate real CLI prompt wording, startup behavior, SFTP permissions, trial timer semantics, or reboot duration.
