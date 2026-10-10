import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import NetworkSettingsPage from "@/features/settings/sections/NetworkSettingsSection";

const t = (key: string) => key;
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t, i18n: { language: "en" } }),
}));

interface NetworkEdit {
  dirty: boolean;
  save: () => Promise<void>;
  payload: unknown;
}

const staged = vi.hoisted(() => {
  const edits = new Map<string, NetworkEdit>();
  const pending = new Map<string, unknown>();
  return {
    edits,
    pending,
    registerExtension: vi.fn(
      (key: string, edit: NetworkEdit | null) => {
        if (edit === null) edits.delete(key);
        else edits.set(key, edit);
      },
    ),
    pendingExtensionPayload: (key: string) => pending.get(key),
  };
});

vi.mock("@/features/settings/store/SettingsStore", () => ({
  useSettings: () => ({
    registerExtension: staged.registerExtension,
    pendingExtensionPayload: staged.pendingExtensionPayload,
    draftRevision: 0,
  }),
}));

const fetchMock = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api", () => ({
  apiUrl: (path: string) => path,
  apiFetch: (...args: unknown[]) => fetchMock(...args),
}));

vi.mock("@/features/runtime-status", () => ({
  RuntimeHealthCard: () => <div data-testid="runtime-health-card" />,
  TurnCoordinationSettings: () => null,
  useRuntimeStatus: () => ({
    data: null,
    health: "unavailable",
    error: null,
    loading: false,
    lastUpdated: null,
    refresh: vi.fn(async () => {}),
  }),
}));

const networkPayload = {
  settings: {
    backend_port: 8000,
    frontend_port: 3000,
    public_api_base: "",
    cors_origins: ["https://app.example.com"],
  },
  effective: {
    backend_url: "http://127.0.0.1:8000",
    frontend_url: "http://127.0.0.1:3000",
    browser_api_base: "http://127.0.0.1:8000",
    api_base_source: "default",
    cors_mode: "explicit" as const,
    cors_origins: ["https://app.example.com"],
    allow_remote_http_origins: false,
  },
  auth: {
    enabled: true,
    cookie_secure: true,
    cookie_samesite: "Lax",
    cross_site_cookie_ready: true,
  },
  restart_required: true,
};

const reply = (value: unknown, ok = true, status = 200) => ({
  ok,
  status,
  json: async () => value,
});

/** The SettingRow root that renders the given row title. */
function rowOf(label: string): HTMLElement {
  const title = screen.getByText(label);
  return title.parentElement?.parentElement as HTMLElement;
}

function backendPortInput(): HTMLInputElement {
  return within(rowOf("Backend port")).getByRole(
    "spinbutton",
  ) as HTMLInputElement;
}

function corsTextarea(): HTMLTextAreaElement {
  return screen.getByPlaceholderText(/learn\.example\.com/) as HTMLTextAreaElement;
}

function lastRegistration(): NetworkEdit | undefined {
  const calls = staged.registerExtension.mock.calls.filter(
    ([key]) => key === "network",
  );
  return calls.length ? calls[calls.length - 1][1] ?? undefined : undefined;
}

beforeEach(() => {
  staged.edits.clear();
  staged.pending.clear();
  fetchMock.mockReset().mockResolvedValue(reply(networkPayload));
});

