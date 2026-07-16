# ADR 0002: Repairing Invalid Alembic Revision 0007

## Status
Accepted

## Context
During a previous regression commit (`b68f90c`), a migration file named `0007_add_context_fields.py` was committed and pushed. However, due to merge conflicts or developer error, the file contents were left empty (0 bytes).

This 0-byte file lacked standard Alembic structure (e.g., `revision` and `down_revision` variables), causing Alembic and target startup sequences to fail immediately when trying to inspect or load the version list.

## Decision
Instead of performing disruptive actions such as modifying public commit history (force push, rebase, or reset) or maintaining runtime monkeypatches on Alembic core internals (such as patching `ScriptDirectory._load_revisions`), we decided to repair `0007_add_context_fields.py` directly in-place.

1. The file `0007_add_context_fields.py` is restored/modified to become a **valid historical no-op migration**.
2. It explicitly declares:
   - `revision = "0007_add_context_fields"`
   - `down_revision = "0006_command_receipts_hardened"`
3. Both `upgrade()` and `downgrade()` functions are empty `pass` statements, containing zero DDL modifications.
4. Subsequent migrations (such as `0008_worker_context_lookup.py`) will chain cleanly from `0007_add_context_fields` as their `down_revision`.

This ensures that the migration chain is fully valid, upgradeable, and downgradeable in all environments (development, staging, production) without requiring hacky runtime patches.

## Consequences
- **Zero History Alteration**: Locus of origin is preserved byte-for-byte in older commits; the fix is implemented via standard corrective code commits.
- **Robust Migration Path**: Alembic operations like `alembic upgrade head` and `alembic downgrade base` work out-of-the-box natively.
- **Testing Boundaries**: Disposable container testing verifies the validity of this chain locally, but it does **not** constitute deployed staging/production acceptance.
- **Safety Flags**: Shadow mode and control plane integration features remain disabled.
