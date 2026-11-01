const API = "/api";

const state = {
    token: localStorage.getItem("forge_token"),
    user: null,
    project: null,
    register: false,
    generationPoll: null
};

const $ = (id) => document.getElementById(id);

const authView = $("auth-view");
const appView = $("app-view");
const dashboardView = $("dashboard-view");
const workspaceView = $("workspace-view");

function toast(message) {
    const el = $("toast");
    el.textContent = message;
    el.classList.remove("hidden");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.add("hidden"), 3200);
}

async function request(path, options = {}) {
    const headers = { ...(options.headers || {}) };

    if (state.token) headers.Authorization = `Bearer ${state.token}`;
    if (options.body) headers["Content-Type"] = "application/json";

    const response = await fetch(`${API}${path}`, {
        ...options,
        headers
    });

    if (response.status === 401 && state.token) {
        logout(false);
        throw new Error("Your session expired. Please sign in again.");
    }

    const data = response.status === 204
        ? null
        : await response.json().catch(() => ({}));

    if (!response.ok) throw new Error(data.detail || "Something went wrong");
    return data;
}

function setAuthMode(register) {
    state.register = register;
    $("auth-title").textContent = register ? "Create your account" : "Sign in to your workspace";
    $("auth-subtitle").textContent = register
        ? "Set up your workspace in a few seconds."
        : "Pick up where you left off.";
    $("name-field").classList.toggle("hidden", !register);
    $("name").required = register;
    $("password").autocomplete = register ? "new-password" : "current-password";
    $("auth-submit").textContent = register ? "Create account" : "Sign in";
    $("auth-switch-text").textContent = register
        ? "Already have an account?"
        : "New to Forge?";
    $("auth-switch").textContent = register ? "Sign in" : "Create an account";
}

function showAuth() {
    authView.classList.remove("hidden");
    appView.classList.add("hidden");
    closeProjectModal();
    setAuthMode(false);
}

function showDashboard() {
    authView.classList.add("hidden");
    appView.classList.remove("hidden");
    dashboardView.classList.remove("hidden");
    workspaceView.classList.add("hidden");
    closePreview();
    state.project = null;
    stopGenerationPolling();
    loadProjects();
}

function showWorkspace(project) {
    state.project = project;
    dashboardView.classList.add("hidden");
    workspaceView.classList.remove("hidden");
    $("workspace-title").textContent = project.name;
    $("workspace-description").textContent = project.description || "No project description";
    closePreview();
    loadMessages();
    loadArtifactStatus();

    if (project.status === "in_progress") startGenerationPolling(project.id);
    else stopGenerationPolling();
}

function closePreview() {
    const frame = $("project-preview");
    if (frame) frame.src = "about:blank";
    $("preview-container").classList.add("hidden");
}

function stopGenerationPolling() {
    if (state.generationPoll) {
        clearInterval(state.generationPoll);
        state.generationPoll = null;
    }
}

function startGenerationPolling(projectId) {
    stopGenerationPolling();

    state.generationPoll = setInterval(async () => {
        if (!state.project || state.project.id !== projectId) {
            stopGenerationPolling();
            return;
        }

        try {
            const project = await request(`/projects/${projectId}`);
            state.project = project;

            if (project.status !== "in_progress") {
                stopGenerationPolling();
                await loadMessages();
                await loadProjects();
                await loadArtifactStatus();
                toast(
                    project.status === "completed"
                        ? "Website generation completed"
                        : project.status === "partially_completed"
                            ? "Website generated with checks to review"
                            : "Generation failed; any valid files are still available"
                );
            } else {
                await loadMessages();
            }
        } catch (error) {
            stopGenerationPolling();
            toast(error.message);
        }
    }, 2500);
}

async function loadUser() {
    state.user = await request("/auth/me");
    $("header-name").textContent = state.user.name;
    $("header-email").textContent = state.user.email;
}

async function loadProjects() {
    try {
        const projects = await request("/projects");
        $("project-count").textContent = `${projects.length} project${projects.length === 1 ? "" : "s"}`;
        $("projects-grid").innerHTML = "";
        $("empty-state").classList.toggle("hidden", projects.length > 0);

        projects.forEach(project => {
            const card = document.createElement("button");
            card.className = "project-card";

            const initial = document.createElement("div");
            initial.className = "mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-50 font-semibold text-indigo-600";
            initial.textContent = project.name.charAt(0).toUpperCase();

            const title = document.createElement("h3");
            title.className = "font-semibold text-slate-900";
            title.textContent = project.name;

            const desc = document.createElement("p");
            desc.className = "mt-2 min-h-10 text-sm leading-5 text-slate-500";
            desc.textContent = project.description || "No description added.";

            const meta = document.createElement("div");
            meta.className = "mt-5 flex items-center justify-between border-t border-slate-100 pt-4 text-xs text-slate-400";

            const status = document.createElement("span");
            status.textContent = project.status;

            const date = document.createElement("span");
            date.textContent = new Date(project.created_at).toLocaleDateString();

            meta.append(status, date);
            card.append(initial, title, desc, meta);
            card.addEventListener("click", () => showWorkspace(project));
            $("projects-grid").append(card);
        });
    } catch (error) {
        toast(error.message);
    }
}

async function loadMessages() {
    if (!state.project) return;

    try {
        const messages = await request(`/projects/${state.project.id}/messages`);
        $("messages").innerHTML = "";

        if (!messages.length) {
            addMessage(
                "assistant",
                "Hi! Tell me what you'd like to build. You can start with a simple description and add details as we go."
            );
        } else {
            messages.forEach(message => addMessage(message.role, message.content));
        }
    } catch (error) {
        toast(error.message);
    }
}

