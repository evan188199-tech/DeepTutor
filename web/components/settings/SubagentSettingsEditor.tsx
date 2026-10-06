"use client";

import { useSettings } from "@/features/settings/store/SettingsStore";
import { useStagedSettings } from "@/features/settings/store/useStagedSettings";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, RefreshCw, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  SettingRow,
  SettingSection,
  SettingsPageHeader,
  selectClass,
  inputClass,
} from "@/components/settings/shared";
import { Toggle } from "@/components/settings/Toggle";
import { agentGlyph } from "@/components/agents/agent-icons";
import {
  getBackendOptions,
  getSubagentSettings,
  syncBackendOptions,
  type SubagentBackendConfig,
  type SubagentBackendOptions,
} from "@/lib/subagents-api";

/** Empty model/effort means "let the selected runtime decide". */
const CUSTOM = "__custom__";

// Defaults mirror BackendConfig in deeptutor/services/subagent/config.py so the
// form shows the same starting state the backend would synthesize.
const DEFAULTS: Required<
  Pick<
    SubagentBackendConfig,
    | "enabled"
    | "model"
    | "effort"
    | "system_prompt"
    | "permission_mode"
    | "sandbox"
    | "approval"
    | "network_access"
    | "ephemeral"
    | "auto_approve"
    | "thinking"
    | "forward_images"
  >
> = {
  enabled: true,
  model: "",
  effort: "",
  system_prompt: "",
  permission_mode: "bypassPermissions",
  sandbox: "workspace-write",
  approval: "never",
  network_access: false,
  ephemeral: false,
  auto_approve: true,
  thinking: true,
  forward_images: false,
};

/**
 * Which knobs each backend kind actually honors — the editor renders from this
 * table instead of per-kind branches. Mirrors what the Python backend reads:
 * e.g. Claude Code / Antigravity / Grok use `permission_mode`, only Codex has its
 * sandbox family, kimi/hermes/opencode/mimo take the `auto_approve` switch.
 */
type KindFeatures = {
  effort: boolean;
  systemPrompt: boolean;
  permissionMode: boolean;
  codexSandbox: boolean;
  autoApprove: boolean;
  thinking: boolean;
  forwardImages: boolean;
};

const KIND_FEATURES: Record<string, KindFeatures> = {
  claude_code: {
    effort: true,
    systemPrompt: true,
    permissionMode: true,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: true,
  },
  codex: {
    effort: true,
    systemPrompt: false,
    permissionMode: false,
    codexSandbox: true,
    autoApprove: false,
    thinking: false,
    forwardImages: true,
  },
  grok: {
    effort: true,
    systemPrompt: true,
    permissionMode: true,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: false,
  },
  antigravity: {
    effort: true, // --effort low|medium|high
    systemPrompt: true,
    permissionMode: true, // permissive modes map onto --dangerously-skip-permissions
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    // Headless `agy` documents no attachment flag; images are named as paths
    // in the prompt for the agent's own file-reading tools instead.
    forwardImages: false,
  },
  kimi: {
    effort: false,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true, // --yolo
    thinking: true, // --thinking / --no-thinking
    forwardImages: false, // no headless image input
  },
  opencode: {
    effort: true, // --variant
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true, // permission.asked replies
    thinking: false, // the event bus always streams reasoning
    forwardImages: true, // file parts on the server API
  },
  mimo: {
    effort: true,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true,
    thinking: false,
    forwardImages: true,
  },
  hermes: {
    effort: true,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true, // --yolo
    thinking: false,
    forwardImages: true, // --image
  },
  hermes_remote: {
    effort: true,
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: true,
    thinking: false,
    forwardImages: false,
  },
  openclaw: {
    effort: true, // --thinking
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: true, // local paths are named in the prompt
  },
  deepseek_harness: {
    effort: true, // SDK reasoning_effort
    systemPrompt: true,
    permissionMode: false,
    codexSandbox: false,
    autoApprove: false,
    thinking: false,
    forwardImages: true, // local paths are named in the prompt
  },
};

const FALLBACK_FEATURES: KindFeatures = KIND_FEATURES.claude_code;

const DISPLAY_NAMES: Record<string, string> = {
  claude_code: "Claude Code",
  codex: "Codex",
  grok: "Grok CLI",
  kimi: "Kimi CLI",
  opencode: "opencode",
  mimo: "MiMo Code",
  hermes: "Hermes Agent",
  hermes_remote: "Hermes Agent (remote)",
  openclaw: "OpenClaw",
  deepseek_harness: "DeepSeek Harness",
};

