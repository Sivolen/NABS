"""
A simulated Cisco IOS / IOS XE device for the adapter tests.

The output formats are SYNTHETIC: written from the formats described in Cisco's
documentation (show version, dir, show archive config differences, configure replace),
NOT captured from a real device. They prove the adapter's logic, not that real devices
behave this way.
"""

import re

SHOW_VERSION_IOSXE = """Cisco IOS XE Software, Version 16.09.04
Cisco IOS Software [Fuji], Catalyst L3 Switch Software (CAT9K_LITE_IOSXE), Version 16.9.4, RELEASE SOFTWARE (fc2)
cisco C9200L-24T-4G (ARM64) processor (revision V02) with 1380000K/6147K bytes of memory.
"""
SHOW_VERSION_IOS = """Cisco IOS Software, C2960X Software (C2960X-UNIVERSALK9-M), Version 15.2(7)E3, RELEASE SOFTWARE (fc2)
cisco WS-C2960X-24TS-L (APM86XXX) processor (revision K0) with 524288K bytes of memory.
"""
SHOW_VERSION_NXOS = """Cisco Nexus Operating System (NX-OS) Software
NXOS: version 9.3(5)
"""
SHOW_VERSION_XR = "Cisco IOS XR Software, Version 6.5.3\n"
SHOW_VERSION_ASA = "Cisco Adaptive Security Appliance Software Version 9.12(4)\n"

RUNNING = """version 16.9
hostname old-name
!
interface GigabitEthernet0/0
 ip address 192.0.2.1 255.255.255.0
!
ip scp server enable
line vty 0 4
 transport input ssh
end
"""
TARGET = RUNNING.replace("old-name", "new-name") + ""


class SimDevice:
    def __init__(
        self,
        running=RUNNING,
        version=SHOW_VERSION_IOSXE,
        filesystem="flash:",
        total=100_000_000,
        free=60_000_000,
        prompt="router#",
    ):
        self.running = running
        self.startup = running
        self.version = version
        self.filesystem = filesystem
        self.total, self.free = total, free
        self.prompt = prompt
        self.files = {}
        self.commands = []
        self.pending = None
        self.replace_output = None  # override the text printed by configure replace
        self.replace_applies = True
        self.replace_extra_line = (
            None  # a line the device adds when it applies (cosmetics)
        )
        self.on_replace = (
            None  # callable(device) -> raise to simulate a dropped session
        )
        self.copy_output = None
        self.diff_output = None
        self.transfer_error = None
        self.new_sessions_allowed = True
        self.sessions_opened = 0
        self.kwargs_log = []
        self.refuse_delete = False

    # ---- what the adapter sees
    def handle(self, command):
        self.commands.append(command)
        if self.pending and command == "\n":
            action, self.pending = self.pending, None
            return action()
        if command == "show version":
            return self.version
        if command == "dir":
            return (
                f"Directory of {self.filesystem}/\n\n    1  -rw-  1234  Oct 5 2026 x.bin\n\n"
                f"{self.total} bytes total ({self.free} bytes free)\n"
            )
        m = re.match(r"dir (\S+)$", command)
        if m:
            name = m.group(1)
            if name in self.files:
                return f"Directory of {name}\n  1 -rw- {len(self.files[name])} {name}\n"
            return "%Error opening " + name + " (No such file or directory)"
        if command == "show running-config":
            body = self.running
            return f"Building configuration...\n\nCurrent configuration : {len(body)} bytes\n!\n{body}"
        m = re.match(
            r"show archive config differences system:running-config (\S+)$", command
        )
        if m:
            if self.diff_output is not None:
                return self.diff_output
            name = m.group(1)
            if name not in self.files:
                return "%Error opening " + name + " (No such file or directory)"
            return self._diff(self.running, self.files[name])
        m = re.match(r"copy running-config (\S+)$", command)
        if m:
            name = m.group(1)

            def finish(name=name):
                self.files[name] = self.running
                return (
                    self.copy_output
                    or f"{len(self.running)} bytes copied in 0.420 secs (3085 bytes/sec)"
                )

            self.pending = finish
            return f"Destination filename [{name.split(':')[-1]}]? "
        m = re.match(r"configure replace (\S+) force$", command)
        if m:
            name = m.group(1)
            if self.on_replace:
                self.on_replace(self)
            if self.replace_applies and name in self.files:
                extra = (
                    self.replace_extra_line if "target" in name else None
                )  # not on rollback
                self.running = self.files[name] + (extra or "")
            if self.replace_output is not None:
                return self.replace_output
            return (
                "This will apply all necessary additions and deletions to replace the current "
                "running configuration with the contents of the specified configuration file, "
                "which is assumed to be a complete configuration, not a partial configuration.\n"
                "Total number of passes: 1\nRollback Done\n"
            )
        if command == "write memory":
            self.startup = self.running
            return "Building configuration...\n[OK]"
        m = re.match(r"delete /force (\S+)$", command)
        if m:
            if not self.refuse_delete:
                self.files.pop(m.group(1), None)
            return ""
        return "% Invalid input detected at '^' marker."

    @staticmethod
    def _diff(running, target):
        a = [l for l in running.splitlines() if l.strip() and not l.startswith("!")]
        b = [l for l in target.splitlines() if l.strip() and not l.startswith("!")]
        removed = [l for l in a if l not in b]
        added = [l for l in b if l not in a]
        if not removed and not added:
            return "No changes were found"
        lines = ["!Contextual Config Diffs:"]
        lines += [f"+{l}" for l in added] + [f"-{l}" for l in removed]
        return "\n".join(lines)


class SimConnection:
    def __init__(self, device):
        self.device = device
        self.closed = False

    def send_command(self, command, **kwargs):
        self.device.kwargs_log.append((command, kwargs))
        return self.device.handle(command)

    # NO send_command_timing: it returns after a short silence, which is wrong for a
    # command that works silently for a long time (configure replace); the adapter
    # must not use it, and a test fails with AttributeError if it does

    def find_prompt(self):
        return self.device.prompt

    def disconnect(self):
        self.closed = True


def make_factory(device, fail_after=None):
    """connection_factory for the adapter. fail_after: the Nth and later connects fail."""
    state = {"n": 0}

    def factory(**kwargs):
        state["n"] += 1
        device.sessions_opened += 1
        device.last_connect_kwargs = kwargs
        if fail_after is not None and state["n"] > fail_after:
            raise OSError("no route to host")
        if state["n"] > 1 and not device.new_sessions_allowed:
            raise OSError("connection refused")
        return SimConnection(device)

    factory.state = state
    return factory


def make_transfer(device):
    def transfer(
        conn, source_file, dest_file, file_system, direction, overwrite_file, **kw
    ):
        assert direction == "put"
        if device.transfer_error:
            raise device.transfer_error
        with open(source_file, encoding="utf-8") as handle:
            device.files[f"{file_system}{dest_file}"] = handle.read()
        device.last_local_file = source_file
        device.commands.append(f"<scp {dest_file}>")
        return {"file_exists": True, "file_transferred": True, "file_verified": True}

    return transfer
