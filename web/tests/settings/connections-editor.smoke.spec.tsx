/**
 * Zero-coverage smoke tests for the connections editor component layer:
 *   - components/settings/ConnectionsEditor.tsx (permission gates, empty
 *     states, masked keys, add/edit/delete flows, service linking, toasts)
 *
 * Origin: web/evidence/web-test-gaps-20261007/summary.json zero list
 * (AGEN-1192). Scope is the editor component mounted inside the real
 * SettingsProvider so the draft mutations (addConnection, update,
 * remove, linkConnectionToServices) run for real; every network access
 * goes through the mocked `@/lib/api` and ProviderModelDiscovery is
 * stubbed (its own probe panel is exercised elsewhere).
 *
 * Note: named `*.smoke.spec.tsx` (not `.test.tsx`) because the vitest
 * include globs only pick up spec files — same convention as
 * tests/memory/memory-section.smoke.spec.tsx.
 */
import { useEffect } from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  SettingsProvider,
  defaultCatalog,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { ConnectionsEditor } from "@/components/settings/ConnectionsEditor";
import type {
  Catalog,
  CatalogConnection,
  ConnectionTarget,
} from "@/lib/model-catalog-types";

const mocks = vi.hoisted(() => ({
  fetch: vi.fn(),
  language: "en",
}));

vi.mock("@/lib/api", () => ({
  apiUrl: (url: string) => url,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const t = (key: string, opts?: Record<string, unknown>) =>
  opts
    ? key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
        String(opts[name] ?? ""),
      )
    : key;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t,
    i18n: { language: mocks.language },
  }),
}));

vi.mock("@/lib/theme", () => ({ setTheme: vi.fn() }));

vi.mock("@/context/AppShellContext", () => ({
  useAppShell: () => ({
    codeBlockTheme: "github",
    codeBlockShowLineNumbers: false,
    codeBlockWrapLongLines: false,
  }),
}));