describe("NetworkSettingsSection", () => {
  it("loads payload into tiles, ports, and the CORS textarea", async () => {
    render(<NetworkSettingsPage />);

    expect(
      await screen.findByText("http://127.0.0.1:8000"),
    ).toBeInTheDocument();
    expect(screen.getByText("Explicit origins required")).toBeInTheDocument();
    expect(screen.getByText("Lax + Secure")).toBeInTheDocument();
    expect(screen.getByText("Required after save")).toBeInTheDocument();

    expect(backendPortInput().value).toBe("8000");
    const frontendPort = within(rowOf("Frontend port")).getByRole(
      "spinbutton",
    ) as HTMLInputElement;
    expect(frontendPort.value).toBe("3000");
    expect(corsTextarea().value).toBe("https://app.example.com");

    await waitFor(() => {
      const ext = staged.edits.get("network");
      expect(ext?.dirty).toBe(false);
      expect(ext?.payload).toEqual({
        backend_port: 8000,
        frontend_port: 3000,
        public_api_base: "",
        cors_origins: ["https://app.example.com"],
      });
    });
  });

  it("prefers a pending draft over the server settings on load", async () => {
    staged.pending.set("network", {
      backend_port: 9000,
      frontend_port: 3000,
      public_api_base: "https://api.example.com",
      cors_origins: ["https://pending.example.com"],
    });

    render(<NetworkSettingsPage />);

    await waitFor(() => expect(backendPortInput().value).toBe("9000"));
    expect(corsTextarea().value).toBe("https://pending.example.com");
    expect(
      within(rowOf("Public API base")).getByPlaceholderText(
        "https://api.example.com",
      ),
    ).toHaveValue("https://api.example.com");
    await waitFor(() => {
      expect(staged.edits.get("network")?.dirty).toBe(true);
    });
  });

  it("shows the loading indicator while fetching", () => {
    fetchMock.mockReturnValue(new Promise(() => {}));

    render(<NetworkSettingsPage />);

    expect(screen.getByText("Loading network settings...")).toBeInTheDocument();
    expect(document.querySelector(".animate-spin")).not.toBeNull();
    expect(screen.queryByText("Backend port")).not.toBeInTheDocument();
  });

  it("renders the server-provided detail on load failure", async () => {
    fetchMock.mockResolvedValue(reply({ detail: "boom" }, false, 503));

    render(<NetworkSettingsPage />);

    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(screen.queryByText("Backend port")).not.toBeInTheDocument();
  });

  it("falls back to the generic message when no detail is returned", async () => {
    fetchMock.mockResolvedValue(reply({}, false, 500));

    render(<NetworkSettingsPage />);

    expect(
      await screen.findByText("Failed to load network settings."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading network settings...")).not.toBeInTheDocument();
  });

  it("splits CORS origins on commas, semicolons, and newlines", async () => {
    render(<NetworkSettingsPage />);
    await screen.findByText("Backend port");

    fireEvent.change(corsTextarea(), {
      target: { value: " https://a.example.com, https://b.example.com;\n\nhttp://10.0.0.5:3782 " },
    });

    await waitFor(() => {
      const ext = staged.edits.get("network");
      expect(ext?.dirty).toBe(true);
      expect(ext?.payload).toMatchObject({
        cors_origins: [
          "https://a.example.com",
          "https://b.example.com",
          "http://10.0.0.5:3782",
        ],
      });
    });
  });

  it("warns when auth is enabled without secure cookies", async () => {
    fetchMock.mockResolvedValue(
      reply({
        ...networkPayload,
        auth: { ...networkPayload.auth, cookie_secure: false },
      }),
    );

    render(<NetworkSettingsPage />);
    await screen.findByText("Backend port");

    expect(
      screen.getByText(/auth\.cookie_secure=true/),
    ).toBeInTheDocument();
  });

  it("hides the secure-cookie warning when cookies are configured", async () => {
    render(<NetworkSettingsPage />);
    await screen.findByText("Backend port");

    expect(
      screen.queryByText(/auth\.cookie_secure=true/),
    ).not.toBeInTheDocument();
  });

  it("save PUTs the draft with split origins and re-syncs", async () => {
    render(<NetworkSettingsPage />);
    await waitFor(() =>
      expect(staged.edits.get("network")?.dirty).toBe(false),
    );

    fireEvent.change(backendPortInput(), { target: { value: "9001" } });
    fireEvent.change(corsTextarea(), {
      target: { value: "https://a.example.com;https://b.example.com" },
    });
    await waitFor(() =>
      expect(staged.edits.get("network")?.dirty).toBe(true),
    );

    const saved = reply({
      ...networkPayload,
      settings: {
        ...networkPayload.settings,
        backend_port: 9001,
        cors_origins: ["https://a.example.com", "https://b.example.com"],
      },
    });
    fetchMock.mockResolvedValue(saved);

    await act(async () => {
      await staged.edits.get("network")?.save();
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/settings/network", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        backend_port: 9001,
        frontend_port: 3000,
        public_api_base: "",
        cors_origins: ["https://a.example.com", "https://b.example.com"],
      }),
    });
    await waitFor(() => {
      expect(backendPortInput().value).toBe("9001");
      expect(lastRegistration()?.dirty).toBe(false);
    });
  });

  it("save failure surfaces the detail banner and rethrows", async () => {
    render(<NetworkSettingsPage />);
    await waitFor(() =>
      expect(staged.edits.get("network")?.dirty).toBe(false),
    );

    fireEvent.change(backendPortInput(), { target: { value: "9001" } });
    await waitFor(() =>
      expect(staged.edits.get("network")?.dirty).toBe(true),
    );

    fetchMock.mockResolvedValue(reply({ detail: "port already in use" }, false, 409));
    await act(async () => {
      await expect(staged.edits.get("network")?.save()).rejects.toThrow(
        "port already in use",
      );
    });
    expect(await screen.findByText("port already in use")).toBeInTheDocument();
    expect(lastRegistration()?.dirty).toBe(true);
  });
});
