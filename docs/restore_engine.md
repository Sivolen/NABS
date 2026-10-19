# Restore Engine

Restores a configuration that NABS has stored onto the network device it came from.
It is **experimental**: read "Support status" before enabling it.

## Support status

| Platform | Adapter | State |
|---|---|---|
| Cisco IOS / IOS XE | `cisco_ios` (Netmiko, `configure replace`) | Written from Cisco documentation, tested on a **simulated** device only. **Off by default.** Not proven on hardware. |
| Huawei CloudEngine (CE6800, CE8800, ...) | `huawei_ce` (Netmiko, `load configuration file ... replace` + trial commit) | Written from Huawei documentation, simulated device only. **Off by default.** Not proven on hardware. Has a device-side revert timer. |
| Huawei S-series (S5700, S6700, ...) | `huawei_s` (startup file + **reboot**) | Written from Huawei documentation, simulated device only. **Off by default.** Not proven on hardware. **Reboots the switch.** |
| Eltex, MikroTik, others | none | Not supported. |

A YAML profile alone never makes a platform supported: a profile is runnable only if its
adapter is implemented, enabled and implements every action the profile uses. A platform
may be called supported only after the tests in "Hardware acceptance" were run on real
devices of that platform and software version.

To try the unverified adapters on a **lab** installation set `RESTORE_ENABLE_UNVERIFIED_ADAPTERS = True`
in `config.py` (see `config_example.py`) and restart the web server and the restore worker. This enables
Cisco and both Huawei adapters; do not set it on a production installation until each adapter has
passed hardware acceptance for the relevant model and VRP/IOS version.

## Which devices, and what the stored configuration must be

NABS collects configurations in two ways, and the restore follows both:

* **NAPALM driver** (`Devices.connection_driver` = `ios`, …): the platform is the driver name.
* **Custom driver** (`custom_drivers_switch` on): `connection_driver` then holds the **id** of a
  row in `Custom_Drivers`; the platform used here is that row's `drivers_platform`, i.e. the
  Netmiko device type. NABS offers only SSH types (`cisco_ios_ssh`, `cisco_xe_ssh`, …); the
  `_ssh` suffix is the transport and is ignored when platforms are compared. The device list in
  the UI shows this platform, not the id.

A profile lists the platform ids it accepts (`platforms`); the shipped Cisco profile accepts
`ios`, `cisco_ios` and `cisco_xe` (with or without `_ssh`). Other Netmiko types (for example
`cisco_s300_ssh`, or any `_telnet` type) are not accepted.

What is restored is the **stored text**. With a custom driver NABS stores the output of the
driver's **last command** as it is. For the Cisco adapter it must therefore be the complete
`show running-config`:

* `Building configuration...`, `Current configuration : N bytes` and `Using N out of M bytes`
  lines at the top are removed before the text is sent to the device;
* a stored text with fewer than half the lines of the device's current configuration is refused
  as "looks partial" (a filtered command such as `show run | ...` would otherwise wipe the rest);
* a restore that removes 20 % or more of the current lines is flagged in the precheck.

These are heuristics; the diff on the job page is the real check.

## How it works

```
 web UI (restore_profiles.py, restore_jobs.py)         never connects to a device
        |
 RestoreService / ProfileService  (service.py, profile_service.py)   rights, validation
        |  writes requests to the database
 restore worker (restore_worker.py, worker.py)          the only process that touches devices
        |
 RestoreEngine (engine.py)  ->  Platform adapter (adapters/*.py)  ->  device
        |
 Database (models: restore_profiles, device_restore_profiles, restore_jobs, restore_job_events)
 Existing `Configs` table (target configuration and the pre-restore copy)
```

* The **engine** is the same for every platform and contains no vendor command.
* A **profile** (YAML) names the steps to run; every step is an action from a fixed catalog.
* An **adapter** implements the actions for one kind of equipment.
* The backupers (`backuper.py`, `app/modules/backuper.py`) are not changed and not used.

### Flow

1. *Restore* on a device's config page opens `/restore/new` (nothing is created).
2. *Run precheck* creates a job and asks the worker for the precheck (`requested_action`).
3. The worker connects, runs the profile's check steps, saves the **pre-restore copy** of the
   device configuration into `Configs`, validates the target and builds a text diff.
4. The job page shows the checks, warnings and diff. Result: `ready`, `warning` or `blocked`.
5. The user ticks the box and confirms. The confirmation is bound to a fingerprint of the
   device, target configuration, profile and precheck outcome, and expires after 15 minutes.
