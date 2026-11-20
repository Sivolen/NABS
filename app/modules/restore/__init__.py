"""
Restore Engine: restoring a saved configuration on a network device.

This package is deliberately independent of the backupers (backuper.py,
app/modules/backuper.py): it never changes how configurations are collected.

Stage 1 contains only pure code without database or device access:
    actions.py  - the catalog of actions a profile may reference
    schema.py   - YAML restore profile parsing and validation
    compat.py   - profile <-> device compatibility check
"""