// Per-kind flavor for the system-prompt section: how the instruction reaches
// the agent (a real flag, a native prompt field, or a first-message prefix).
const SYSTEM_PROMPT_HINT: Record<string, string> = {
  grok: "Additional teaching or delegation instructions are passed through Grok CLI's rules option.",
  claude_code: "Appended to the agent's system prompt (--append-system-prompt).",
  kimi: "Kimi CLI has no system-prompt flag — the instruction is prefixed to each new session's first message.",
  opencode: "Injected into each new session via the server API's system field.",
  mimo: "Injected into each new session via the server API's system field.",
  hermes: "Hermes has no system-prompt flag — the instruction is prefixed to each new session's first message.",
  hermes_remote: "Sent through the Hermes gateway API's instructions field for a fresh or expired session.",
  openclaw: "The instruction is prefixed to the first message for each new OpenClaw session key.",
  deepseek_harness: "The instruction is prefixed to the first message in each new DeepSeek Harness session.",
};

const PERMISSION_MODES: { value: string; label: string }[] = [
  {
    value: "bypassPermissions",
    label: "Bypass permissions · autonomous (recommended)",
  },
  {
    value: "acceptEdits",
    label: "Accept edits automatically",
  },
  {
    value: "default",
    label: "Default · may wait for prompts",
  },
  {
    value: "plan",
    label: "Plan mode · read-only",
  },
];

const GROK_PERMISSION_MODES: { value: string; label: string }[] = [
  {
    value: "dontAsk",
    label: "Don't ask · deny approval requests (default)",
  },
  {
    value: "plan",
    label: "Plan (compatibility mode)",
  },
  {
    value: "default",
    label: "Default permissions",
  },
  {
    value: "acceptEdits",
    label: "Accept edits automatically",
  },
  {
    value: "auto",
    label: "Automatically evaluate permissions",
  },
  {
    value: "bypassPermissions",
    label: "Bypass permissions",
  },
];

function defaultsForKind(kind: string): typeof DEFAULTS {
  return kind === "grok"
    ? { ...DEFAULTS, permission_mode: "dontAsk" }
    : DEFAULTS;
}

const SANDBOXES: { value: string; label: string }[] = [
  { value: "read-only", label: "Read-only" },
  {
    value: "workspace-write",
    label: "Workspace write (recommended)",
  },
  { value: "danger-full-access", label: "Full access" },
  {
    value: "bypass",
    label: "Bypass sandbox & approvals",
  },
];

const APPROVALS: { value: string; label: string }[] = [
  {
    value: "never",
    label: "Never ask (recommended)",
  },
  { value: "on-failure", label: "On failure" },
  { value: "on-request", label: "On request" },
  {
    value: "untrusted",
    label: "Untrusted commands",
  },
];