6. The worker re-checks that the device still matches, applies, verifies, rolls back when
   verification fails, and finishes in one terminal state.

### States

| State | Meaning |
|---|---|
| `created` → `precheck_running` → `awaiting_confirmation` | preparation; a blocked precheck ends as `failed` |
| `queued` | confirmed, waiting for the worker |
| `running` → `verifying` | the device may be changing |
| `rollback_running` | rolling back |
| `success` | applied **and** verified by reading the configuration back |
| `failed` | failed; the summary says whether the device was verified unchanged |
| `failed_rollback_confirmed` | failed, previous configuration restored and confirmed |
| `rollback_failed` | rollback not confirmed: the device needs manual attention |
| `unknown` | the result cannot be established (lost session, unreadable state, restart); manual resolution required |
| `resolved_manual` | an operator confirmed the target or pre-restore state after out-of-band inspection |
| `cancelled` | cancelled before any change (also: confirmation expired) |

Terminal for worker execution means there is no automatic retry or resume. `unknown` and
`rollback_failed` can only transition to `resolved_manual` through the audited operator workflow;
if the device state remains uncertain, the job stays unresolved and its configuration copies remain protected.

### Safety rules (enforced in code)

* No restore without a successful precheck and an explicit confirmation of that precheck.
* The pre-restore copy is mandatory unless a profile explicitly turns it off (a warning is shown).
* One job cannot run twice: statuses change by atomic `UPDATE … WHERE status IN (…)` and a
  job is created with a unique `client_token`.
* A lost SSH session is never answered with a second apply. The engine reconnects within
  `reconnect_timeout`, reads the state back, and otherwise reports `unknown`.
* Success needs a positive read-back; "commands were sent" is never success.
* After a restart, claimed jobs become `unknown` and are never resumed.
* No generated reverse (`no …`) commands; a text diff is information only.
* Only roles `sadmin` and `admin`, and only on devices they may access; checked on every call.
* The web process has no adapters and cannot open a connection to a device.
* Configurations needed by an unfinished job (and by `unknown` / `rollback_failed` jobs) are
  protected from retention cleanup and manual deletion.

## Profiles

Built-in profiles are YAML files in `app/modules/restore/profiles/` (`<id>.yaml`, `builtin: true`).
They are read-only: copy one to change it. User profiles are stored in the database.

Schema version 1:

| Field | Notes |
|---|---|
| `schema_version` | must be `1` |
| `id`, `name`, `vendor`, `platforms`, `profile_version` | `id`: `[a-z0-9][a-z0-9_-]{1,62}`; `platforms` match the device's platform id (NAPALM driver name, or the Netmiko type of its custom driver) |
| `description`, `warnings` | optional text; `warnings` are shown at every precheck |
| `compatibility.models` / `os_versions` | optional glob lists. NABS does not store the OS version, so a version restriction makes every device "cannot be verified" |
| `adapter.type`, `adapter.device_type` | `cisco_ios`, `huawei_ce`, `huawei_s`, `mock` (tests only) |
| `restore.strategy` | `platform_specific` |
| `restore.require_precheck`, `require_confirmation` | must be `true` |
| `restore.require_pre_restore_backup`, `require_target_validation` | `true`, or `false` with a warning |
| `restore.disruptive` | `true` when the restore interrupts service (a reboot): the precheck warns, the job page shows a banner and the user must type the device name to confirm. Default `false` |
| `restore.steps` | list of `{action, params?, required?}` |
| `failure.rollback_strategy` | `none` (warning) or `platform_specific` |
| `failure.mark_unknown_if_connection_lost` | must be `true` |
| `limits` | seconds: `connect_timeout` 1–120 (10), `operation_timeout` 1–3600 (120), `verify_timeout` 1–1200 (60), `reconnect_timeout` 0–600 (60) |

Actions (a profile can name only these; unknown keys, aliases, duplicate keys, secret-like
key names such as `password`/`token`, files over 64 KiB and nesting over 8 are rejected):

| Action | Phase | Params |
|---|---|---|
| `check_platform_support`, `check_connectivity` | precheck | |
| `fetch_current_config`, `check_rollback_available` | precheck | may be `required: false` |
| `save_pre_restore_backup` (engine) | prepare | needs `fetch_current_config` before it |
| `validate_target_config` | prepare | |
| `apply_saved_config` | apply | exactly one |
| `verify_management_access` | verify | `attempts` 1–5 (3), `wait_seconds` 0–300 (10) |
| `verify_running_config` | verify | `compare`: `exact` or `normalized` (default) |
| `persist_config` | persist | |

