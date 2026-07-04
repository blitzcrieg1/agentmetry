import {
  App,
  Modal,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  SuggestModal,
  requestUrl,
} from "obsidian";

interface BlackboxSettings {
  orchestratorUrl: string;
  apiKey: string;
}

const DEFAULT_SETTINGS: BlackboxSettings = {
  orchestratorUrl: "http://127.0.0.1:8000",
  apiKey: "",
};

interface PendingApproval {
  thread_id: string;
  skill_name: string;
  draft: string;
  confidence: number;
  created_at?: string;
}

interface SkillInfo {
  id: string;
  name?: string;
  display_name?: string;
  description?: string;
}

export default class BlackboxPlugin extends Plugin {
  settings: BlackboxSettings = DEFAULT_SETTINGS;
  statusBar: HTMLElement | null = null;
  private ws: WebSocket | null = null;
  private wsReconnectTimer: number | null = null;
  private unloaded = false;

  async onload() {
    await this.loadSettings();
    this.addSettingTab(new BlackboxSettingTab(this.app, this));

    this.statusBar = this.addStatusBarItem();
    this.statusBar.setText("BB …");
    this.refreshStatus();
    // 30s poll stays as the heartbeat; the WS stream adds live transitions.
    this.registerInterval(
      window.setInterval(() => this.refreshStatus(), 30_000)
    );
    this.connectStatusStream();

    this.addCommand({
      id: "summarize-active-note",
      name: "Summarize active note",
      callback: () => this.runSkillOnActiveNote("summarize_note"),
    });
    this.addCommand({
      id: "triage-active-note",
      name: "Triage active note",
      callback: () => this.runSkillOnActiveNote("inbox_triage"),
    });
    this.addCommand({
      id: "run-skill-on-active-note",
      name: "Run skill on active note…",
      callback: () => this.openSkillPicker(),
    });
    this.addCommand({
      id: "review-approvals",
      name: "Review pending approvals",
      callback: () => this.openApprovals(),
    });
    this.addCommand({
      id: "approve-all-pending",
      name: "Approve all pending",
      callback: () => this.resolveAllPending(true),
    });
    this.addCommand({
      id: "reject-all-pending",
      name: "Reject all pending",
      callback: () => this.resolveAllPending(false),
    });
  }

  async resolveAllPending(approved: boolean) {
    try {
      const data = await this.apiGet("/api/v1/skills/pending");
      const items: PendingApproval[] = data.pending ?? [];
      if (items.length === 0) {
        new Notice("BLACKBOX: no pending approvals.");
        return;
      }
      const verb = approved ? "Approving" : "Rejecting";
      new Notice(`BLACKBOX: ${verb} ${items.length} pending…`);
      const result = await this.apiPost("/api/v1/skills/approve/batch", {
        thread_ids: items.map((i) => i.thread_id),
        approved,
      });
      new Notice(
        `BLACKBOX ${approved ? "✓" : "✗"} ${result.resolved}/${result.requested} resolved.`,
        8000
      );
    } catch (err) {
      new Notice(`BLACKBOX error: ${err}`, 8000);
    }
    this.refreshStatus();
  }

  async openSkillPicker() {
    try {
      const data = await this.apiGet("/api/v1/skills/");
      const skills: SkillInfo[] = (data.skills ?? []).map((s: SkillInfo) => ({
        ...s,
        id: s.id || s.name || "",
      }));
      if (skills.length === 0) {
        new Notice("BLACKBOX: no skills registered.");
        return;
      }
      new SkillPicker(this.app, this, skills).open();
    } catch (err) {
      new Notice(`BLACKBOX error: ${err}`, 8000);
    }
  }

  // ------------------------------------------------------------------ api