export function SubagentSettingsEditor({ kind }: { kind: string }) {
  const { t, i18n } = useTranslation();
  const zh = i18n.language?.toLowerCase().startsWith("zh");

  const [options, setOptions] = useState<SubagentBackendOptions | null>(null);
  const [liveConfig, setLiveConfig] = useState<SubagentBackendConfig>({
    ...defaultsForKind(kind),
  });
  const [config, setConfig] = useStagedSettings(`subagent:${kind}`, liveConfig, setLiveConfig);
  const [customModel, setCustomModel] = useState(false);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const { applying: busy, draftRevision } = useSettings();
  const [error, setError] = useState<string | null>(null);

  const Glyph = agentGlyph(kind);

  const fetchOptions = useCallback(async () => {
    const all = await getBackendOptions();
    return all.find((o) => o.kind === kind) ?? null;
  }, [kind]);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [opts, settings] = await Promise.all([
        fetchOptions(),
        // An editor must show what is stored, never a cached copy.
        getSubagentSettings({ force: true }),
      ]);
      setOptions(opts);
      const stored = settings.backends?.[kind] ?? {};
      setLiveConfig({ ...defaultsForKind(kind), ...stored });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [fetchOptions, kind]);

  useEffect(() => {
    void load();
  }, [load, draftRevision]);

  const sync = useCallback(async () => {
    setSyncing(true);
    setError(null);
    try {
      // Actively re-pull this backend's catalog (CC scrapes /model live).
      setOptions(await syncBackendOptions(kind));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }, [kind]);

  const save = useCallback(async (patch: Partial<SubagentBackendConfig>) => {
    setConfig((prev) => ({ ...prev, ...patch }));
  }, [setConfig]);

  const features = KIND_FEATURES[kind] ?? FALLBACK_FEATURES;
  const isRemote = kind === "hermes_remote";
  const isGrok = kind === "grok";
  const permissionModes = isGrok ? GROK_PERMISSION_MODES : PERMISSION_MODES;
  const knownSlugs = useMemo(
    () => new Set((options?.models ?? []).map((m) => m.slug)),
    [options],
  );
  const showCustomModel =
    customModel || (config.model !== "" && !knownSlugs.has(config.model ?? ""));

  // Effort choices: per-model when the catalog carries each model's levels
  // (Codex, opencode family), else the backend's union (Claude Code). Falls
  // back to the union when the chosen model isn't a known slug.
  const effortChoices = useMemo(() => {
    if (config.model && knownSlugs.has(config.model)) {
      const m = options?.models.find((x) => x.slug === config.model);
      if (m?.efforts?.length) return m.efforts;
    }
    return options?.efforts ?? [];
  }, [config.model, knownSlugs, options]);

  const onModelSelect = useCallback(
    (value: string) => {
      if (value === CUSTOM) {
        setCustomModel(true);
        return;
      }
      setCustomModel(false);
      // Reset an effort the newly chosen model doesn't support.
      const m = options?.models.find((x) => x.slug === value);
      const patch: Partial<SubagentBackendConfig> = { model: value };
      if (
        config.effort &&
        m?.efforts?.length &&
        !m.efforts.includes(config.effort)
      ) {
        patch.effort = "";
      }
      void save(patch);
    },
    [options, config.effort, save],
  );

  const displayName = options?.display_name ?? DISPLAY_NAMES[kind] ?? kind;

  return (
    <div>
      <SettingsPageHeader
        title={displayName}
        description={
          isRemote
            ? t("Configure the remote Hermes gateway, model, and run parameters DeepTutor uses over HTTP.")
            : t(
                "Model, reasoning effort, and run parameters DeepTutor drives the local {{name}} with when consulting it. These override the CLI defaults; leave blank to keep the CLI's own default.",
                { name: displayName },
              )
        }
      />

      {loading && (
        <div className="flex items-center gap-2 text-[13px] text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t("Loading…")}
        </div>
      )}

      {!loading && error && (
        <div className="mb-5 rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-[13px] text-red-600 dark:text-red-300">
          {error}
        </div>
      )}

      {!loading && options && (
        <>
          {/* Availability + sync. The model/effort lists change over time, so
              the user can re-pull them on demand. */}
          <SettingSection
            title={t("Connection & sync")}
            description={
              isRemote
                ? t("Check connectivity and authentication for the configured gateway.")
                : isGrok
                  ? t("Detect Grok CLI in the backend environment. Leave model and reasoning effort blank for CLI defaults, or enter them manually.")
                  : t("Vendors add and retire models and effort levels over time — sync any time to re-pull the latest lists.")
            }
          >
            <SettingRow
              title={
                isRemote
                  ? t("Gateway status")
                  : t("On this machine")
              }
              description={
                options.available
                  ? options.version
                  : options.detail ||
                    t("CLI not found on PATH.")
              }
              control={
                <span
                  className={`inline-flex items-center gap-1.5 text-[12px] ${
                    options.available
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-amber-600 dark:text-amber-400"
                  }`}
                >
                  {Glyph ? <Glyph size={15} /> : null}
                  {options.available ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5" />
                  )}
                  {options.available
                    ? isRemote
                      ? t("Reachable")
                      : t("Installed")
                    : isRemote
                      ? t("Unavailable")
                      : t("Not detected")}
                </span>
              }
            />
            <SettingRow
              title={t("Model list")}
              description={
                isGrok
                  ? t("No model catalog is assumed. Enter a model supported by your Grok CLI; sync only detects the CLI again.")
                  : options.synced_at
                    ? t("Last synced: {{ts}}", {
                        ts: formatTs(options.synced_at, zh),
                      })
                    : isRemote
                      ? t("The remote gateway does not currently enumerate models here; use its default or enter a model name manually.")
                      : t("This CLI has no model-list API; below are the common aliases, and any model name is accepted.")
              }
              control={
                isRemote ? (
                  <span className="text-[12px] text-[var(--muted-foreground)]">
                    {t("Gateway models are server-managed")}
                  </span>
                ) : (
                  <button
                    type="button"
                    disabled={syncing}
                    onClick={() => void sync()}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[12px] font-medium text-[var(--foreground)] transition-colors hover:border-[var(--foreground)]/40 disabled:opacity-60"
                  >
                    <RefreshCw
                      className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`}
                    />
                    {t("Sync")}
                  </button>
                )
              }
            />
          </SettingSection>

          {isRemote && (
            <SettingSection
              title={t("Remote gateway")}
              description={t("The bearer is read only from the environment; this stores the variable name, never the secret.")}
            >
              <SettingRow
                title={t("Gateway URL")}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    value={config.base_url ?? ""}
                    placeholder={t("e.g. http://hermes-uni:8642")}
                    onChange={(e) => setConfig((p) => ({ ...p, base_url: e.target.value }))}
                    onBlur={(e) => void save({ base_url: e.target.value.trim() })}
                  />
                }
              />
              <SettingRow
                title={t("API key environment variable")}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    value={config.api_key_env ?? "DEEPTUTOR_HERMES_REMOTE_API_KEY"}
                    onChange={(e) => setConfig((p) => ({ ...p, api_key_env: e.target.value }))}
                    onBlur={(e) => void save({ api_key_env: e.target.value.trim() })}
                  />
                }
              />
              <SettingRow
                title={t("Profile label")}
                description={t("Informational deployment label; it never stores a key.")}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    value={config.profile ?? ""}
                    onChange={(e) => setConfig((p) => ({ ...p, profile: e.target.value }))}
                    onBlur={(e) => void save({ profile: e.target.value.trim() })}
                  />
                }
              />
              <SettingRow
                title={t("Idle timeout (seconds)")}
                control={
                  <input
                    className={`${inputClass} w-[260px]`}
                    disabled={busy}
                    type="number"
                    min={1}
                    max={86400}
                    value={config.idle_timeout_seconds ?? 600}
                    onChange={(e) =>
                      setConfig((p) => ({
                        ...p,
                        idle_timeout_seconds: Number.parseInt(e.target.value, 10),
                      }))
                    }
                    onBlur={(e) =>
                      void save({ idle_timeout_seconds: Number.parseInt(e.target.value, 10) })
                    }
                  />
                }
              />
            </SettingSection>
          )}

          <SettingSection
            title={t("Model")}
            description={t("The model and reasoning effort DeepTutor consults this agent with.")}
          >
            <SettingRow
              title={t("Enabled")}
              description={t("When off, DeepTutor won't consult this agent in chat.")}
              control={
                <Toggle
                  checked={config.enabled !== false}
                  disabled={busy}
                  onChange={(v) => void save({ enabled: v })}
                />
              }
            />
            <SettingRow
              title={t("Model")}
              control={
                <div className="flex w-[260px] flex-col items-end gap-2">
                  <select
                    aria-label={t("Model")}
                    className={selectClass}
                    disabled={busy}
                    value={showCustomModel ? CUSTOM : (config.model ?? "")}
                    onChange={(e) => onModelSelect(e.target.value)}
                  >
                    <option value="">
                      {isRemote
                        ? t("Gateway default")
                        : t("CLI default")}
                    </option>
                    {options.models.map((m) => (
                      <option key={m.slug} value={m.slug}>
                        {m.display_name}
                      </option>
                    ))}
                    {options.allow_custom_model && (
                      <option value={CUSTOM}>
                        {t("Custom…")}
                      </option>
                    )}
                  </select>
                  {showCustomModel && (
                    <input
                      aria-label={t("Custom model")}
                      className={inputClass}
                      disabled={busy}
                      placeholder={t("Enter a model name")}
                      value={config.model ?? ""}
                      onChange={(e) =>
                        setConfig((p) => ({ ...p, model: e.target.value }))
                      }
                      onBlur={(e) =>
                        void save({ model: e.target.value.trim() })
                      }
                    />
                  )}
                </div>
              }
            />
            {features.effort && (
              <SettingRow
                title={t("Reasoning effort")}
                control={
                  isGrok ? (
                    <input
                      aria-label={t("Reasoning effort")}
                      className={`${inputClass} w-[260px]`}
                      disabled={busy}
                      placeholder={t("Blank uses CLI default")}
                      value={config.effort ?? ""}
                      onChange={(e) =>
                        setConfig((p) => ({ ...p, effort: e.target.value }))
                      }
                      onBlur={(e) =>
                        void save({ effort: e.target.value.trim() })
                      }
                    />
                  ) : (
                    <select
                      className={`${selectClass} w-[260px]`}
                      disabled={busy || effortChoices.length === 0}
                      value={config.effort ?? ""}
                      onChange={(e) => void save({ effort: e.target.value })}
                    >
                      <option value="">
                        {isRemote
                          ? t("Gateway default")
                          : t("CLI default")}
                      </option>
                      {effortChoices.map((eff) => (
                        <option key={eff} value={eff}>
                          {eff}
                        </option>
                      ))}
                    </select>
                  )
                }
              />
            )}
          </SettingSection>

          {features.systemPrompt && (
            <SettingSection
              title={t("System prompt")}
              description={`${t(
                SYSTEM_PROMPT_HINT[kind] ?? SYSTEM_PROMPT_HINT.claude_code,
              )} ${t("Blank uses DeepTutor's default delegate instruction.")}`}
            >
              <div className="py-4">
                <textarea
                  aria-label={t("System prompt")}
                  className={`${inputClass} min-h-[96px] resize-y leading-relaxed`}
                  disabled={busy}
                  placeholder={t("(blank uses the default delegate instruction)")}
                  value={config.system_prompt ?? ""}
                  onChange={(e) =>
                    setConfig((p) => ({ ...p, system_prompt: e.target.value }))
                  }
                  onBlur={(e) => void save({ system_prompt: e.target.value })}
                />
              </div>
            </SettingSection>
          )}

          <SettingSection
            title={t("Run parameters")}
            description={t("DeepTutor drives the agent unattended — the defaults ensure it never stalls waiting for an approval prompt.")}
          >
            {features.permissionMode && (
              <SettingRow
                title={t("Permission mode")}
                description={
                  isGrok
                    ? t("The default dontAsk mode denies operations that need approval. Other modes follow Grok CLI permissions; unattended runs cannot answer interactive prompts.")
                    : t("Modes other than bypass may stall an unattended run waiting for a prompt.")
                }
                control={
                  <select
                    aria-label={t("Permission mode")}
                    className={`${selectClass} w-[260px]`}
                    disabled={busy}
                    value={
                      config.permission_mode ??
                      defaultsForKind(kind).permission_mode
                    }
                    onChange={(e) =>
                      void save({ permission_mode: e.target.value })
                    }
                  >
                    {permissionModes.map((o) => (
                      <option key={o.value} value={o.value}>
                        {t(o.label)}
                      </option>
                    ))}
                  </select>
                }
              />
            )}

            {features.autoApprove && (
              <SettingRow
                title={t("Auto-approve")}
                description={t("Approve the agent's permission asks automatically. When off they are rejected — an unattended run can't confirm interactively.")}
                control={
                  <Toggle
                    checked={config.auto_approve !== false}
                    disabled={busy}
                    onChange={(v) => void save({ auto_approve: v })}
                  />
                }
              />
            )}

            {features.thinking && (
              <SettingRow
                title={t("Thinking")}
                description={t("Stream the model's thinking (--thinking).")}
                control={
                  <Toggle
                    checked={config.thinking !== false}
                    disabled={busy}
                    onChange={(v) => void save({ thinking: v })}
                  />
                }
              />
            )}

            {features.codexSandbox && (
              <>
                <SettingRow
                  title={t("Sandbox")}
                  control={
                    <select
                      className={`${selectClass} w-[260px]`}
                      disabled={busy}
                      value={config.sandbox ?? DEFAULTS.sandbox}
                      onChange={(e) => void save({ sandbox: e.target.value })}
                    >
                      {SANDBOXES.map((o) => (
                        <option key={o.value} value={o.value}>
                          {t(o.label)}
                        </option>
                      ))}
                    </select>
                  }
                />
                <SettingRow
                  title={t("Approval policy")}
                  description={t("Anything but never may stall an unattended run.")}
                  control={
                    <select
                      className={`${selectClass} w-[260px]`}
                      disabled={busy}
                      value={config.approval ?? DEFAULTS.approval}
                      onChange={(e) => void save({ approval: e.target.value })}
                    >
                      {APPROVALS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {t(o.label)}
                        </option>
                      ))}
                    </select>
                  }
                />
                <SettingRow
                  title={t("Command network access")}
                  description={t("Let the model's shell commands reach the network (workspace-write is offline by default). The built-in web search is unaffected.")}
                  control={
                    <Toggle
                      checked={Boolean(config.network_access)}
                      disabled={busy}
                      onChange={(v) => void save({ network_access: v })}
                    />
                  }
                />
                <SettingRow
                  title={t("Ephemeral session")}
                  description={t("Don't persist the session under ~/.codex/sessions.")}
                  control={
                    <Toggle
                      checked={Boolean(config.ephemeral)}
                      disabled={busy}
                      onChange={(v) => void save({ ephemeral: v })}
                    />
                  }
                />
              </>
            )}

            {features.forwardImages && (
              <SettingRow
                title={t("Forward images")}
                description={t("Let DeepTutor forward image attachments from the chat turn to this agent.")}
                control={
                  <Toggle
                    checked={Boolean(config.forward_images)}
                    disabled={busy}
                    onChange={(v) => void save({ forward_images: v })}
                  />
                }
              />
            )}
          </SettingSection>
        </>
      )}
    </div>
  );
}

function formatTs(value: string, zh: boolean): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(zh ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export default SubagentSettingsEditor;