Steps must follow the phase order, each action at most once, at least one `verify_*` step
must follow the apply, and the steps required by the `require_*` flags must precede it.

* **Copy**: `Copy` on a profile creates a user profile with a new id, version 1 and a recorded
  origin. The original is never changed. If a built-in profile is later updated, copies made
  from the older version are flagged ("source updated") and are not changed.
* **Edit**: user profiles only. Saving validates, stores the canonical YAML (comments are not
  kept), keeps the id, raises `profile_version` only when the content changed, and needs the
  checksum of the edited text (a concurrent change is a conflict).
* **Import / export**: preview shows problems and conflicts first. An imported profile is
  always a user profile, is never assigned automatically, and replaces an existing one only
  with explicit overwrite; a built-in id requires another id.
* **Assign**: to one device or a group. Only a valid, runnable profile and a positively
  compatible device are accepted; the result lists compatible / incompatible / cannot-verify /
  refused devices. Nothing is assigned automatically.
* **Delete**: user profiles only, not while assigned.
* Profile changes are logged to the `nabs.restore.audit` logger (who, what, which profile;
  never the YAML).

## Writing an adapter

Subclass `RestoreAdapter` (`adapters/base.py`) and override only the actions you really
implement; `supported_actions()` is derived from what you override. Rules:

* Return `Verdict.OK` only with positive evidence; return `UNKNOWN` when you cannot tell.
* Raise `ConnectionLost` / `AdapterTimeout` for a dropped session; never retry an apply.
* Put nothing secret and no configuration text into messages or `details`.
* Implement `rollback` **and** `verify_rollback`, or leave both out (the profile must then use
  `rollback_strategy: none`).
* Honour `ctx.profile.limits` yourself: the engine cannot interrupt a blocking call.
* Set `verified = False` until it has been run on real devices; register it in
  `adapters/__init__.py`. Add a profile only together with the adapter.
* Do not assume that similar CLI means the same restore semantics.

## Installation

1. Unpack the code and run `flask db migrate` / review the generated migration / `flask db upgrade`.
   Four new tables are created; no existing table or column changes.
2. Install the worker:
   ```bash
   sudo ln -s /opt/NABS/supervisor/nabs-restore-worker.service /etc/systemd/system/nabs-restore-worker.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now nabs-restore-worker
   journalctl -u nabs-restore-worker -f
   ```
   Exactly one worker runs (PostgreSQL advisory lock). It must be stopped gracefully; a restart
   marks jobs it had claimed as `unknown`.
3. Menu: **Settings → Restore Profiles** (roles `admin`, `sadmin`).

## Cisco IOS / IOS XE adapter

Prerequisites on the device: privilege level 15, `ip scp server enable` with SCP
authorization, free space on the file system for two copies of the configuration. The
restored configuration is saved to startup-config as the last step.

Mechanism: the precheck uploads the target file and asks the device for the differences
(`show archive config differences`); applying copies the running configuration to
`<fs>nabs-restore-<job>-pre.cfg`, uploads the target and runs `configure replace <file> force`;
the result is verified from a **new** SSH session and by comparing configurations; a failed
verification triggers `configure replace` from the pre-copy. Temporary files are cleaned after a
confirmed success or rollback; they are retained if the final device state is unknown or rollback fails.

**There is no device-side revert timer.** If the session is lost during the replace the device
does not roll back by itself. Console access may be needed. Use lab devices only.

Open points to settle on hardware: exact `configure replace` output per release; whether a
stored (cleaned) configuration is accepted (banners, certificates, indentation); availability
and format of `show archive config differences system:running-config`; SCP/AAA prerequisites;
whether `configure replace … time` can be used safely (its unit differs between releases);
behaviour when the management interface is changed.

## Tests

```bash
cd tests && python -m unittest discover -p "test_restore_*.py"
```

`tests/test_restore_*.py`, `restore_test_support.py` (in-memory stores) and `cisco_sim.py`
(simulated Cisco device; its outputs are **synthetic**, written from documentation). Not
covered by automatic tests: `db_store.py` and `restore_worker.py` against a real PostgreSQL,
the browser JavaScript, Netmiko itself, and any real device.

### Hardware acceptance (before a platform may be called supported)

On each platform and software version, on a device with console access: configuration read
back; the replace mechanism; result verification; behaviour on a rejected configuration;
rollback and its verification; behaviour when the session is lost; no false "success".
Never on production devices without an agreed test plan.

