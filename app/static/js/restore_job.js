/* Refresh the server-rendered job while keeping the operator on the same page. */
(function () {
    "use strict";

    const page = document.getElementById("restoreJobPage");
    if (!page) return;

    const connectionStatus = document.getElementById("restoreConnectionStatus");
    const fragmentUrl = new URL(window.location.href);
    fragmentUrl.searchParams.set("fragment", "1");
    let timer;
    let stopped = false;
    let terminalSeen = false;

    function schedule(seconds) {
        if (!stopped) timer = setTimeout(poll, seconds * 1000);
    }

    function refreshContent(current, next) {
        const currentForm = current.querySelector("#restoreConfirmation");
        const nextForm = next.querySelector("#restoreConfirmation");
        const sameConfirmation = currentForm && nextForm &&
            currentForm.elements.fingerprint.value === nextForm.elements.fingerprint.value &&
            currentForm.dataset.deviceName === nextForm.dataset.deviceName &&
            Boolean(currentForm.elements.confirm_name) === Boolean(nextForm.elements.confirm_name);
        let focusField;
        if (sameConfirmation) {
            nextForm.elements.acknowledge.checked = currentForm.elements.acknowledge.checked;
            if (nextForm.elements.confirm_name) {
                nextForm.elements.confirm_name.value = currentForm.elements.confirm_name.value;
            }
            if (currentForm.contains(document.activeElement)) {
                focusField = nextForm.elements[document.activeElement.name];
            }
        }

        const sameStage = JSON.parse(current.dataset.state)[0] === JSON.parse(next.dataset.state)[0];
        for (const id of ["restoreJournal", "restoreChecks", "restoreDiff"]) {
            const oldDetails = current.querySelector("#" + id);
            const newDetails = next.querySelector("#" + id);
            if (oldDetails && newDetails && (sameStage || id === "restoreJournal")) {
                newDetails.open = oldDetails.open;
            }
        }
        const oldResolution = current.querySelector("#restoreManualResolution");
        const newResolution = next.querySelector("#restoreManualResolution");
        if (oldResolution && newResolution && sameStage &&
            oldResolution.dataset.deviceName === newResolution.dataset.deviceName) {
            for (const name of ["resolution", "inspection_note", "confirm_name"]) {
                newResolution.elements[name].value = oldResolution.elements[name].value;
            }
            newResolution.elements.acknowledge.checked = oldResolution.elements.acknowledge.checked;
            if (oldResolution.contains(document.activeElement)) {
                focusField = newResolution.elements[document.activeElement.name];
            }
        }
        current.replaceWith(next);
        if (focusField) focusField.focus({preventScroll: true});
    }

    async function poll() {
        try {
            const response = await fetch(page.dataset.statusUrl, {
                headers: {Accept: "application/json"},
                cache: "no-store",
            });
            if (response.status === 401 || response.status === 403 || response.status === 404) {
                connectionStatus.textContent = "This job can no longer be refreshed. Reopen it from Restore history to check access.";
                connectionStatus.hidden = false;
                return;
            }
            if (!response.ok) throw new Error("Status request failed");

            const status = await response.json();
            const current = document.getElementById("restoreJobContent");
            const state = [status.status, status.stage, status.requested_action, status.events];
            if (JSON.stringify(state) !== JSON.stringify(JSON.parse(current.dataset.state))) {
                const fragment = await fetch(fragmentUrl, {cache: "no-store"});
                if (!fragment.ok) throw new Error("Job refresh failed");

                const markup = await fragment.text();
                const documentPart = new DOMParser().parseFromString(markup, "text/html");
                const next = documentPart.getElementById("restoreJobContent");
                if (!next) throw new Error("Job content unavailable");

                refreshContent(current, next);
                if (JSON.stringify(state) !== JSON.stringify(JSON.parse(next.dataset.state))) {
                    connectionStatus.hidden = true;
                    schedule(1);
                    return;
                }
            }
            connectionStatus.hidden = true;
            if (!status.terminal) {
                terminalSeen = false;
                schedule(3);
            } else if (document.getElementById("restoreManualResolution")) {
                schedule(8);
            } else if (!terminalSeen) {
                // The worker records the final journal entry after publishing the outcome.
                terminalSeen = true;
                schedule(3);
            }
        } catch {
            connectionStatus.textContent = "Status may be out of date. Trying to reconnect…";
            connectionStatus.hidden = false;
            schedule(8);
        }
    }

    window.addEventListener("pagehide", () => {
        stopped = true;
        clearTimeout(timer);
    });
    window.addEventListener("pageshow", (event) => {
        if (event.persisted) {
            stopped = false;
            schedule(0);
        }
    });
    schedule(3);
})();
