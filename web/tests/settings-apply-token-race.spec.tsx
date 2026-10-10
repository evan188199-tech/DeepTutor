import React, { useEffect, useState } from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  SettingsProvider,
  defaultCatalog,
  useSettings,
} from "@/features/settings/store/SettingsStore";
import { useStagedSettings } from "@/features/settings/store/useStagedSettings";
import { UiSettingsProvider } from "@/features/settings/store/UiSettingsProvider";
import { MinerUEngineSettings } from "@/components/settings/MinerUEngineSettings";

const TOKEN_MASK = "••••••••••••";
const mocks = vi.hoisted(() => ({ fetch: vi.fn() }));
vi.mock("@/lib/api", () => ({
  apiUrl: (s: string) => s,
  apiFetch: (...args: unknown[]) => mocks.fetch(...args),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));
vi.mock("@/lib/theme", () => ({
  setTheme: vi.fn(),
}));
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

let settings: ReturnType<typeof useSettings>;
let live: ReturnType<typeof defaultCatalog>;
let stored: any;
let resources: Record<string, any>;
const reply = (value: unknown, ok = true) => ({
  ok,
  status: ok ? 200 : 422,
  json: async () => value,
});
beforeEach(() => {
  live = defaultCatalog();
  stored = null;
  resources = {
    workspace: { path: "/original" },
    mineru: {
      settings: { mode: "cloud", api_base_url: "http://mineru" },
      api_token_set: true,
    },
  };
  mocks.fetch.mockImplementation(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/settings")
      return reply({
        catalog: live,
        ui: { theme: "snow", language: "en", response_language: "en" },
      });
    if (url === "/api/settings/draft") {
      if (method === "PUT") stored = JSON.parse(String(init?.body));
      if (method === "DELETE") stored = null;
      return reply({ draft: stored });
    }
    if (url === "/api/settings/apply") {
      live = stored.catalog;
      stored = null;
      return reply({ catalog: live });
    }
    const key = url.split("/").pop()!;
    if (method === "PUT") {
      const body = JSON.parse(String(init?.body));
      if (key === "mineru") {
        // Mirror the backend: a saved token keeps api_token_set true, an
        // explicit clear ("") turns it off, an untouched token keeps it.
        const tokenSet =
          body.api_token === undefined
            ? (resources.mineru.api_token_set ?? false)
            : Boolean(body.api_token);
        resources.mineru = {
          ...resources.mineru,
          ...body,
          api_token_set: tokenSet,
        };
      } else {
        resources[key] = body;
      }
    }
    return reply(resources[key] ?? {});
  });
});
function Capture() {
  const value = useSettings();
  useEffect(() => {
    settings = value;
  }, [value]);
  return null;
}
function Editor({ name }: { name: string }) {
  const [liveValue, setLiveValue] = useState(resources[name]);
  const [draft, edit] = useStagedSettings(name, liveValue, setLiveValue);
  return (
    <input
      aria-label={name}
      value={draft.path ?? draft.provider}
      onChange={(e) =>
        edit(
          name === "workspace"
            ? { path: e.target.value }
            : { provider: e.target.value },
        )
      }
    />
  );
}
function App() {
  return (
    <SettingsProvider>
      <UiSettingsProvider>
        <Capture />
        <Editor name="workspace" />
        <MinerUEngineSettings />
      </UiSettingsProvider>
    </SettingsProvider>
  );
}
async function ready() {
  await waitFor(() => expect(settings.settingsLoading).toBe(false));
}
const writes = (endpoint: string) =>
  mocks.fetch.mock.calls.filter(
    ([url, init]) => url === endpoint && init?.method === "PUT",
  );
const bodies = (endpoint: string) =>
  writes(endpoint).map(([, init]) => JSON.parse(String(init?.body)));

async function holdWhileApplying(endpoint: string) {
  const implementation = mocks.fetch.getMockImplementation()!;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  mocks.fetch.mockImplementation(async (url, init) => {
    if (url === endpoint && init?.method === "PUT") await gate;
    return implementation(url, init);
  });
  let applying!: Promise<void>;
  act(() => {
    applying = settings.applyCatalog();
  });
  await waitFor(() => expect(writes(endpoint)).toHaveLength(1));
  return { release: () => release(), applying };
}

it("applies the captured token and keeps a clear typed during a pending Apply for the next Apply", async () => {
  render(<App />);
  await ready();
  const token = await screen.findByPlaceholderText(TOKEN_MASK);
  fireEvent.change(token, { target: { value: "staged-token" } });
  expect(settings.hasUnsavedChanges).toBe(true);
  const { release, applying } = await holdWhileApplying("/api/settings/mineru");
  fireEvent.change(screen.getByPlaceholderText(TOKEN_MASK), {
    target: { value: "" },
  });
  await act(async () => {
    release();
    await applying;
  });
  expect(bodies("/api/settings/mineru")[0]).toHaveProperty(
    "api_token",
    "staged-token",
  );
  expect(resources.mineru.api_token).toBe("staged-token");
  expect(screen.getByPlaceholderText(TOKEN_MASK)).toHaveValue("");
  expect(settings.draftState).toBe("unsaved");
  await act(() => settings.applyCatalog());
  expect(bodies("/api/settings/mineru")[1]).toHaveProperty("api_token", "");
  expect(resources.mineru.api_token).toBe("");
  expect(settings.draftState).toBe("clean");
});

it("does not let an unrelated Apply discard a MinerU token clear made while it runs", async () => {
  render(<App />);
  await ready();
  await screen.findByPlaceholderText(TOKEN_MASK);
  fireEvent.change(screen.getByLabelText("workspace"), {
    target: { value: "/first" },
  });
  const { release, applying } = await holdWhileApplying(
    "/api/settings/workspace",
  );
  fireEvent.click(screen.getByRole("button", { name: "Show API token" }));
  const field = screen.getByPlaceholderText(TOKEN_MASK);
  fireEvent.change(field, { target: { value: "x" } });
  fireEvent.change(field, { target: { value: "" } });
  await act(async () => {
    release();
    await applying;
  });
  expect(resources.workspace.path).toBe("/first");
  expect(writes("/api/settings/mineru")).toHaveLength(0);
  expect(screen.getByPlaceholderText(TOKEN_MASK)).toHaveValue("");
  expect(settings.draftState).toBe("unsaved");
  await act(() => settings.applyCatalog());
  expect(bodies("/api/settings/mineru")[0]).toHaveProperty("api_token", "");
  expect(resources.mineru.api_token).toBe("");
  expect(settings.draftState).toBe("clean");
});