vi.mock("@/lib/llm-options", () => ({
  invalidateLLMOptionsCache: vi.fn(),
  listLLMOptions: vi.fn(async () => ({ active: null, options: [] })),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...props
  }: {
    children?: React.ReactNode;
    href: string;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/settings/ProviderModelDiscovery", async () => {
  const React = await import("react");
  return {
    ProviderModelDiscovery: (props: { input: Record<string, unknown> }) =>
      React.createElement("div", {
        "data-testid": "discovery-stub",
        "data-input": JSON.stringify(props.input),
      }),
  };
});

// ── Fixtures ─────────────────────────────────────────────────────────

const TARGETS: ConnectionTarget[] = [
  {
    provider: "openai",
    label: "OpenAI",
    default_base_url: "https://api.openai.example/v1",
    services: {
      llm: {
        provider: "openai",
        base_url: "https://api.openai.example/v1",
        default_model: "gpt-4o-mini",
      },
      embedding: {
        provider: "openai",
        base_url: "https://api.openai.example/v1",
        default_model: "text-embedding-3-small",
        default_dim: "1536",
      },
      imagegen: {
        provider: "openai",
        base_url: "https://api.openai.example/v1",
        default_model: "gpt-image-1",
      },
    },
  },
  {
    provider: "siliconflow",
    label: "SiliconFlow",
    default_base_url: "https://api.siliconflow.example/v1",
    services: {
      llm: {
        provider: "openai",
        base_url: "https://api.siliconflow.example/v1",
        default_model: "deepseek-ai/DeepSeek-V3",
      },
      tts: {
        provider: "fishaudio",
        base_url: "https://api.siliconflow.example/v1",
        default_model: "FunAudioLLM/CosyVoice2-0.5B",
      },
      stt: {
        provider: "openai",
        base_url: "https://api.siliconflow.example/v1",
        default_model: "FunAudioLLM/SenseVoiceSmall",
      },
    },
  },
];

const CONN_PRIMARY: CatalogConnection = {
  id: "conn-primary",
  name: "Primary",
  provider: "openai",
  api_key: "***",
  base_url: "https://api.openai.example/v1",
  api_version: "",
  extra_headers: {},
};

const CONN_AUX: CatalogConnection = {
  id: "conn-aux",
  name: "Aux",
  provider: "siliconflow",
  api_key: "sk12345678",
  base_url: "",
  api_version: "",
};

const CONN_LONG: CatalogConnection = {
  id: "conn-long",
  name: "Longkey",
  provider: "vertex",
  api_key: "sk-abcdefghijklmnop1234",
  base_url: "",
  api_version: "",
};

const CONN_KEYLESS: CatalogConnection = {
  id: "conn-keyless",
  name: "Keyless",
  provider: "vertex",
  api_key: "",
  base_url: "",
  api_version: "",
};

const LINKED_LLM_PROFILE = {
  id: "llm-profile-primary",
  name: "Primary",
  binding: "openai",
  base_url: "https://api.openai.example/v1",
  api_key: "***",
  api_version: "",
  extra_headers: {},
  connection_id: "conn-primary",
  models: [{ id: "llm-model-primary", name: "gpt-4o-mini", model: "gpt-4o-mini" }],
};

function soloProfile(service: "llm" | "stt"): Record<string, unknown> {
  return service === "llm"
    ? {
        id: "llm-profile-solo",
        name: "Solo LLM",
        binding: "openai",
        base_url: "https://api.openai.example/v1",
        api_key: "sk-solo",
        api_version: "",
        extra_headers: {},
        models: [{ id: "llm-model-solo", name: "gpt-4o-mini", model: "gpt-4o-mini" }],
      }
    : {
        id: "stt-profile-solo",
        name: "Solo STT",
        binding: "openai",
        base_url: "https://api.siliconflow.example/v1",
        api_key: "sk-solo",
        api_version: "",
        extra_headers: {},
        models: [
          {
            id: "stt-model-solo",
            name: "SenseVoice",
            model: "FunAudioLLM/SenseVoiceSmall",
          },
        ],
      };
}

function buildCatalog(opts: {
  connections?: CatalogConnection[];
  llmLinked?: boolean;
  llmStandalone?: boolean;
  sttStandalone?: boolean;
} = {}): Catalog {
  const catalog = defaultCatalog();
  catalog.connections = [...(opts.connections ?? [])];
  if (opts.llmLinked) {
    catalog.services.llm.profiles.push({
      ...LINKED_LLM_PROFILE,
    } as Catalog["services"]["llm"]["profiles"][number]);
    catalog.services.llm.active_profile_id = LINKED_LLM_PROFILE.id;
    catalog.services.llm.active_model_id = "llm-model-primary";
  }
  if (opts.llmStandalone) {
    const profile = soloProfile("llm");
    catalog.services.llm.profiles.push(
      profile as Catalog["services"]["llm"]["profiles"][number],
    );
    catalog.services.llm.active_profile_id = String(profile.id);
    catalog.services.llm.active_model_id = "llm-model-solo";
  }
  if (opts.sttStandalone) {
    const profile = soloProfile("stt");
    catalog.services.stt.profiles.push(
      profile as Catalog["services"]["stt"]["profiles"][number],
    );
    catalog.services.stt.active_profile_id = String(profile.id);
    catalog.services.stt.active_model_id = "stt-model-solo";
  }
  return catalog;
}

const ALL_ROWS: CatalogConnection[] = [
  CONN_PRIMARY,
  CONN_AUX,
  CONN_LONG,
  CONN_KEYLESS,
];

// ── Harness ──────────────────────────────────────────────────────────

const state: { fail: boolean; catalog: Catalog | null } = {
  fail: false,
  catalog: null,
};

const reply = (value: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 500,
  json: async () => value,
});

let settings: ReturnType<typeof useSettings> | undefined;

function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}

function App() {
  return (
    <SettingsProvider>
      <Capture />
      <ConnectionsEditor />
    </SettingsProvider>
  );
}

/** Mount with the catalog scenario already installed in `state`. */
async function mountWith(catalog: Catalog | null) {
  state.catalog = catalog;
  render(<App />);
  await waitFor(() => expect(settings?.settingsLoading).toBe(false));
}

beforeEach(() => {
  state.fail = false;
  state.catalog = null;
  settings = undefined;
  mocks.language = "en";
  mocks.fetch.mockReset();
  mocks.fetch.mockImplementation(async (url: string) => {
    if (url === "/api/settings") {
      if (state.fail) return reply({ detail: "nope" }, false);
      return reply({
        catalog: state.catalog,
        ui: { theme: "snow", language: "en", response_language: "en" },
        connection_targets: TARGETS,
      });
    }
    if (url === "/api/settings/draft") return reply({ draft: null });
    if (url === "/api/system/status") return reply({ status: "ok" });
    throw new Error(`Unexpected fetch in test: ${url}`);
  });
});

/** The ConnectionRow root is the nearest ancestor of a row's name that
 *  also contains that row's trash button. */
function rowOf(name: string): HTMLElement {
  let el: HTMLElement | null = screen.getByText(name).parentElement;
  while (el && !el.querySelector('button[aria-label="Delete"]')) {
    el = el.parentElement;
  }
  expect(el).not.toBeNull();
  return el!;
}

