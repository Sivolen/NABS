/* Read-only software inspection is queued for the background worker. */
(function () {
    "use strict";
    const box = document.getElementById("softwareInspection");
    if (!box) return;
    const button = document.getElementById("inspectSoftware");
    const status = document.getElementById("inspectionStatus");
    let timer = null;
    let requested = false;
    async function update(method) {
        try {
            const response = await fetch(box.dataset.url, {method: method, headers: {Accept: "application/json"}});
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || "Could not read inspection status. Check your session and try again.");
            button.disabled = !data.supported || data.status === "queued" || data.status === "running";
            if (!data.supported) {
                status.textContent = "Automatic software detection is not implemented for this platform yet.";
                return;
            }
            if (data.status === "queued" || data.status === "running") {
                status.textContent = data.message + (data.status === "queued" ? ". The restore worker must be running." : "…");
                timer = setTimeout(() => update("GET"), 3000);
            } else if (data.status === "ready" && data.fresh) {
                status.textContent = "Detected: " + (data.model || "") + " · " + (data.os_version || "");
                if (requested) window.location.reload();
            } else if (data.status === "failed") {
                status.textContent = data.message;
            } else if (data.status === "ready") {
                status.textContent = "The last result is outdated. Run detection again.";
            }
        } catch (error) {
            status.textContent = error.message;
            button.disabled = false;
        }
    }
    button.addEventListener("click", function () {
        clearTimeout(timer);
        requested = true;
        button.disabled = true;
        status.textContent = "Requesting device inspection…";
        update("POST");
    });
    window.addEventListener("pagehide", () => clearTimeout(timer));
    update("GET");
})();
