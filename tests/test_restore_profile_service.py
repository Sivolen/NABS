"""Restore Engine, stage 5: profile management and assignment (backend)."""

import tempfile
import unittest
from pathlib import Path

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

import yaml  # noqa: E402

from app.modules.access import can_access_device  # noqa: E402
from app.modules.restore.adapters import adapter_capabilities  # noqa: E402
from app.modules.restore.adapters import base  # noqa: E402
from app.modules.restore.engine import ENGINE_IMPLEMENTED_ACTIONS  # noqa: E402
from app.modules.restore.profile_service import ProfileService  # noqa: E402
from app.modules.restore.profiles import BuiltinProfileProvider  # noqa: E402
from app.modules.restore.service import (  # noqa: E402
    CONFLICT,
    FORBIDDEN,
    INVALID,
    NOT_FOUND,
    ServiceError,
)
from restore_test_support import (  # noqa: E402
    FakeClock,
    InMemoryDevices,
    InMemoryProfileRepo,
    profile_yaml,
)

ADMIN = {"user": "anton", "rights": "admin", "allowed_devices": [5]}
SADMIN = {"user": "root", "rights": "sadmin"}
PLAIN_USER = {"user": "bob", "rights": "user", "allowed_devices": [5]}
OTHER_GROUP = {"user": "eve", "rights": "admin", "allowed_devices": [9]}
SECRET_TEXT = "TOPSECRET-VALUE"

DEVICES = {
    1: base.DeviceInfo(1, "192.0.2.1", "sw1", "mock_os", model="M1"),
    2: base.DeviceInfo(2, "192.0.2.2", "sw2", "ios", model="C9300"),
    3: base.DeviceInfo(3, "192.0.2.3", "sw3", "mock_os", model="M1"),
}


GROUP_DEVICES = {5: {1, 2}, 9: {3}}  # device 3 belongs to another group


def group_lookup(groups, device_id):
    return any(device_id in GROUP_DEVICES.get(g, ()) for g in groups)


def access(session_obj, device_id):
    return can_access_device(session_obj, device_id, group_lookup=group_lookup)


class MultiDevices(InMemoryDevices):
    def __init__(self):
        super().__init__(None, None)

    def get_device(self, device_id):
        return DEVICES.get(device_id)


def make_text(profile_id="mock_builtin", version=1, builtin=True, **extra):
    def mutate(data):
        data.update(
            id=profile_id,
            builtin=builtin,
            profile_version=version,
            name="Mock built-in",
        )
        data.update(extra)

    return profile_yaml(mutate)


class Env:
    def __init__(self, builtin_version=1, runnable=True):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup = None
        self.write_builtin("mock_builtin", make_text(version=builtin_version))
        self.repo = InMemoryProfileRepo()
        self.clock = FakeClock()
        self.caps = (
            (
                lambda: adapter_capabilities(
                    include_mock=True, engine_actions=ENGINE_IMPLEMENTED_ACTIONS
                )
            )
            if runnable
            else None
        )
        self.service = self.make_service()

    def write_builtin(self, name, text):
        Path(self.dir.name, f"{name}.yaml").write_text(text, encoding="utf-8")

    def make_service(self):
        return ProfileService(
            BuiltinProfileProvider(Path(self.dir.name)),
            self.repo,
            MultiDevices(),
            access=access,
            capabilities=self.caps,
            now=self.clock.utcnow,
        )

    def reload_builtin(self):
        self.service = self.make_service()