function discoveryInput(): Record<string, unknown> {
  return JSON.parse(
    screen.getByTestId("discovery-stub").getAttribute("data-input") ?? "{}",
  );
}

// ── Gates ────────────────────────────────────────────────────────────

describe("<ConnectionsEditor /> zero-coverage smoke", () => {
  it("shows the backend-unreachable panel when settings fail to load", async () => {
    state.fail = true;
    render(<App />);
    await waitFor(() => expect(settings?.settingsError).toBeTruthy());
    expect(
      screen.getByText(
        "Backend unreachable — model endpoints will appear once the connection is restored. See the banner above for details.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add connection" }),
    ).not.toBeInTheDocument();
  });

  it("shows the admin-assigned panel when the catalog is not editable", async () => {
    await mountWith(null);
    expect(
      screen.getByText(
        "Model endpoints are assigned by your administrator. You can still personalize theme and language here.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add connection" }),
    ).not.toBeInTheDocument();
  });

  // ── Empty states ───────────────────────────────────────────────────

  it("shows the bare empty state without standalone services", async () => {
    await mountWith(buildCatalog());
    expect(screen.getByText("No connections yet.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "A connection holds one vendor credential and supplies every model service that can use it.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Credentials are currently entered separately/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add connection" }),
    ).toBeInTheDocument();
  });

  it("lists standalone services in the empty state", async () => {
    await mountWith(buildCatalog({ llmStandalone: true, sttStandalone: true }));
    expect(
      screen.getByText(
        "Credentials are currently entered separately for LLM, Speech-to-Text.",
      ),
    ).toBeInTheDocument();
  });

  // ── Row rendering ──────────────────────────────────────────────────

  it("renders masked keys, service links and per-row empty states", async () => {
    await mountWith(buildCatalog({ connections: ALL_ROWS, llmLinked: true }));

    const primary = rowOf("Primary");
    expect(within(primary).getByText("••••••••")).toBeInTheDocument();
    const link = within(primary).getByRole("link", { name: /LLM/ });
    expect(link.getAttribute("href")).toBe(
      "/settings/llm?profile=llm-profile-primary",
    );

    expect(within(rowOf("Aux")).getByText("sk••••")).toBeInTheDocument();
    expect(within(rowOf("Longkey")).getByText("sk-ab••••1234")).toBeInTheDocument();
    expect(within(rowOf("Keyless")).getByText("No key")).toBeInTheDocument();

    expect(within(rowOf("Aux")).getByText("Not supplying any service yet")).toBeInTheDocument();
    expect(within(rowOf("Keyless")).getByText("Not supplying any service yet")).toBeInTheDocument();
    expect(within(rowOf("Primary")).queryByText("Not supplying any service yet")).not.toBeInTheDocument();

    // Only the not-yet-linked services of the row's own target become chips.
    expect(screen.getByRole("button", { name: "Embedding" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Image" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "LLM" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Speech-to-Text" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Text-to-Speech" })).toBeInTheDocument();
    expect(
      within(rowOf("Primary")).queryByRole("button", { name: "LLM" }),
    ).not.toBeInTheDocument();
    expect(
      within(rowOf("Primary")).queryByRole("button", { name: "Text-to-Speech" }),
    ).not.toBeInTheDocument();
  });

  // ── Add flow ───────────────────────────────────────────────────────

  it("gates the add form until a provider and at least one service are chosen", async () => {
    await mountWith(buildCatalog());
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));

    const submit = screen.getByRole("button", { name: "Add connection" }) as HTMLButtonElement;
    expect(submit).toBeDisabled();

    const providerSelect = screen.getByLabelText("Provider");
    const baseUrl = screen.getByLabelText("Base URL") as HTMLInputElement;
    expect(baseUrl.getAttribute("placeholder")).toBe("https://…/v1");

    fireEvent.change(providerSelect, { target: { value: "openai" } });
    expect(baseUrl.getAttribute("placeholder")).toBe("https://api.openai.example/v1");
    expect(screen.getByRole("button", { name: "LLM", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Embedding", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Image", pressed: true })).toBeInTheDocument();
    expect(screen.getByLabelText("Model ID")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No chat model picked yet — the profile is still created, pick one on the LLM page.",
      ),
    ).toBeInTheDocument();
    expect(submit).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "LLM", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "Embedding", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "Image", pressed: true }));
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "LLM" }));
    expect(submit).toBeEnabled();
  });

  it("creates a connection, links profiles and reports activated services", async () => {
    await mountWith(buildCatalog());
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "openai" },
    });
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://proxy.example/v1/" },
    });
    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "sk-new-0001" },
    });
    fireEvent.change(screen.getByLabelText("Model ID"), {
      target: { value: "gpt-5-mini" },
    });
    expect(
      screen.queryByText(
        "No chat model picked yet — the profile is still created, pick one on the LLM page.",
      ),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));

    await waitFor(() =>
      expect(settings?.toast).toBe(
        "Configured 3 services and made them active.",
      ),
    );
    expect(settings?.draft.connections).toHaveLength(1);
    const created = settings!.draft.connections![0];
    expect(created.provider).toBe("openai");
    expect(created.name).toBe("OpenAI");
    expect(created.api_key).toBe("sk-new-0001");
    // The connection keeps the typed value (whitespace-trimmed only); the
    // trailing slash is stripped when it is mirrored into linked profiles.
    expect(created.base_url).toBe("https://proxy.example/v1/");

    const llm = settings!.draft.services.llm;
    expect(llm.profiles).toHaveLength(1);
    expect(llm.profiles[0].connection_id).toBe(created.id);
    expect(llm.profiles[0].base_url).toBe("https://proxy.example/v1");
    expect(llm.active_profile_id).toBe(llm.profiles[0].id);
    expect(llm.profiles[0].models[0].model).toBe("gpt-5-mini");

    const embedding = settings!.draft.services.embedding;
    expect(embedding.profiles).toHaveLength(1);
    expect(embedding.profiles[0].base_url).toBe("https://proxy.example/v1/embeddings");
    expect(embedding.active_profile_id).toBe(embedding.profiles[0].id);
    expect(embedding.profiles[0].models[0].dimension).toBe("1536");

    const imagegen = settings!.draft.services.imagegen;
    expect(imagegen.profiles).toHaveLength(1);
    expect(imagegen.active_profile_id).toBe(imagegen.profiles[0].id);

    // The panel closed and the row is listed with its fresh links.
    expect(screen.getByText("1 connection")).toBeInTheDocument();
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /LLM/ })).toBeInTheDocument();
  });

  it("keeps an existing active choice and says so in the toast", async () => {
    await mountWith(buildCatalog({ llmStandalone: true }));
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "openai" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));

    await waitFor(() =>
      expect(settings?.toast).toBe(
        "Configured 3 services — LLM kept your existing choice.",
      ),
    );
    expect(settings!.draft.services.llm.active_profile_id).toBe("llm-profile-solo");
    expect(settings!.draft.services.llm.profiles).toHaveLength(2);
    expect(settings!.draft.services.embedding.active_profile_id).not.toBeNull();
    expect(settings!.draft.services.imagegen.active_profile_id).not.toBeNull();
  });

  it("cancels the add panel without touching the draft", async () => {
    await mountWith(buildCatalog());
    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "openai" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Provider")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add connection" })).toBeInTheDocument();
    expect(settings?.draft.connections).toHaveLength(0);
    expect(settings?.toast ?? "").not.toContain("Configured");
  });

  // ── Edit flow ──────────────────────────────────────────────────────

  it("edits connection fields, toggles key visibility and feeds discovery", async () => {
    await mountWith(buildCatalog({ connections: ALL_ROWS, llmLinked: true }));

    fireEvent.click(within(rowOf("Primary")).getByRole("button", { name: "Edit" }));

    const nameInput = screen.getByLabelText("Name") as HTMLInputElement;
    expect(nameInput.value).toBe("Primary");
    const baseUrlInput = screen.getByLabelText("Base URL") as HTMLInputElement;
    expect(baseUrlInput.value).toBe("https://api.openai.example/v1");
    const keyInput = screen.getByLabelText("API Key") as HTMLInputElement;
    expect(keyInput.type).toBe("password");
    expect(keyInput.value).toBe("***");
    expect(
      screen.getByText(
        "Saving pushes these values into every profile this connection supplies.",
      ),
    ).toBeInTheDocument();

    expect(discoveryInput()).toEqual({
      binding: "openai",
      base_url: "https://api.openai.example/v1",
      api_key: "***",
      connection_id: "conn-primary",
      extra_headers: {},
      api_version: "",
    });

    fireEvent.click(screen.getByRole("button", { name: "Show API key" }));
    expect((screen.getByLabelText("API Key") as HTMLInputElement).type).toBe("text");
    expect(
      screen.getByRole("button", { name: "Hide API key" }),
    ).toBeInTheDocument();

    fireEvent.change(nameInput, { target: { value: "Renamed" } });
    expect(screen.getByText("Renamed")).toBeInTheDocument();
    expect(settings!.draft.connections![0].name).toBe("Renamed");

    fireEvent.change(baseUrlInput, {
      target: { value: "https://relay.example/v1" },
    });
    expect(discoveryInput().base_url).toBe("https://relay.example/v1");

    fireEvent.change(screen.getByLabelText("API Key"), {
      target: { value: "sk-edit-9999" },
    });
    expect(settings!.draft.connections![0].api_key).toBe("sk-edit-9999");
    // Mirroring into the linked profile happens on save, not on typing.
    expect(settings!.draft.services.llm.profiles[0].api_key).toBe("***");

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
    expect(screen.getByText("Renamed")).toBeInTheDocument();
  });

  // ── Delete flow ────────────────────────────────────────────────────

  it("deletes a linked connection after confirm and detaches its profile", async () => {
    await mountWith(buildCatalog({ connections: [CONN_PRIMARY], llmLinked: true }));

    fireEvent.click(within(rowOf("Primary")).getByRole("button", { name: "Delete" }));
    expect(
      screen.getByText(
        "Profiles it supplies keep their current credentials but stop following this connection.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(
      screen.queryByText(
        "Profiles it supplies keep their current credentials but stop following this connection.",
      ),
    ).not.toBeInTheDocument();
    expect(settings!.draft.connections).toHaveLength(1);

    fireEvent.click(within(rowOf("Primary")).getByRole("button", { name: "Delete" }));
    // The strip's Delete is the only button carrying the label as text —
    // the trash icon is addressed by its aria-label above.
    fireEvent.click(screen.getByText("Delete"));

    expect(screen.getByText("No connections yet.")).toBeInTheDocument();
    expect(
      screen.getByText("Credentials are currently entered separately for LLM."),
    ).toBeInTheDocument();
    const profile = settings!.draft.services.llm.profiles[0];
    expect(profile.connection_id).toBeUndefined();
    expect(profile.api_key).toBe("***");
    expect(profile.base_url).toBe("https://api.openai.example/v1");
    expect(settings!.draft.services.llm.active_profile_id).toBe(profile.id);
    expect(settings!.draft.connections).toHaveLength(0);
  });

  it("deletes an unlinked connection showing the no-consumer warning", async () => {
    await mountWith(buildCatalog({ connections: [CONN_AUX] }));

    fireEvent.click(within(rowOf("Aux")).getByRole("button", { name: "Delete" }));
    expect(
      screen.getByText("Nothing is using this connection."),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("Delete"));
    expect(screen.getByText("No connections yet.")).toBeInTheDocument();
    expect(settings!.draft.connections).toHaveLength(0);
  });

  // ── Service linking from a row ─────────────────────────────────────

  it("links an available service from a row chip and activates it", async () => {
    await mountWith(buildCatalog({ connections: [CONN_PRIMARY], llmLinked: true }));

    fireEvent.click(screen.getByRole("button", { name: "Embedding" }));

    await waitFor(() =>
      expect(settings?.toast).toBe("Embedding now uses Primary."),
    );
    const embedding = settings!.draft.services.embedding;
    expect(embedding.profiles).toHaveLength(1);
    expect(embedding.profiles[0].connection_id).toBe("conn-primary");
    expect(embedding.active_profile_id).toBe(embedding.profiles[0].id);

    expect(
      screen.queryByRole("button", { name: "Embedding" }),
    ).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: /Embedding/ });
    expect(link.getAttribute("href")).toBe(
      `/settings/embedding?profile=${embedding.profiles[0].id}`,
    );
  });

  it("adds a profile without switching the active one when the service already has one", async () => {
    await mountWith(buildCatalog({ connections: [CONN_AUX], sttStandalone: true }));

    fireEvent.click(within(rowOf("Aux")).getByRole("button", { name: "Speech-to-Text" }));

    await waitFor(() =>
      expect(settings?.toast).toBe(
        "Added a Speech-to-Text profile — switch to it on its own page.",
      ),
    );
    const stt = settings!.draft.services.stt;
    expect(stt.profiles).toHaveLength(2);
    expect(stt.active_profile_id).toBe("stt-profile-solo");
    expect(stt.profiles[1].connection_id).toBe("conn-aux");
  });

  // ── Localization ───────────────────────────────────────────────────

  it("localizes service labels and the standalone list in Chinese", async () => {
    mocks.language = "zh-CN";
    await mountWith(buildCatalog({ llmStandalone: true, sttStandalone: true }));
    expect(
      screen.getByText("Credentials are currently entered separately for LLM、语音识别."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add connection" }));
    fireEvent.change(screen.getByLabelText("Provider"), {
      target: { value: "siliconflow" },
    });
    expect(screen.getByRole("button", { name: "语音识别", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "语音合成", pressed: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "LLM", pressed: true })).toBeInTheDocument();
  });
});
