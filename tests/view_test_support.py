"""Helpers for view-level tests: a tiny Flask app that serves the REAL view functions."""

from flask import Flask


def make_test_app(rules):
    """
    rules: [(url_rule, endpoint, view_function, methods), ...]
    The endpoints the views redirect to ("login", "devices", ...) are added as stubs,
    unless the caller registers a real one.
    """
    flask_app = Flask("view-tests")
    flask_app.config.update(TESTING=True, SECRET_KEY="test", WTF_CSRF_ENABLED=False)
    registered = set()
    for rule, endpoint, view, methods in rules:
        flask_app.add_url_rule(rule, endpoint, view, methods=methods)
        registered.add(endpoint)
    for endpoint, rule in (
        ("login", "/login"),
        ("devices", "/devices"),
        ("config", "/config_page/<device_id>"),
        ("diff_page", "/diff_page/<device_id>"),
    ):
        if endpoint not in registered:
            flask_app.add_url_rule(rule, endpoint, lambda **kw: "stub")
    return flask_app


def logged_in(client, rights="user", groups=(10,), user="tester", user_id=7):
    with client.session_transaction() as session:
        session["user"] = user
        session["rights"] = rights
        session["user_id"] = user_id
        session["allowed_devices"] = list(groups)


def flashed(client):
    with client.session_transaction() as session:
        return [message for _category, message in session.get("_flashes", [])]