## Huawei adapters

Both accept the platforms `huawei_vrp` / `huawei` (NABS offers `huawei_vrp_ssh`, `huawei_ssh`; the `_ssh`
suffix is ignored). They cannot tell a CloudEngine from an S-series switch by platform id alone: the
adapter reads `display version` at the precheck and refuses the wrong family ("use the Huawei
S-series profile"), so assign the right profile to each device. The stored configuration must be the
complete `display current-configuration` (it must end with `return`; a text shorter than half of the
device's configuration is refused as partial). Prerequisites for both: `sftp server enable`, an
account allowed to use SFTP whose directory is the storage root, free space for two copies.

**CloudEngine (`huawei_ce`)** needs two-phase validation mode (prompt `[~...]`). Precheck: the target
is uploaded, loaded into the *candidate* (`load configuration file ... replace`), the device lists
what would change and what it cannot replace, and the candidate is cleared (nothing committed).
Apply: the rollback file (the NABS copy of the configuration before) and the target are uploaded,
the target is loaded and `commit trial <seconds>` makes it run **on trial**: the device returns to
the previous configuration by itself unless it is confirmed. Verification: a new SSH session, then
the configuration is compared with the target. Last step: `commit` (confirms the trial) and `save`.
A failed verification triggers `abort trial`.

**S-series (`huawei_s`) reboots the switch.** Huawei documents restoring these series as "put the
file on the device, make it the startup file with `startup saved-configuration`, restart". The
profile is marked `disruptive`: the switch is unreachable for several minutes, so use a maintenance
window and have console access ready. The questions of `reboot` are answered strictly: *save the
current configuration* is always answered **n** (a Y would write the running configuration over the
restore file and the restore would do nothing); a version that saves it over the file without
asking, or any unknown question, aborts before the reboot and puts the startup file back. After the
reboot the adapter waits for the device, requires `display startup` to show the restore file as the
file it booted from, compares the configuration, and finally moves the restored configuration back to
the original startup file name. A failed restore is rolled back by `startup saved-configuration
<rollback file>` and a second reboot. If the switch does not come back the result is `unknown`.

## Time and long commands

* Timestamps of the restore tables are **naive UTC** (a tz-aware value written to a
  `timestamp without time zone` column is converted to the database session's zone and comes
  back naive, which cannot be compared with the clock). The journal shows UTC. A confirmation
  whose stored time is more than 5 minutes in the future is refused as not trustworthy.
* A queued job whose start fails before it is claimed (any unexpected error) is **cancelled**
  with a message, never retried forever.
* On Cisco a long command (`configure replace`) is sent with `send_command(expect_string=...)`,
  i.e. the adapter waits for the prompt (up to `operation_timeout`); a fixed-silence read would
  return while the device is still working.
* The diff on the job page ignores the `show running-config` header, timestamp comments and bare
  `!` lines (the adapter decides what to ignore); the replace itself uses the full text.

## Known limitations

* No platform is verified on hardware.
* `verify_timeout` is an aggregate budget for the verification phase. The engine checks the deadline between steps, and platform adapters bound read commands and reconnect attempts by the remaining budget. A Netmiko/SSH call already in progress still relies on the transport read timeout; a timeout after an apply is treated as an uncertain device state, not proof that the device was unchanged.
* `unknown` and `rollback_failed` require manual inspection. The job page can record an audited resolution only after the operator confirms the target or pre-restore configuration and types the device hostname/IP. Unresolved jobs continue to protect their configurations; deleting a device or configuration referenced by an unresolved job is blocked. Temporary device-side files are retained for unknown/failed rollback and cleaned after success or confirmed rollback; cleanup failures are written to the job journal.
* Editing a profile in the UI drops YAML comments.
* The device card (`devices.html`) does not show the assigned profile yet; the data is available at
  `/api/restore_profiles/device/<id>`.
* Bulk restore through Nornir is not implemented. The service, engine and job model are per
  device and are meant to be reused by it (one job per device, concurrency limit, same checks).


## Manual resolution of an uncertain result

Jobs in `unknown` or `rollback_failed` are terminal for worker execution and are never retried automatically. An authorized operator can record a manual inspection from the job page. Closing the job requires a meaningful note, confirmation of the device hostname/IP, and an explicit choice that the target or pre-restore configuration was verified through console/out-of-band access. If the state remains uncertain, the operator can record the inspection but leave the job unresolved. The unresolved job continues to protect its target and pre-restore configuration from manual deletion and retention cleanup.
