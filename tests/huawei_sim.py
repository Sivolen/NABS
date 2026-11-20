"""
Simulated Huawei devices (CloudEngine and S-series) for the adapter tests.

The outputs are SYNTHETIC: written from the formats described in Huawei's documentation, NOT
captured from a device. They prove the adapters' logic, not that real devices behave this way.
"""

import re

CE_VERSION = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 8.191 (CE6863E V200R019C10SPC800)
Copyright (C) 2012-2026 Huawei Technologies Co., Ltd.
"""
S_VERSION = """Huawei Versatile Routing Platform Software
VRP (R) software, Version 5.170 (S5720 V200R011C10SPC600)
Copyright (C) 2000-2026 Huawei Technologies Co., Ltd.
"""
AR_VERSION = "VRP (R) software, Version 5.170 (AR2220 V200R010C10SPC300)\n"

BODY = """sysname old-name
#
sftp server enable
#
interface {mgmt}
 ip address 192.0.2.1 255.255.255.0
#
interface GigabitEthernet0/0/1
 description uplink
#
user-interface vty 0 4
 authentication-mode aaa
 protocol inbound ssh
#
return
"""
CE_RUNNING = BODY.format(mgmt="MEth0/0/0")
S_RUNNING = BODY.format(mgmt="Vlanif1")
HEADER = "!Software Version V200R019C10SPC800\n!Last configuration was updated at 2026-10-08 10:00:00+11:00\n#\n"


def stored(running):
    """What a custom driver stores: the output of `display current-configuration`."""
    return HEADER + running


class FakeSftp:
    def __init__(self, device):
        self.device = device

    def put(self, local, remote):
        if self.device.sftp_error:
            raise self.device.sftp_error
        with open(local, encoding="utf-8") as handle:
            self.device.files[remote] = handle.read()
        self.device.last_local_file = local

    def stat(self, remote):
        class Stat:
            st_size = len(self.device.files[remote].encode("utf-8"))

        return Stat()

    def close(self):
        pass


class HwDevice:
    """Common part: files, display, dir, delete, prompts."""

    family = "ce"
    prompt_name = "HUAWEI"

    def __init__(self, running=None, version=None, free_kb=500000):
        self.running = running
        self.version = version
        self.free_kb = free_kb
        self.files = {}
        self.commands = []
        self.kwargs_log = []
        self.written = []
        self.pending = None
        self.view = "user"
        self.alive = True
        self.sftp_error = None
        self.sessions_opened = 0
        self.online = True
        self.refuse_new_sessions = 0
        self.last_connect_kwargs = {}
        self.refuse_delete = False

    # ---- prompts and output
    def prompt(self):
        if self.view == "user":
            return f"<{self.prompt_name}>"
        return f"[{self.system_marker}{self.prompt_name}]"

    system_marker = ""

    def reply(self, text=""):
        return (text + "\n" if text else "") + self.prompt()

    def question(self, text, on_answer):
        self.pending = on_answer
        return text  # ends with [Y/N]: and NO prompt, like the device

    # ---- commands
    def handle(self, command):
        self.commands.append(command)
        if self.pending is not None:
            callback, self.pending = self.pending, None
            return callback(command.strip().lower())
        if command == "display version":
            return self.reply(self.version)
        if command == "display current-configuration":
            return self.reply(stored(self.running))
        if command == "dir":
            return self.reply(
                f"Directory of flash:/\n\n  0 -rw- 1234 Oct 08 2026 10:00:00 vrpcfg.zip\n\n"
                f"1,036,308 KB total ({self.free_kb:,} KB free)"
            )
        m = re.match(r"dir (\S+)$", command)
        if m:
            name = m.group(1)
            if name in self.files:
                return self.reply(
                    f"  1 -rw- {len(self.files[name])} Oct 08 2026 10:05:00 {name}"
                )
            return self.reply("Error: Wrong parameter found at '^' position.")
        m = re.match(r"delete (\S+)$", command)
        if m:
            name = m.group(1)

            def done(answer, name=name):
                if answer == "y" and not self.refuse_delete:
                    self.files.pop(name, None)
                return self.reply()

            return self.question(
                f"Warning: The contents of file flash:/{name} cannot be recycled. Continue? [Y/N]:",
                done,
            )
        return self.extra(command)

    def extra(self, command):
        return self.reply("Error: Unrecognized command found at '^' position.")


class CeDevice(HwDevice):
    def prompt(self):
        if (
            self.view != "user"
            and self.system_marker == "~"
            and self.candidate is not None
        ):
            return f"[*{self.prompt_name}]"
        return super().prompt()

    family = "ce"

    def __init__(self, running=CE_RUNNING, version=CE_VERSION, two_phase=True, **kw):
        super().__init__(running, version, **kw)
        self.two_phase = two_phase
        self.system_marker = "~" if two_phase else ""
        self.candidate = None
        self.trial = None
        self.startup_saved = running
        self.replace_failures = []
        self.load_error = None
        self.trial_error = None
        self.commit_error = None
        self.revert_on_session_end = True
        self.drop_after = None  # a command after which the session dies
        self.save_output = "Info: Save the configuration successfully."

    def extra(self, command):
        if command == "system-view":
            self.view = "system"
            return self.reply(
                "Enter system view, return user view with return command."
            )
        if command == "return":
            self.view = "user"
            return self.reply()
        m = re.match(r"load configuration file (\S+) replace$", command)
        if m:
            if self.view != "system":
                return self.reply("Error: Unrecognized command found at '^' position.")
            if self.load_error:
                return self.reply(self.load_error)
            name = m.group(1)
            if name not in self.files:
                return self.reply("Error: The file does not exist.")
            self.candidate = self.files[name]
            return self.reply(
                "Info: The configuration file was loaded into the candidate configuration."
            )
        if command == "display configuration replace failed":
            if not self.replace_failures:
                return self.reply()
            body = "".join(
                f"Command : {c}\nView : system\nReason : cannot be replaced\n\n"
                for c in self.replace_failures
            )
            return self.reply("Failed command(s):\n\n" + body)
        if command == "display configuration candidate changes":
            if self.candidate is None:
                return self.reply()

            def real(text):  # comments (!) and separators (#) are not configuration
                return {
                    l
                    for l in text.split("\n")
                    if l.strip() and l.strip() != "#" and not l.startswith("!")
                }

            old, new = real(self.running), real(self.candidate)
            lines = [
                f"- {l.strip()}" for l in self.running.split("\n") if l in old - new
            ]
            lines += [
                f"+ {l.strip()}" for l in self.candidate.split("\n") if l in new - old
            ]
            return self.reply("\n".join(lines))
        if command == "clear configuration candidate":
            self.candidate = None
            return self.reply()
        m = re.match(r"commit trial (\d+)$", command)
        if m:
            if self.trial_error:
                return self.reply(self.trial_error)
            if self.candidate is None:
                return self.reply("Info: There is no configuration to commit.")
            self.trial = {"pre": self.running, "seconds": int(m.group(1))}
            self.running, self.candidate = self.candidate, None
            if self.drop_after == "commit trial":
                self.kill_session()
                raise OSError("socket is closed")
            return self.reply(
                f"Info: The system enters the trial configuration mode. The system will revert to"
                f" the previous configuration if the trial configuration is not confirmed in {m.group(1)} seconds."
            )
        if command == "commit":
            if self.commit_error:
                return self.reply(self.commit_error)
            if self.trial is not None:
                self.trial = None
            elif self.candidate is not None:
                self.running, self.candidate = self.candidate, None
            return self.reply()
        if command == "abort trial":

            def done(answer):
                if answer == "y" and self.trial is not None:
                    self.running, self.trial = self.trial["pre"], None
                    return self.reply(
                        "Info: The trial configuration rollback succeeded."
                    )
                return self.reply()

            return self.question(
                "Warning: The trial configuration will be rolled back. Continue? [Y/N]:",
                done,
            )
        if command == "save":

            def done(answer):
                if answer == "y":
                    self.startup_saved = self.running
                    return self.reply(self.save_output)
                return self.reply()

            return self.question("Are you sure to save the configuration? [Y/N]:", done)
        return super().extra(command)

    def kill_session(self):
        """The management session ends; an unconfirmed trial is reverted by the device."""
        self.alive = False
        if self.trial is not None and self.revert_on_session_end:
            self.running, self.trial = self.trial["pre"], None


class SDevice(HwDevice):
    family = "s"

    def __init__(self, running=S_RUNNING, version=S_VERSION, **kw):
        super().__init__(running, version, **kw)
        self.files["vrpcfg.zip"] = running
        self.current_startup = "flash:/vrpcfg.zip"
        self.next_startup = "flash:/vrpcfg.zip"
        # the questions `reboot` asks, in order: (text, kind)
        self.reboot_questions = [
            (
                "Info: The system is now comparing the configuration, please wait.\n"
                "Warning: The configuration has been modified, and it will be saved to the next startup "
                "saved-configuration file flash:/{next}. [Y/N]:",
                "save",
            ),
            ("System will reboot! Continue? [Y/N]:", "reboot"),
        ]
        self.saved_over_next = (
            False  # set when somebody answered Y to the save question
        )
        self.reboot_count = 0
        self.never_boots = False
        self.boots_offline_polls = (
            1  # new sessions refused this many times after the reboot
        )
        self.startup_error = None
        self.save_output = "Now saving the current configuration to the slot 1.\nSave the configuration successfully."

    def extra(self, command):
        if command == "display startup":
            return self.reply(
                "MainBoard:\n"
                "  Startup system software:                  flash:/s5720.cc\n"
                "  Next startup system software:             flash:/s5720.cc\n"
                f"  Startup saved-configuration file:         {self.current_startup}\n"
                f"  Next startup saved-configuration file:    {self.next_startup}"
            )
        m = re.match(r"startup saved-configuration (\S+)$", command)
        if m:
            if self.startup_error:
                return self.reply(self.startup_error)
            name = m.group(1)
            if name not in self.files:
                return self.reply("Error: The file does not exist.")
            self.next_startup = f"flash:/{name}"
            return self.reply("Info: Succeeded in setting the file for booting system.")
        m = re.match(r"compare configuration (\S+)$", command)
        if m:
            if m.group(1) not in self.files:
                return self.reply("Error: The file does not exist.")
            same = self.files[m.group(1)] == self.running
            return self.reply(
                "Info: The current configuration is the same as the specified file."
                if same
                else "Info: The current configuration is different from the specified file."
            )
        m = re.match(r"save (\S+)$", command)
        if m:
            name = m.group(1)

            def done(answer, name=name):
                if answer == "y":
                    self.files[name] = self.running
                    return self.reply(self.save_output)
                return self.reply()

            return self.question(
                f"Are you sure to save the configuration to flash:/{name}? [Y/N]:", done
            )
        if command == "reboot":
            return self._ask_reboot(0)
        return super().extra(command)

    def _ask_reboot(self, index):
        text, kind = self.reboot_questions[index]
        text = text.format(next=self.next_startup.split("/")[-1])

        def answer(reply):
            if kind == "save":
                if reply == "y":
                    self.saved_over_next = True
                return self._ask_reboot(index + 1)
            if kind == "reboot":
                if reply == "y":
                    self.do_reboot()
                    raise OSError("socket is closed")
                return self.reply("Info: The reboot was cancelled.")
            return self.reply("Info: Cancelled.")

        if kind == "combined":

            def answer(reply):  # noqa: F811 - a single question that saves AND reboots
                if reply == "y":
                    self.saved_over_next = True
                    self.do_reboot()
                    raise OSError("socket is closed")
                return self.reply("Info: The reboot was cancelled.")

        return self.question(text, answer)

    def write_channel(self, data):
        """The final `y\\n` of the reboot is written without waiting for an answer."""
        if self.pending is not None:
            callback, self.pending = self.pending, None
            try:
                callback(data.strip().lower())
            except OSError:
                pass

    def do_reboot(self):
        self.reboot_count += 1
        name = self.next_startup.split("/")[-1]
        if self.saved_over_next:
            self.files[
                name
            ] = self.running  # the hazard: the running config is saved over the file
        self.running = self.files[name]
        self.current_startup = self.next_startup
        self.alive = False
        self.online = not self.never_boots
        self.refuse_new_sessions = self.boots_offline_polls
        self.view = "user"


class HwConnection:
    def __init__(self, device):
        self.device = device
        self.closed = False

    def _check(self):
        if not self.device.alive and not self.closed:
            raise OSError("socket is closed")

    def send_command(self, command, **kwargs):
        self._check()
        self.device.kwargs_log.append((command, kwargs))
        return self.device.handle(command)

    def write_channel(self, data):
        self.device.written.append(data)
        self.device.write_channel(data) if hasattr(
            self.device, "write_channel"
        ) else None

    def find_prompt(self):
        self._check()
        return self.device.prompt()

    def disconnect(self):
        self.closed = True


def make_factory(device):
    def factory(**kwargs):
        device.last_connect_kwargs = kwargs
        if not device.online or device.refuse_new_sessions > 0:
            if device.refuse_new_sessions > 0:
                device.refuse_new_sessions -= 1
            raise OSError("no route to host")
        device.sessions_opened += 1
        if not device.alive:  # the device is back after a reboot: a fresh session
            device.alive = True
        return HwConnection(device)

    return factory


def make_sftp(device):
    return lambda conn: FakeSftp(device)