function addMessage(role, content) {
    const wrapper = document.createElement("div");
    wrapper.className = `message ${role}`;
    wrapper.textContent = content;
    $("messages").append(wrapper);
    $("messages").scrollTop = $("messages").scrollHeight;
}

async function loadArtifactStatus() {
    if (!state.project) return;

    const preview = $("preview-project-btn");
    const download = $("download-project-btn");
    preview.disabled = true;
    download.disabled = true;

    try {
        const result = await request(`/projects/${state.project.id}/artifacts`);
        preview.disabled = !result.has_generated_files;
        download.disabled = !result.has_generated_files;
        preview.title = result.has_generated_files
            ? "Preview generated website"
            : "Generate a valid website to enable preview";
        download.title = result.has_generated_files
            ? "Download generated website"
            : "Generate a valid website to enable download";
    } catch (error) {
        preview.disabled = true;
        download.disabled = true;
        toast(error.message);
    }
}

async function previewProject() {
    if (!state.project) return;

    const button = $("preview-project-btn");
    button.disabled = true;
    button.textContent = "Loading preview...";

    try {
        const data = await request(`/projects/${state.project.id}/preview-token`, {
            method: "POST"
        });

        if (!data.preview_url) throw new Error("Preview URL was not returned by the server");

        const frame = $("project-preview");
        frame.src = data.preview_url;
        $("preview-container").classList.remove("hidden");
        $("preview-container").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
        toast(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "Preview website";
    }
}

async function downloadProject() {
    if (!state.project) return;

    const button = $("download-project-btn");
    button.disabled = true;
    button.textContent = "Preparing ZIP...";

    try {
        const response = await fetch(`${API}/projects/${state.project.id}/download`, {
            headers: { Authorization: `Bearer ${state.token}` }
        });

        if (response.status === 401) {
            logout(false);
            throw new Error("Your session expired. Please sign in again.");
        }

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.detail || "Could not download this project");
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `forge-project-${state.project.id}.zip`;
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        toast("Website ZIP downloaded");
    } catch (error) {
        toast(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "Download website ZIP";
    }
}

function openProjectModal() {
    $("project-form").reset();
    $("project-modal").classList.remove("hidden");
    document.body.classList.add("modal-open");
    $("project-name").focus();
}

function closeProjectModal() {
    if ($("project-modal")) {
        $("project-modal").classList.add("hidden");
        document.body.classList.remove("modal-open");
    }
}

async function createProject(event) {
    event.preventDefault();
    const name = $("project-name").value.trim();
    const description = $("project-description").value.trim();

    if (!name) {
        toast("Please enter a project name");
        return;
    }

    const button = $("create-project-submit");
    button.disabled = true;
    button.textContent = "Creating...";

    try {
        const project = await request("/projects", {
            method: "POST",
            body: JSON.stringify({ name, description })
        });
        closeProjectModal();
        showWorkspace(project);
        toast("Project created successfully");
    } catch (error) {
        toast(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "Create project";
    }
}

function logout(showMessage = true) {
    stopGenerationPolling();
    state.token = null;
    state.user = null;
    state.project = null;
    localStorage.removeItem("forge_token");
    closePreview();
    showAuth();
    if (showMessage) toast("You have been logged out");
}

$("auth-switch").addEventListener("click", () => setAuthMode(!state.register));

$("auth-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("auth-submit");
    button.disabled = true;

    try {
        const payload = {
            email: $("email").value.trim(),
            password: $("password").value
        };
        const path = state.register ? "/auth/register" : "/auth/login";
        if (state.register) payload.name = $("name").value.trim();

        const result = await request(path, {
            method: "POST",
            body: JSON.stringify(payload)
        });

        state.token = result.access_token;
        localStorage.setItem("forge_token", state.token);
        state.user = result.user;
        await loadUser();
        showDashboard();
        $("auth-form").reset();
        toast(state.register ? "Account created successfully" : "Welcome back");
    } catch (error) {
        toast(error.message);
    } finally {
        button.disabled = false;
    }
});

$("logout-btn").addEventListener("click", () => logout());
$("new-project-btn").addEventListener("click", openProjectModal);
$("empty-create-btn").addEventListener("click", openProjectModal);
$("back-btn").addEventListener("click", showDashboard);
$("download-project-btn").addEventListener("click", downloadProject);
$("preview-project-btn").addEventListener("click", previewProject);
$("close-preview-btn").addEventListener("click", closePreview);
$("project-form").addEventListener("submit", createProject);
$("close-modal").addEventListener("click", closeProjectModal);
$("cancel-modal").addEventListener("click", closeProjectModal);

$("project-modal").addEventListener("click", (event) => {
    if (event.target.id === "project-modal") closeProjectModal();
});

document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !$("project-modal").classList.contains("hidden")) {
        closeProjectModal();
    }
});

$("chat-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("prompt-input");
    const content = input.value.trim();
    if (!content || !state.project) return;

    const button = $("send-btn");
    button.disabled = true;
    input.value = "";
    addMessage("user", content);

    try {
        await request(`/projects/${state.project.id}/messages`, {
            method: "POST",
            body: JSON.stringify({ content })
        });
        await loadMessages();
        startGenerationPolling(state.project.id);
    } catch (error) {
        addMessage("assistant", `I couldn't send that message: ${error.message}`);
    } finally {
        button.disabled = false;
        input.focus();
    }
});

(async function init() {
    if (!state.token) return showAuth();

    try {
        await loadUser();
        showDashboard();
    } catch {
        logout(false);
    }
})();