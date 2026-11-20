# Huawei: restore research

> Update: adapters now exist (`huawei_ce`, `huawei_s`), written from the findings below, **unverified on
> hardware** and off by default; see `restore_engine.md`. The open points below still apply.

Original result (before the adapters): no Huawei adapter or profile was written. The specification forbids inventing
commands and requires a confirmed safe mechanism per platform. The vendor documentation found
shows that the mechanisms differ by product family and software version, and several facts
needed to automate a restore are not confirmed.

## What the documentation shows

CloudEngine data-centre switches (VRP8):

* `load configuration file <filename> replace [relative]` replaces the running configuration
  with a file (CloudEngine 12800 V200R020C10, "File Management Commands");
  `display configuration replace file` / `display configuration replace failed` show the
  differences and failures.
* `rollback configuration to file <file-name>` rolls the configuration back to a file; after it
  the device configuration is the same as in the file (CloudEngine 16800 V300R024C10 command
  reference; S-series CloudEngine V600R023C00 configuration guide). The result is read with
  `display configuration rollback result`.
* Rollback points: `display configuration commit list`, `rollback configuration to commit-id …`.
* Two-phase mode: `commit trial <seconds>` applies a configuration for a trial period and rolls it
  back automatically when it is not confirmed; `abort trial` stops it (CloudEngine 9800/8800/6800
  V300R024C00). This is the only device-side protection against a lost session that was found.
* `display current-configuration` is used in the guides to check the running configuration.

Classic VRP5 switches (S1720/S2700/S5700/S6720 V200R011C10, V200R019C10) and AR routers:

* The backup guide describes saving `display current-configuration` output to a file or
  `configuration copy startup to file <file>`.
* The `rollback` command in the S-series V200R019C10 upgrade chapter rolls back the **system
  software** version, not the configuration.
* No documented online whole-configuration replace was found for these platforms.

## Re-checked (Oct 2026): campus S-series restore is file + reboot

Huawei's own guides for S1720/S2700/S5700/S6720 (V200R011C10) and S2720/S5700/S6700
(V200R019C10) describe restoring a configuration as: put the backed-up file on the device
(FTP/TFTP/FTPS/SFTP/SCP), select it with `startup saved-configuration <file>`, and **reboot**; the
guide states that the restored configuration takes effect only after the restart. The related
S-series material found documents backup (`display current-configuration` to a file,
`configuration copy startup to file <file>`) and this startup-file procedure, but **no online
replace of the running configuration**. A CloudEngine 16800 reference does document
`load configuration file <file> replace [relative]` and `display configuration replace file`.

So for campus S-series switches the documented restore is an outage (reboot), which does not fit
the engine's model of an online replace verified from a new SSH session. It could be built as a
separate, explicitly disruptive scenario, but only with a maintenance-window decision, a way to
return the device to the previous startup file, and hardware tests.

## Not confirmed

* Which command and which release combination applies to which model (the CE families
  documented above already differ from each other).
* How to put a configuration file on the device from NABS: Netmiko has no Huawei file-transfer
  helper; SFTP/SCP prerequisites (`sftp server enable`, user service types, default directory)
  were not confirmed for the models in use.
* The exact output and prompts of the replace and rollback commands, and the format of
  `display version` for each family (needed to recognise the platform).
* How `commit trial` combines with a file-based replace, and what happens to the session when the
  management interface changes.
* Whether the community NAPALM driver (`napalm-huawei-vrp`) offers a replace on the models in use.

## What is needed to proceed

1. The exact models and software versions to be supported first (CloudEngine, S-series, AR…).
2. A lab device with console access for each.
3. Outputs from those devices: `display version`, `display current-configuration`,
   `dir`, the result of `load configuration file … replace` or `rollback configuration to file …`
   on a test configuration, `display configuration rollback result`, and whether SFTP/SCP can be enabled.

Until then Huawei devices get no runnable profile and cannot be restored by NABS. Do not add a
Huawei YAML profile without its adapter.