  private headers(): Record<string, string> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (this.settings.apiKey) headers["X-API-Key"] = this.settings.apiKey;
    return headers;
  }

  async apiGet(path: string): Promise<any> {
    const res = await requestUrl({
      url: `${this.settings.orchestratorUrl}${path}`,
      headers: this.headers(),
      throw: false,
    });
    if (res.status >= 400) throw new Error(`HTTP ${res.status}: ${res.text}`);
    return res.json;
  }

  async apiPost(path: string, body: unknown): Promise<any> {
    const res = await requestUrl({
      url: `${this.settings.orchestratorUrl}${path}`,
      method: "POST",
      headers: this.headers(),
      body: JSON.stringify(body),
      throw: false,
    });
    if (res.status >= 400) throw new Error(`HTTP ${res.status}: ${res.text}`);
    return res.json;
  }

  // ----------------------------------------------------------- live stream

  private wsUrl(): string {
    const base = this.settings.orchestratorUrl.replace(/^http/, "ws");
    const url = `${base}/ws/global`;
    return this.settings.apiKey
      ? `${url}?token=${encodeURIComponent(this.settings.apiKey)}`
      : url;
  }

  /**
   * Subscribe to the orchestrator's global event feed so the status bar
   * reflects runs live — including autonomous and dashboard-started ones,
   * not just runs launched from this plugin. Additive to the 30s poll.
   */
  connectStatusStream() {
    if (this.unloaded) return;
    let ws: WebSocket;
    try {
      ws = new WebSocket(this.wsUrl());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.ws = ws;
    ws.onopen = () => this.refreshStatus();
    ws.onmessage = (ev) => this.onStreamEvent(ev);
    ws.onclose = () => {
      this.ws = null;
      this.scheduleReconnect();
    };
  }

  reconnectStatusStream() {
    if (this.wsReconnectTimer !== null) {
      window.clearTimeout(this.wsReconnectTimer);
      this.wsReconnectTimer = null;
    }
    this.ws?.close();
    this.connectStatusStream();
  }

  private scheduleReconnect() {
    if (this.unloaded || this.wsReconnectTimer !== null) return;
    this.wsReconnectTimer = window.setTimeout(() => {
      this.wsReconnectTimer = null;
      this.connectStatusStream();
    }, 5_000);
  }

  private onStreamEvent(ev: MessageEvent) {
    let data: { type?: string; skill?: string };
    try {
      data = JSON.parse(ev.data);
    } catch {
      return;
    }
    // Lifecycle only — the global feed also carries token/node_update noise.
    switch (data.type) {
      case "execution_started":
        this.statusBar?.setText(`BB ⚙ ${data.skill ?? "run"}…`);
        break;
      case "execution_completed":
      case "execution_failed":
      case "execution_terminated":
      case "approval_required":
        this.refreshStatus();
        break;
    }
  }

  onunload() {
    this.unloaded = true;
    if (this.wsReconnectTimer !== null) {
      window.clearTimeout(this.wsReconnectTimer);
      this.wsReconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  // --------------------------------------------------------------- status

  async refreshStatus() {
    if (!this.statusBar) return;
    try {
      const health = await this.apiGet("/api/v1/health");
      const pending = await this.apiGet("/api/v1/skills/pending").catch(() => null);
      const count = pending?.pending?.length ?? 0;
      const suffix = count > 0 ? ` · ${count} pending` : "";
      if (health.status === "ok") {
        this.statusBar.setText(`BB ● ${health.modes?.llm ?? "ok"}${suffix}`);
      } else if (health.status === "degraded") {
        this.statusBar.setText(`BB ▲ degraded${suffix}`);
      } else {
        this.statusBar.setText(`BB ○ ${health.status}${suffix}`);
      }
    } catch {
      this.statusBar.setText("BB ⏻ offline");
    }
  }

  // ---------------------------------------------------------------- skills

  async runSkillOnActiveNote(skill: string) {
    const file = this.app.workspace.getActiveFile();
    if (!file || file.extension !== "md") {
      new Notice("BLACKBOX: open a markdown note first.");
      return;
    }
    new Notice(`BLACKBOX: running ${skill} on ${file.path}…`);
    this.statusBar?.setText(`BB ⚙ ${skill}…`);
    try {
      const result = await this.apiPost("/api/v1/skills/execute", {
        skill_name: skill,
        user_input: file.path,
        session_id: "obsidian-plugin",
      });
      const thread = result.thread_id ? ` (thread ${result.thread_id.slice(0, 8)})` : "";
      if (result.status === "completed" || result.status === "approved") {
        const archive = result.archive_path
          ? String(result.archive_path).split(/[\\/]/).pop()
          : "done";
        new Notice(`BLACKBOX ✓ 30-Archive/${archive}${thread}`, 8000);
      } else if (result.status === "waiting_for_input") {
        new Notice(
          `BLACKBOX ⚠ approval required${thread} — run 'Review pending approvals'.`,
          8000
        );
      } else {
        new Notice(`BLACKBOX ✗ ${result.status}${thread}: ${result.error ?? ""}`, 8000);
      }
    } catch (err) {
      new Notice(`BLACKBOX error: ${err}`, 8000);
    }
    this.refreshStatus();
  }

  // ------------------------------------------------------------- approvals

  async openApprovals() {
    try {
      const data = await this.apiGet("/api/v1/skills/pending");
      const items: PendingApproval[] = data.pending ?? [];
      if (items.length === 0) {
        new Notice("BLACKBOX: no pending approvals.");
        return;
      }
      new ApprovalPicker(this.app, this, items).open();
    } catch (err) {
      new Notice(`BLACKBOX error: ${err}`, 8000);
    }
  }

  async resolveApproval(threadId: string, approved: boolean) {
    try {
      const result = await this.apiPost("/api/v1/skills/approve", {
        thread_id: threadId,
        approved,
      });
      new Notice(
        approved
          ? `BLACKBOX ✓ approved — ${result.archive_path ?? result.status}`
          : "BLACKBOX ✗ rejected.",
        8000
      );
    } catch (err) {
      new Notice(`BLACKBOX error: ${err}`, 8000);
    }
    this.refreshStatus();
  }

  // ---------------------------------------------------------------- config

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}

class SkillPicker extends SuggestModal<SkillInfo> {
  constructor(
    app: App,
    private plugin: BlackboxPlugin,
    private skills: SkillInfo[]
  ) {
    super(app);
    this.setPlaceholder("Run a BLACKBOX skill on the active note");
  }

  getSuggestions(query: string): SkillInfo[] {
    const q = query.toLowerCase();
    return this.skills.filter(
      (s) =>
        s.id.toLowerCase().includes(q) ||
        (s.display_name ?? "").toLowerCase().includes(q)
    );
  }

  renderSuggestion(skill: SkillInfo, el: HTMLElement) {
    el.createEl("div", { text: skill.display_name || skill.id });
    if (skill.description) {
      el.createEl("small", { text: skill.description });
    }
  }

  onChooseSuggestion(skill: SkillInfo) {
    void this.plugin.runSkillOnActiveNote(skill.id);
  }
}

class ApprovalPicker extends SuggestModal<PendingApproval> {
  constructor(
    app: App,
    private plugin: BlackboxPlugin,
    private items: PendingApproval[]
  ) {
    super(app);
    this.setPlaceholder("Pending approvals — pick one to review");
  }

  getSuggestions(query: string): PendingApproval[] {
    const q = query.toLowerCase();
    return this.items.filter(
      (i) =>
        i.skill_name.toLowerCase().includes(q) || i.thread_id.startsWith(q)
    );
  }

  renderSuggestion(item: PendingApproval, el: HTMLElement) {
    el.createEl("div", { text: `${item.skill_name}` });
    el.createEl("small", {
      text: `confidence ${(item.confidence * 100).toFixed(0)}% · ${item.thread_id.slice(0, 8)}`,
    });
  }

  onChooseSuggestion(item: PendingApproval) {
    new ApprovalReview(this.app, this.plugin, item).open();
  }
}

class ApprovalReview extends Modal {
  constructor(
    app: App,
    private plugin: BlackboxPlugin,
    private item: PendingApproval
  ) {
    super(app);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h2", { text: `Approve: ${this.item.skill_name}` });
    contentEl.createEl("p", {
      text: `Confidence ${(this.item.confidence * 100).toFixed(0)}% · thread ${this.item.thread_id.slice(0, 8)}`,
    });
    const pre = contentEl.createEl("pre");
    pre.setText(this.item.draft || "(no draft captured)");
    pre.style.maxHeight = "40vh";
    pre.style.overflow = "auto";
    pre.style.whiteSpace = "pre-wrap";

    const buttons = contentEl.createDiv();
    buttons.style.display = "flex";
    buttons.style.gap = "8px";
    buttons.style.marginTop = "12px";

    const approve = buttons.createEl("button", { text: "Approve" });
    approve.addClass("mod-cta");
    approve.onclick = async () => {
      this.close();
      await this.plugin.resolveApproval(this.item.thread_id, true);
    };
    const reject = buttons.createEl("button", { text: "Reject" });
    reject.addClass("mod-warning");
    reject.onclick = async () => {
      this.close();
      await this.plugin.resolveApproval(this.item.thread_id, false);
    };
    buttons.createEl("button", { text: "Cancel" }).onclick = () => this.close();
  }

  onClose() {
    this.contentEl.empty();
  }
}

class BlackboxSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: BlackboxPlugin) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Orchestrator URL")
      .setDesc("The local BLACKBOX orchestrator (blackbox start).")
      .addText((text) =>
        text
          .setPlaceholder("http://127.0.0.1:8000")
          .setValue(this.plugin.settings.orchestratorUrl)
          .onChange(async (value) => {
            this.plugin.settings.orchestratorUrl = value.replace(/\/+$/, "");
            await this.plugin.saveSettings();
            this.plugin.reconnectStatusStream();
          })
      );

    new Setting(containerEl)
      .setName("API key")
      .setDesc("Matches BLACKBOX_API_KEY in the orchestrator .env (leave empty for open local dev).")
      .addText((text) =>
        text
          .setValue(this.plugin.settings.apiKey)
          .onChange(async (value) => {
            this.plugin.settings.apiKey = value.trim();
            await this.plugin.saveSettings();
            this.plugin.reconnectStatusStream();
          })
      );
  }
}
