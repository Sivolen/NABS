"""
The management pages that the menu shows only to some roles (drivers: sadmin/admin;
scheduler and validation profiles: sadmin) must be closed on the SERVER for the other
roles too - hiding a menu item is not an access check.
"""

import unittest
from unittest.mock import patch

import nabs_test_stubs

nabs_test_stubs.install_if_missing()

from app.views import drivers as drivers_view  # noqa: E402
from app.views import scheduler as scheduler_view  # noqa: E402
from app.views import validation_profiles as profiles_view  # noqa: E402
from view_test_support import logged_in, make_test_app  # noqa: E402

M = ["GET", "POST"]
ROUTES = [
    ("/drivers/", "drivers", drivers_view.drivers, M),
    ("/drivers_settings/", "drivers_settings", drivers_view.drivers_settings, M),
    ("/scheduler/", "scheduler_settings", scheduler_view.scheduler_settings, M),
    (
        "/validation_profiles/",
        "validation_profiles",
        profiles_view.validation_profiles,
        M,
    ),
    (
        "/validation_profiles/export/<int:profile_id>",
        "export_validation_profile",
        profiles_view.export_validation_profile,
        ["GET"],
    ),
    ("/validation_profiles/test_rule", "test_rule", profiles_view.test_rule, ["POST"]),
    (
        "/validation_profiles/export_rule/<int:rule_id>",
        "export_rule",
        profiles_view.export_rule,
        ["GET"],
    ),
    (
        "/validation_profiles/import_rule",
        "import_rule",
        profiles_view.import_rule,
        ["POST"],
    ),
    (
        "/validation_profiles/import",
        "import_validation_profile",
        profiles_view.import_validation_profile,
        ["POST"],
    ),
]
ADMIN_PLUS = {"/drivers/", "/drivers_settings/"}
SADMIN_ONLY = {r[0] for r in ROUTES} - ADMIN_PLUS


def url_of(rule):
    return rule.replace("<int:profile_id>", "1").replace("<int:rule_id>", "1")


class TestGlobalSettingsRoles(unittest.TestCase):
    def setUp(self):
        self.flask_app = make_test_app(ROUTES)
        self.flask_app.config["PROPAGATE_EXCEPTIONS"] = False
        self.flask_app.logger.disabled = True
        self.client = self.flask_app.test_client()

    def reached_the_view(self, rule, role):
        """True if the role passed the guards (the view body may then fail on mocks)."""
        logged_in(self.client, role, [10])
        url = url_of(rule)
        method = [r for r in ROUTES if r[0] == rule][0][3][-1]
        with patch("app.modules.dbutils.db_user_rights.logger"):
            response = self.client.open(
                url, method=method, json={} if method == "POST" else None
            )
        denied = (
            response.status_code == 302
            and response.headers["Location"].endswith("/devices")
        ) or b"Access dined" in response.data
        return not denied

    def test_plain_user_is_refused_everywhere(self):
        for rule, *_ in ROUTES:
            self.assertFalse(self.reached_the_view(rule, "user"), rule)

    def test_admin_only_reaches_the_drivers_pages(self):
        for rule in ADMIN_PLUS:
            self.assertTrue(self.reached_the_view(rule, "admin"), rule)
        for rule in SADMIN_ONLY:
            self.assertFalse(self.reached_the_view(rule, "admin"), rule)

    def test_sadmin_reaches_everything(self):
        for rule, *_ in ROUTES:
            self.assertTrue(self.reached_the_view(rule, "sadmin"), rule)

    def test_anonymous_is_sent_to_login(self):
        for rule, *_ in ROUTES:
            response = self.client.get(url_of(rule))
            self.assertIn(response.status_code, (302, 405), rule)
            if response.status_code == 302:
                self.assertIn("/login", response.headers["Location"], rule)


if __name__ == "__main__":
    unittest.main()
