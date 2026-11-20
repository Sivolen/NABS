from flask import render_template, request, session

from app.modules.auth.auth_users_ldap import check_auth
from app.modules.dbutils.db_dashboards import get_dashboard_summary
from app.modules.scheduler_manager import get_scheduler_next_run_time
from app.utils import get_server_params


@check_auth
def dashboards():
    summary = get_dashboard_summary(session)
    issue_filter = request.args.get("issues", "all")
    issues = summary["issues"]
    if issue_filter == "errors":
        issues = [device for device in issues if device["error"]]
    elif issue_filter == "missing":
        issues = [device for device in issues if not device["has_backup"]]
    else:
        issue_filter = "all"

    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    page_size = 8
    page = min(page, max(1, (len(issues) + page_size - 1) // page_size))
    start = (page - 1) * page_size
    end = start + page_size
    return render_template(
        "dashboards.html",
        dashboard_menu_active=True,
        summary=summary,
        issues=issues[start:end],
        issue_filter=issue_filter,
        issue_count=len(issues),
        first_issue=start + 1,
        last_issue=min(end, len(issues)),
        page=page,
        has_next=end < len(issues),
        server_params=get_server_params() if session["rights"] == "sadmin" else None,
        scheduler_info=get_scheduler_next_run_time(),
    )