def code_of(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ServiceError as error:
        return error.code
    return None


class Base(unittest.TestCase):
    def setUp(self):
        self.env = Env()
        self.addCleanup(self.env.dir.cleanup)
        self.svc = self.env.service

    def user_profile(self, key="mine", **extra):
        text = profile_yaml(lambda d: d.update(id=key, name="Mine", **extra))
        return self.svc.create_profile(ADMIN, text)


class TestAuthorization(Base):
    def test_only_admin_roles_can_manage(self):
        text = profile_yaml()
        calls = [
            lambda s: self.svc.list_profiles(s),
            lambda s: self.svc.get_profile(s, "builtin", "mock_builtin"),
            lambda s: self.svc.export_profile(s, "builtin", "mock_builtin"),
            lambda s: self.svc.copy_profile(s, "builtin", "mock_builtin"),
            lambda s: self.svc.create_profile(s, text),
            lambda s: self.svc.import_profile(s, text),
            lambda s: self.svc.preview_assignment(s, [1], "builtin", "mock_builtin"),
            lambda s: self.svc.assign(s, [1], "builtin", "mock_builtin"),
            lambda s: self.svc.unassign(s, 1),
            lambda s: self.svc.suggest_for_device(s, 1),
            lambda s: self.svc.find_outdated_copies(s),
        ]
        for call in calls:
            for session in (PLAIN_USER, {}, {"rights": "admin"}):
                self.assertEqual(code_of(call, session), FORBIDDEN)
        self.assertEqual(self.env.repo.profiles, {})
        self.assertEqual(self.env.repo.assignments, {})

    def test_assignment_needs_access_to_each_device(self):
        result = self.svc.preview_assignment(
            OTHER_GROUP, [1, 3], "builtin", "mock_builtin"
        )
        self.assertEqual(
            [r["status"] for r in result["devices"]], ["denied", "compatible"]
        )
        self.assertEqual(
            self.svc.assign(OTHER_GROUP, [1, 3], "builtin", "mock_builtin")["assigned"],
            [3],
        )
        self.assertEqual(self.env.repo.assignments, {3: ("builtin", "mock_builtin")})
        self.assertEqual(code_of(self.svc.unassign, ADMIN, 3), FORBIDDEN)


class TestBuiltinProtection(Base):
    def test_builtin_is_viewable_but_read_only(self):
        view = self.svc.get_profile(ADMIN, "builtin", "mock_builtin")
        self.assertFalse(view["editable"])
        self.assertIn("schema_version", view["content"])
        self.assertEqual(
            code_of(
                self.svc.update_profile,
                ADMIN,
                "builtin",
                "mock_builtin",
                make_text(),
                "x",
            ),
            FORBIDDEN,
        )
        self.assertEqual(
            code_of(self.svc.delete_profile, ADMIN, "builtin", "mock_builtin"),
            FORBIDDEN,
        )
        self.assertEqual(self.env.repo.profiles, {})

    def test_a_user_profile_cannot_take_a_builtin_id(self):
        text = profile_yaml(lambda d: d.update(id="mock_builtin"))
        self.assertEqual(code_of(self.svc.create_profile, ADMIN, text), CONFLICT)

    def test_export_of_builtin_is_the_shipped_text(self):
        name, text = self.svc.export_profile(ADMIN, "builtin", "mock_builtin")
        self.assertEqual((name, text), ("mock_builtin.yaml", make_text()))


class TestCopy(Base):
    def test_copy_of_builtin(self):
        before = self.svc.get_profile(ADMIN, "builtin", "mock_builtin")["content"]
        view = self.svc.copy_profile(ADMIN, "builtin", "mock_builtin")
        self.assertEqual(view["key"], "mock_builtin_copy")
        self.assertEqual(
            (view["source"], view["editable"], view["profile_version"]),
            ("user", True, 1),
        )
        record = self.env.repo.profiles["mock_builtin_copy"]
        self.assertEqual(
            (record.origin_kind, record.origin_key, record.origin_version),
            ("builtin", "mock_builtin", 1),
        )
        parsed = yaml.safe_load(record.content)
        self.assertFalse(parsed["builtin"])
        self.assertEqual(
            self.svc.get_profile(ADMIN, "builtin", "mock_builtin")["content"], before
        )

    def test_copies_get_unique_ids_and_custom_ids_are_checked(self):
        first = self.svc.copy_profile(ADMIN, "builtin", "mock_builtin")["key"]
        second = self.svc.copy_profile(ADMIN, "builtin", "mock_builtin")["key"]
        self.assertNotEqual(first, second)
        self.assertEqual(
            self.svc.copy_profile(
                ADMIN, "builtin", "mock_builtin", "my_cisco", "My Cisco"
            )["name"],
            "My Cisco",
        )
        for bad in ("Bad Id", "", "x", "../etc", "mock_builtin"):
            self.assertIn(
                code_of(self.svc.copy_profile, ADMIN, "builtin", "mock_builtin", bad),
                (INVALID, CONFLICT),
            )
        self.assertEqual(
            code_of(
                self.svc.copy_profile, ADMIN, "builtin", "mock_builtin", "my_cisco"
            ),
            CONFLICT,
        )

    def test_copy_of_a_user_profile_is_marked_as_a_copy(self):
        self.user_profile("mine")
        self.svc.copy_profile(ADMIN, "user", "mine")
        self.assertEqual(self.env.repo.profiles["mine_copy"].origin_kind, "copy")

    def test_unknown_source_or_profile(self):
        self.assertEqual(
            code_of(self.svc.copy_profile, ADMIN, "builtin", "nope"), NOT_FOUND
        )
        self.assertEqual(code_of(self.svc.copy_profile, ADMIN, "weird", "x"), INVALID)


class TestEdit(Base):
    def edit(self, key="mine", mutate=None, sha=None):
        view = self.svc.get_profile(ADMIN, "user", key)
        data = yaml.safe_load(view["content"])
        (mutate or (lambda d: d.update(description="changed")))(data)
        return self.svc.update_profile(
            ADMIN,
            "user",
            key,
            yaml.safe_dump(data, sort_keys=False),
            sha or view["content_sha256"],
        )

    def test_change_raises_the_version_and_is_validated(self):
        self.user_profile()
        view = self.edit()
        self.assertEqual(view["profile_version"], 2)
        self.assertEqual(self.env.repo.profiles["mine"].profile_version, 2)

    def test_saving_the_same_content_does_not_bump_the_version(self):
        self.user_profile()
        self.assertEqual(self.edit(mutate=lambda d: None)["profile_version"], 1)

    def test_a_version_typed_by_the_user_is_ignored(self):
        self.user_profile()
        self.assertEqual(
            self.edit(mutate=lambda d: d.update(description="x", profile_version=50))[
                "profile_version"
            ],
            2,
        )

    def test_invalid_edit_is_refused_with_field_details_and_nothing_changes(self):
        self.user_profile()
        before = self.env.repo.profiles["mine"].content
        with self.assertRaises(ServiceError) as ctx:
            self.edit(
                mutate=lambda d: d["restore"]["steps"].insert(
                    0, {"action": "run_shell"}
                )
            )
        self.assertEqual(ctx.exception.code, INVALID)
        self.assertIn(
            "restore.steps[0].action", [d["path"] for d in ctx.exception.details]
        )
        self.assertEqual(self.env.repo.profiles["mine"].content, before)

    def test_id_cannot_change_and_builtin_flag_is_refused(self):
        self.user_profile()
        self.assertEqual(
            code_of(self.edit, "mine", lambda d: d.update(id="other")), INVALID
        )
        self.assertEqual(
            code_of(self.edit, "mine", lambda d: d.update(builtin=True)), INVALID
        )

    def test_stale_edit_is_a_conflict(self):
        self.user_profile()
        stale = self.svc.get_profile(ADMIN, "user", "mine")["content_sha256"]
        self.edit()  # somebody else saved first
        self.assertEqual(
            code_of(
                self.edit, "mine", lambda d: d.update(description="mine too"), stale
            ),
            CONFLICT,
        )
        self.assertEqual(
            yaml.safe_load(self.env.repo.profiles["mine"].content)["description"],
            "changed",
        )

    def test_lost_race_inside_the_repository_is_a_conflict(self):
        self.user_profile()
        view = self.svc.get_profile(ADMIN, "user", "mine")
        self.env.repo.update_user_profile = lambda *a, **k: False
        data = yaml.safe_load(view["content"])
        data["description"] = "x"
        self.assertEqual(
            code_of(
                self.svc.update_profile,
                ADMIN,
                "user",
                "mine",
                yaml.safe_dump(data, sort_keys=False),
                view["content_sha256"],
            ),
            CONFLICT,
        )

    def test_secret_like_fields_are_refused(self):
        self.user_profile()
        self.assertEqual(
            code_of(
                self.edit, "mine", lambda d: d["adapter"].update(password=SECRET_TEXT)
            ),
            INVALID,
        )
        self.assertNotIn(SECRET_TEXT, self.env.repo.profiles["mine"].content)


class TestImportExport(Base):
    def test_preview_changes_nothing(self):
        info = self.svc.import_profile(
            ADMIN, profile_yaml(lambda d: d.update(id="imported")), preview=True
        )
        self.assertTrue(info["can_import"])
        self.assertIsNone(info["conflict"])
        self.assertEqual(info["profile"]["key"], "imported")
        self.assertEqual(self.env.repo.profiles, {})

    def test_preview_reports_problems_without_raising(self):
        info = self.svc.import_profile(ADMIN, "not: [valid", preview=True)
        self.assertFalse(info["valid"])
        self.assertFalse(info["can_import"])

    def test_import_creates_a_user_profile_with_origin_and_assigns_nothing(self):
        view = self.svc.import_profile(
            ADMIN, profile_yaml(lambda d: d.update(id="imported"))
        )
        self.assertEqual(view["source"], "user")
        record = self.env.repo.profiles["imported"]
        self.assertEqual(
            (record.origin_kind, record.origin_key), ("import", "imported")
        )
        self.assertEqual(record.profile_version, 1)
        self.assertEqual(self.env.repo.assignments, {})

    def test_builtin_flag_in_a_file_is_dropped(self):
        view = self.svc.import_profile(ADMIN, make_text("elsewhere_builtin"))
        self.assertFalse(
            yaml.safe_load(self.env.repo.profiles[view["key"]].content)["builtin"]
        )
        self.assertTrue(view["editable"])

    def test_id_of_a_builtin_needs_another_id_even_with_overwrite(self):
        text = make_text()
        self.assertEqual(
            code_of(self.svc.import_profile, ADMIN, text, overwrite=True), CONFLICT
        )
        self.assertEqual(
            self.svc.import_profile(ADMIN, text, preview=True)["conflict"], "builtin"
        )
        view = self.svc.import_profile(ADMIN, text, new_key="renamed_import")
        self.assertEqual(view["key"], "renamed_import")
        self.assertEqual(
            self.env.repo.profiles["renamed_import"].origin_key, "mock_builtin"
        )

    def test_overwrite_needs_explicit_confirmation(self):
        self.user_profile("mine")
        text = profile_yaml(lambda d: d.update(id="mine", description="from file"))
        self.assertEqual(code_of(self.svc.import_profile, ADMIN, text), CONFLICT)
        self.assertEqual(
            self.svc.import_profile(ADMIN, text, preview=True)["conflict"], "user"
        )
        view = self.svc.import_profile(ADMIN, text, overwrite=True)
        self.assertEqual(view["profile_version"], 2)

    def test_hostile_files(self):
        big = profile_yaml() + "\n# " + "x" * 70000
        alias = profile_yaml() + "x: &a [1]\ny: *a\n"
        secret = profile_yaml(lambda d: d["adapter"].update(password=SECRET_TEXT))
        shell = profile_yaml(
            lambda d: d["restore"]["steps"].insert(0, {"action": "run_shell"})
        )
        for text in (
            big,
            alias,
            secret,
            shell,
            "",
            None,
            123,
            "!!python/object/apply:os.system [ls]",
        ):
            self.assertEqual(
                code_of(self.svc.import_profile, ADMIN, text), INVALID, str(text)[:30]
            )
        self.assertEqual(self.env.repo.profiles, {})

    def test_export_import_round_trip(self):
        self.user_profile("mine")
        _name, text = self.svc.export_profile(ADMIN, "user", "mine")
        other = Env()
        self.addCleanup(other.dir.cleanup)
        view = other.service.import_profile(ADMIN, text)
        self.assertEqual(view["key"], "mine")
        self.assertEqual(
            yaml.safe_load(other.repo.profiles["mine"].content)["restore"],
            yaml.safe_load(self.env.repo.profiles["mine"].content)["restore"],
        )


class TestDelete(Base):
    def test_assigned_profile_cannot_be_deleted(self):
        self.user_profile("mine")
        self.svc.assign(ADMIN, [1], "user", "mine")
        self.assertEqual(
            code_of(self.svc.delete_profile, ADMIN, "user", "mine"), CONFLICT
        )
        self.svc.unassign(ADMIN, 1)
        self.svc.delete_profile(ADMIN, "user", "mine")
        self.assertEqual(self.env.repo.profiles, {})
        self.assertEqual(
            code_of(self.svc.delete_profile, ADMIN, "user", "mine"), NOT_FOUND
        )


class TestAssignment(Base):
    def test_three_groups_and_only_compatible_devices_are_assigned(self):
        self.user_profile("mine")
        preview = self.svc.preview_assignment(ADMIN, [1, 2, 3, 99, "x"], "user", "mine")
        self.assertEqual([r["device_id"] for r in preview["compatible"]], [1])
        self.assertEqual([r["device_id"] for r in preview["incompatible"]], [2])
        self.assertEqual(
            {r["status"] for r in preview["refused"]}, {"denied", "invalid"}
        )
        self.assertIn("platform", preview["incompatible"][0]["reason"])
        result = self.svc.assign(ADMIN, [1, 2, 3], "user", "mine")
        self.assertEqual(result["assigned"], [1])
        self.assertEqual({s["device_id"] for s in result["skipped"]}, {2, 3})
        self.assertEqual(self.env.repo.assignments, {1: ("user", "mine")})

    def test_unverifiable_device_is_not_assigned(self):
        text = profile_yaml(
            lambda d: d.update(id="strict", compatibility={"models": ["Z*"]})
        )
        self.svc.create_profile(ADMIN, text)
        DEVICES[1] = base.DeviceInfo(1, "192.0.2.1", "sw1", "mock_os", model=None)
        try:
            preview = self.svc.preview_assignment(ADMIN, [1], "user", "strict")
            self.assertEqual([r["device_id"] for r in preview["unverifiable"]], [1])
            self.assertEqual(
                self.svc.assign(ADMIN, [1], "user", "strict")["assigned"], []
            )
        finally:
            DEVICES[1] = base.DeviceInfo(1, "192.0.2.1", "sw1", "mock_os", model="M1")

    def test_not_runnable_profile_is_never_assigned(self):
        env = Env(runnable=False)  # production-like: no adapter is implemented
        self.addCleanup(env.dir.cleanup)
        preview = env.service.preview_assignment(ADMIN, [1], "builtin", "mock_builtin")
        self.assertTrue(preview["blockers"])
        self.assertIn("not runnable", preview["blockers"][0])
        self.assertFalse(preview["can_assign"])
        self.assertEqual(
            code_of(env.service.assign, ADMIN, [1], "builtin", "mock_builtin"), INVALID
        )
        self.assertEqual(env.repo.assignments, {})
        self.assertEqual(env.service.suggest_for_device(ADMIN, 1), [])

    def test_bad_requests(self):
        for ids in ([], None, "1", list(range(1, 600))):
            self.assertEqual(
                code_of(
                    self.svc.preview_assignment, ADMIN, ids, "builtin", "mock_builtin"
                ),
                INVALID,
            )
        self.assertEqual(
            code_of(self.svc.preview_assignment, ADMIN, [1], "builtin", "nope"),
            NOT_FOUND,
        )

    def test_assign_rechecks_instead_of_trusting_an_earlier_preview(self):
        self.user_profile("mine")
        self.svc.preview_assignment(ADMIN, [1], "user", "mine")
        DEVICES[1] = base.DeviceInfo(
            1, "192.0.2.1", "sw1", "ios", model="M1"
        )  # changed since
        try:
            self.assertEqual(
                self.svc.assign(ADMIN, [1], "user", "mine")["assigned"], []
            )
        finally:
            DEVICES[1] = base.DeviceInfo(1, "192.0.2.1", "sw1", "mock_os", model="M1")

    def test_reassigning_replaces_the_previous_profile(self):
        self.user_profile("mine")
        self.svc.assign(ADMIN, [1], "builtin", "mock_builtin")
        self.svc.assign(ADMIN, [1], "user", "mine")
        self.assertEqual(self.env.repo.assignments, {1: ("user", "mine")})

    def test_suggestions_are_offered_but_never_assigned(self):
        offers = self.svc.suggest_for_device(ADMIN, 1)
        self.assertEqual([o["key"] for o in offers], ["mock_builtin"])
        self.assertEqual(self.svc.suggest_for_device(ADMIN, 2), [])  # ios: no match
        self.assertEqual(self.env.repo.assignments, {})

    def test_device_card_shows_the_assignment(self):
        self.assertIsNone(self.svc.device_assignment(ADMIN, 1))
        self.svc.assign(ADMIN, [1], "builtin", "mock_builtin")
        card = self.svc.device_assignment(ADMIN, 1)
        self.assertEqual(
            (card["key"], card["missing"], card["profile_version"]),
            ("mock_builtin", False, 1),
        )
        self.assertEqual(code_of(self.svc.device_assignment, OTHER_GROUP, 1), FORBIDDEN)


class TestListingAndOutdatedCopies(Base):
    def test_listing_has_both_kinds_counts_and_filters(self):
        self.user_profile("mine")
        self.svc.assign(SADMIN, [1, 3], "builtin", "mock_builtin")
        rows = {r["key"]: r for r in self.svc.list_profiles(ADMIN)}
        self.assertEqual(set(rows), {"mock_builtin", "mine"})
        self.assertEqual(
            (rows["mock_builtin"]["kind"], rows["mock_builtin"]["assigned_count"]),
            ("builtin", 2),
        )
        self.assertTrue(rows["mock_builtin"]["runnable"])
        self.assertEqual(
            [r["key"] for r in self.svc.list_profiles(ADMIN, kind="user")], ["mine"]
        )
        self.assertEqual(
            [r["key"] for r in self.svc.list_profiles(ADMIN, query="BUILT")],
            ["mock_builtin"],
        )
        self.assertEqual(self.svc.list_profiles(ADMIN, vendor="nobody"), [])
        self.assertEqual(len(self.svc.list_profiles(ADMIN, sort="updated")), 2)

    def test_runnable_flag_is_false_without_an_implemented_adapter(self):
        env = Env(runnable=False)
        self.addCleanup(env.dir.cleanup)
        self.assertFalse(env.service.list_profiles(ADMIN)[0]["runnable"])
        view = env.service.get_profile(ADMIN, "builtin", "mock_builtin")
        self.assertTrue(view["runnable_issues"])

    def test_copies_of_an_updated_builtin_are_found_and_not_changed(self):
        self.svc.copy_profile(ADMIN, "builtin", "mock_builtin")
        self.svc.create_profile(
            ADMIN, profile_yaml(lambda d: d.update(id="independent"))
        )
        self.assertEqual(self.svc.find_outdated_copies(ADMIN), [])
        before = self.env.repo.profiles["mock_builtin_copy"].content

        self.env.write_builtin(
            "mock_builtin", make_text(version=2)
        )  # application update
        self.env.reload_builtin()
        outdated = self.env.service.find_outdated_copies(ADMIN)
        self.assertEqual([o["key"] for o in outdated], ["mock_builtin_copy"])
        self.assertEqual(outdated[0]["origin_version"], 1)
        self.assertEqual(
            self.env.repo.profiles["mock_builtin_copy"].content, before
        )  # untouched
        row = next(
            r
            for r in self.env.service.list_profiles(ADMIN)
            if r["key"] == "mock_builtin_copy"
        )
        self.assertTrue(row["origin_outdated"])
        view = self.env.service.get_profile(ADMIN, "user", "mock_builtin_copy")
        self.assertTrue(view["origin"]["outdated"])

    def test_stored_profile_that_no_longer_validates_is_listed_as_invalid(self):
        self.user_profile("mine")
        self.env.repo.profiles["mine"].content = "id: broken"
        row = next(r for r in self.svc.list_profiles(ADMIN) if r["key"] == "mine")
        self.assertFalse(row["valid"])
        self.assertFalse(row["runnable"])


class TestUnverifiedAdapterMessage(unittest.TestCase):
    def test_a_profile_of_an_unverified_adapter_says_why_it_cannot_run(self):
        from app.modules.restore.schema import parse_profile_yaml

        shipped = BuiltinProfileProvider().get("builtin", "cisco_ios")
        profile = parse_profile_yaml(shipped.content, allow_builtin=True).profile
        service = ProfileService(
            BuiltinProfileProvider(),
            InMemoryProfileRepo(),
            MultiDevices(),
            access=access,
            capabilities=lambda: {},
        )
        issues = service._runnable_issues(profile)
        self.assertEqual(len(issues), 1)
        self.assertIn("not been verified on hardware", issues[0]["message"])
        self.assertIn("RESTORE_ENABLE_UNVERIFIED_ADAPTERS", issues[0]["message"])
        row = next(r for r in service.list_profiles(ADMIN) if r["key"] == "cisco_ios")
        self.assertEqual(
            (row["kind"], row["valid"], row["runnable"]), ("builtin", True, False)
        )
        self.assertEqual(
            code_of(service.assign, ADMIN, [1], "builtin", "cisco_ios"), INVALID
        )

    def test_enabling_the_flag_makes_it_runnable(self):
        from unittest.mock import patch
        from app.modules.restore import settings

        service = ProfileService(
            BuiltinProfileProvider(),
            InMemoryProfileRepo(),
            MultiDevices(),
            access=access,
        )
        row = lambda: next(
            r for r in service.list_profiles(ADMIN) if r["key"] == "cisco_ios"
        )
        self.assertFalse(row()["runnable"])
        with patch.object(
            settings, "unverified_adapters_enabled", return_value=True
        ), patch(
            "app.modules.restore.profile_service.unverified_adapters_enabled",
            return_value=True,
        ):
            self.assertTrue(row()["runnable"])


class TestCiscoWithCustomDriverDevices(unittest.TestCase):
    """The reported case: the device has a NABS custom driver of type cisco_ios_ssh."""

    def setUp(self):
        self.repo = InMemoryProfileRepo()
        self.service = ProfileService(
            BuiltinProfileProvider(),
            self.repo,
            MultiDevices(),
            access=access,
            capabilities=lambda: adapter_capabilities(
                engine_actions=ENGINE_IMPLEMENTED_ACTIONS, include_unverified=True
            ),
        )
        self._saved = dict(DEVICES)
        self.addCleanup(lambda: (DEVICES.clear(), DEVICES.update(self._saved)))

    def put(self, device_id, platform, **kw):
        DEVICES[device_id] = base.DeviceInfo(
            device_id, f"192.0.2.{device_id}", f"sw{device_id}", platform, **kw
        )

    def test_cisco_ios_ssh_is_assignable(self):
        self.put(1, "cisco_ios_ssh", netmiko_device_type="cisco_ios_ssh")
        preview = self.service.preview_assignment(SADMIN, [1], "builtin", "cisco_ios")
        self.assertEqual(preview["blockers"], [])
        self.assertEqual([r["device_id"] for r in preview["compatible"]], [1])
        self.assertEqual(
            self.service.assign(SADMIN, [1], "builtin", "cisco_ios")["assigned"], [1]
        )
        self.assertEqual(self.repo.assignments, {1: ("builtin", "cisco_ios")})

    def test_other_platforms_and_telnet_are_not(self):
        for device_id, platform in (
            (1, "cisco_xe_ssh"),
            (2, "ios"),
            (3, "cisco_ios_telnet"),
            (4, "huawei_vrp_ssh"),
            (5, "cisco_s300_ssh"),
        ):
            self.put(device_id, platform)
        result = self.service.preview_assignment(
            SADMIN, [1, 2, 3, 4, 5], "builtin", "cisco_ios"
        )
        self.assertEqual(sorted(r["device_id"] for r in result["compatible"]), [1, 2])
        self.assertEqual(
            sorted(r["device_id"] for r in result["incompatible"]), [3, 4, 5]
        )

    def test_the_device_is_offered_the_profile(self):
        self.put(1, "cisco_ios_ssh", netmiko_device_type="cisco_ios_ssh")
        self.assertEqual(
            [o["key"] for o in self.service.suggest_for_device(SADMIN, 1)],
            ["cisco_ios"],
        )


class TestAudit(Base):
    def test_audit_has_who_and_what_but_never_the_yaml_or_secrets(self):
        with self.assertLogs("nabs.restore.audit", "INFO") as logs:
            self.user_profile("mine")
            self.svc.assign(ADMIN, [1], "user", "mine")
            self.svc.export_profile(ADMIN, "user", "mine")
        text = "\n".join(logs.output)
        for expected in (
            "user=anton",
            "action=create",
            "action=assign",
            "action=export",
            "profile=mine",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("schema_version", text)
        self.assertNotIn("restore:", text)


class TestDbMappingForProfiles(unittest.TestCase):
    def test_record_round_trip(self):
        from types import SimpleNamespace
        from app.modules.restore import dbmap
        from app.modules.restore.storage import UserProfileRecord

        record = UserProfileRecord(
            key="k",
            name="N",
            description="",
            vendor="V",
            platforms=["a", "b"],
            schema_version=1,
            profile_version=3,
            content="c",
            content_sha256="s",
            last_validation=[{"level": "warning"}],
        )
        columns = dbmap.profile_fields_to_columns(
            {n: getattr(record, n) for n in dbmap.PROFILE_FIELDS}
        )
        self.assertEqual(columns["profile_key"], "k")
        self.assertNotIn("key", columns)
        back = dbmap.row_to_profile_record(SimpleNamespace(**columns))
        self.assertEqual(back, record)
        with self.assertRaises(KeyError):
            dbmap.profile_fields_to_columns({"drop": 1})

    def test_every_field_has_a_model_column(self):
        from app.modules.restore import dbmap

        source = (
            Path(__file__).resolve().parent.parent / "app" / "models.py"
        ).read_text()
        part = source[
            source.index("class RestoreProfile(db.Model)") : source.index(
                "class DeviceRestoreProfile"
            )
        ]
        for name in dbmap.PROFILE_FIELDS:
            column = dbmap.PROFILE_COLUMN.get(name, name)
            self.assertIn(f"    {column} = db.Column", part, column)


if __name__ == "__main__":
    unittest.main()
