import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import PartnerChannels from "@/components/partners/PartnerChannels";
import type { ChannelsSchemaResponse } from "@/lib/partners-api";

const api = vi.hoisted(() => ({
  fetch: vi.fn(),
  schemas: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/lib/api", () => ({
  apiFetch: api.fetch,
  apiUrl: (path: string) => path,
}));
vi.mock("@/lib/partners-api", () => ({
  getChannelSchemas: api.schemas,
  supportsChannelOnboarding: (channel: string, available?: boolean) =>
    available !== false && (channel === "feishu" || channel === "wecom"),
}));
vi.mock("@/components/partners/WeixinQrLogin", () => ({
  default: () => <div data-testid="weixin-qr" />,
}));
vi.mock("@/components/partners/ChannelOnboardingPanel", () => ({
  default: (props: { channel: string }) => (
    <div data-testid="onboarding-panel" data-channel={props.channel} />
  ),
}));
vi.mock("@/components/partners/ChannelRuntimeStatus", () => ({
  default: (props: { channel: string; enabled: boolean }) => (
    <div
      data-testid="runtime-status"
      data-channel={props.channel}
      data-enabled={String(props.enabled)}
    />
  ),
}));

const catalog: ChannelsSchemaResponse = {
  channels: {
    telegram: {
      name: "telegram",
      display_name: "Telegram",
      default_config: { enabled: false, bot_token: "", allow_from: [] },
      secret_fields: ["bot_token"],
      json_schema: {
        type: "object",
        description: "Telegram channel settings",
        properties: {
          enabled: { type: "boolean", title: "Enabled" },
          bot_token: { type: "string", title: "Bot Token" },
          allow_from: {
            type: "array",
            items: { type: "string" },
            title: "Allow From",
          },
        },
      },
    },
    weixin: {
      name: "weixin",
      display_name: "WeChat",
      default_config: { enabled: false, token: "", allow_from: [] },
      secret_fields: ["token"],
      json_schema: {
        type: "object",
        properties: {
          enabled: { type: "boolean", title: "Enabled" },
          token: { type: "string", title: "Token" },
          allow_from: {
            type: "array",
            items: { type: "string" },
            title: "Allow From",
          },
        },
      },
    },
    feishu: {
      name: "feishu",
      display_name: "Feishu",
      default_config: {},
      secret_fields: [],
      json_schema: null,
      available: false,
      unavailable_reason: "ImportError: lark-oapi is not installed",
    },
    wecom: {
      name: "wecom",
      display_name: "WeCom",
      default_config: { enabled: false },
      secret_fields: [],
      json_schema: {
        type: "object",
        properties: {
          enabled: { type: "boolean", title: "Enabled" },
        },
      },
    },
  },
};

const detailBody = () => ({
  channels: {
    weixin: { enabled: true, token: "secret-token", allow_from: ["alice"] },
    telegram: { enabled: false, bot_token: "", allow_from: [] },
  } as Record<string, unknown>,
  last_reload_error: null,
});

type ResLike = {
  ok: boolean;
  status: number;
  json: () => Promise<unknown>;
};
const okRes = (body: unknown): ResLike => ({
  ok: true,
  status: 200,
  json: async () => body,
});
const errRes = (body: unknown, status: number): ResLike => ({
  ok: false,
  status,
  json: async () => body,
});
const brokenRes = (status: number): ResLike => ({
  ok: false,
  status,
  json: async () => {
    throw new Error("unreadable body");
  },
});

let patchHandler: () => ResLike = () => okRes({});
let detailHandler: () => ResLike = () => okRes(detailBody());

function renderPanel(onToast = vi.fn()) {
  return render(<PartnerChannels partnerId="p1" onToast={onToast} />);
}

async function settledPanel(onToast = vi.fn()) {
  const utils = renderPanel(onToast);
  await screen.findByRole("heading", { name: /WeChat/ });
  return { ...utils, onToast };
}

function sidebar(): HTMLElement {
  const aside = document.querySelector("aside");
  expect(aside).not.toBeNull();
  return aside as HTMLElement;
}

function patchCall(): [string, { method?: string; body?: string }] {
  const call = api.fetch.mock.calls.find(
    (c) => (c[1] as { method?: string } | undefined)?.method === "PATCH",
  ) as [string, { method?: string; body?: string }] | undefined;
  expect(call).toBeDefined();
  return call as [string, { method?: string; body?: string }];
}

function detailCalls(): number {
  return api.fetch.mock.calls.filter(
    (c) => c[0] === "/api/partners/p1?include_secrets=true",
  ).length;
}

async function save() {
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  await act(async () => {});
}

beforeEach(() => {
  api.schemas.mockResolvedValue(catalog);
  patchHandler = () => okRes({});
  detailHandler = () => okRes(detailBody());
  api.fetch.mockImplementation(
    async (_url: string, init?: { method?: string }) =>
      init?.method === "PATCH" ? patchHandler() : detailHandler(),
  );
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

it("renders a spinner until catalog and detail both resolve", async () => {
  const catalogGate = deferred<unknown>();
  const detailGate = deferred<unknown>();
  api.schemas.mockReturnValue(catalogGate.promise);
  detailHandler = () => ({
    ok: true,
    status: 200,
    json: () => detailGate.promise,
  });

  const { container } = renderPanel();
  expect(container.querySelector(".animate-spin")).not.toBeNull();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();

  await act(async () => {
    catalogGate.resolve({ channels: catalog.channels });
    detailGate.resolve(detailBody());
  });
  expect(await screen.findByRole("heading", { name: /WeChat/ })).toBeTruthy();
  expect(container.querySelector(".animate-spin")).toBeNull();
});

it("assembles the sidebar sorted by display name with an Enabled badge", async () => {
  await settledPanel();
  const buttons = within(sidebar()).getAllByRole("button");
  expect(buttons.map((b) => b.textContent)).toEqual([
    "Feishu",
    "Telegram",
    "WeChatEnabled",
    "WeCom",
  ]);
  expect(
    within(buttons.find((b) => b.textContent === "Telegram") as HTMLElement)
      .queryByText("Enabled"),
  ).toBeNull();
  expect(screen.getByRole("heading", { name: /WeChat/ })).toBeTruthy();
  expect(screen.getByText("weixin")).toBeTruthy();
  expect(screen.queryByText(/Add at least one allowed sender/)).toBeNull();
});

it("selects the first catalog channel and its default config when none are enabled", async () => {
  detailHandler = () => okRes({ channels: {}, last_reload_error: null });
  renderPanel();
  await screen.findByRole("heading", { name: /Telegram/ });

  expect(screen.getByText("telegram")).toBeTruthy();
  expect(screen.getByText("Telegram channel settings")).toBeTruthy();
  const enabledBox = screen.getByRole("checkbox") as HTMLInputElement;
  expect(enabledBox.checked).toBe(false);
  expect(screen.getAllByDisplayValue("")).toHaveLength(2);
  expect(screen.queryByTestId("runtime-status")).not.toBeNull();
});

it("shows the empty-catalog prompt when the server exposes no channels", async () => {
  api.schemas.mockResolvedValue({ channels: {} });
  renderPanel();

  expect(await screen.findByText("Select a channel.")).toBeTruthy();
  expect(within(sidebar()).queryByRole("button")).toBeNull();
});

it("surfaces the last listener reload error as a banner", async () => {
  detailHandler = () =>
    okRes({ channels: {}, last_reload_error: "listener crashed" });
  renderPanel();

  expect(
    await screen.findByText("Channel listeners failed to restart:"),
  ).toBeTruthy();
  expect(screen.getByText("listener crashed")).toBeTruthy();
});

it("shows the unavailable branch for channels missing server modules", async () => {
  await settledPanel();

  const feishuButton = screen.getByRole("button", { name: "Feishu" });
  expect(feishuButton.className).toContain("opacity-45");
  fireEvent.click(feishuButton);

  expect(
    screen.getByText("This channel is not available on the server."),
  ).toBeTruthy();
  expect(screen.getByText(/lark-oapi is not installed/)).toBeTruthy();
  expect(screen.queryByTestId("onboarding-panel")).toBeNull();
  expect(screen.queryByTestId("runtime-status")).toBeNull();
  expect(screen.queryByRole("checkbox")).toBeNull();
});

it("strips legacy global delivery keys from state and the save payload", async () => {
  detailHandler = () =>
    okRes({
      channels: {
        telegram: { enabled: false, bot_token: "", allow_from: [] },
        send_progress: true,
        send_tool_hints: false,
        sendToolHints: true,
      },
      last_reload_error: null,
    });
  renderPanel();
  await screen.findByRole("heading", { name: /Telegram/ });

  expect(screen.queryByText(/send progress/i)).toBeNull();
  await save();

  const [url, init] = patchCall();
  expect(url).toBe("/api/partners/p1");
  const body = JSON.parse(init.body as string) as {
    channels: Record<string, unknown>;
  };
  expect(Object.keys(body.channels)).toEqual(["telegram"]);
});

it("saves the edited config via PATCH, toasts, and reloads detail", async () => {
  const { onToast } = await settledPanel();

  fireEvent.change(screen.getByDisplayValue("secret-token"), {
    target: { value: "rotated-token" },
  });
  await save();

  expect(onToast).toHaveBeenCalledWith("Channels saved");
  const [url, init] = patchCall();
  expect(url).toBe("/api/partners/p1");
  expect(init.method).toBe("PATCH");
  const body = JSON.parse(init.body as string) as {
    channels: Record<string, Record<string, unknown>>;
  };
  expect(body.channels.weixin.token).toBe("rotated-token");
  expect(body.channels.weixin.allow_from).toEqual(["alice"]);
  expect(detailCalls()).toBe(2);
});

it("maps a 422 validation envelope onto the toast", async () => {
  const onToast = vi.fn();
  patchHandler = () =>
    errRes(
      {
        detail: {
          errors: [
            {
              loc: ["body", "channels", "telegram", "bot_token"],
              msg: "Field required",
            },
          ],
        },
      },
      422,
    );
  await settledPanel(onToast);
  await save();

  expect(onToast).toHaveBeenCalledTimes(1);
  expect(onToast).toHaveBeenCalledWith(
    "Invalid channel configuration — body.channels.telegram.bot_token: Field required",
  );
});

it.each([
  [
    "detail string",
    () => errRes({ detail: "quota exceeded" }, 500),
    "quota exceeded",
  ],
  ["unreadable body", () => brokenRes(500), "Save failed"],
])("surfaces non-422 save failures (%s)", async (_name, handler, expected) => {
  const onToast = vi.fn();
  patchHandler = handler as () => ResLike;
  await settledPanel(onToast);
  await save();

  expect(onToast).toHaveBeenCalledWith(expected);
});

it("surfaces a save network error", async () => {
  const onToast = vi.fn();
  patchHandler = () => {
    throw new Error("offline");
  };
  await settledPanel(onToast);
  await save();

  expect(onToast).toHaveBeenCalledWith("offline");
});

it("masks secret fields until explicitly revealed", async () => {
  await settledPanel();

  const token = screen.getByDisplayValue("secret-token") as HTMLInputElement;
  expect(token.type).toBe("password");
  expect(token.autocomplete).toBe("new-password");

  fireEvent.click(screen.getByRole("button", { name: "Show secret" }));
  expect(
    (screen.getByDisplayValue("secret-token") as HTMLInputElement).type,
  ).toBe("text");

  fireEvent.click(screen.getByRole("button", { name: "Hide secret" }));
  expect(
    (screen.getByDisplayValue("secret-token") as HTMLInputElement).type,
  ).toBe("password");
});

it("warns when an enabled channel has no allowed senders", async () => {
  detailHandler = () =>
    okRes({
      channels: { weixin: { enabled: true, token: "t", allow_from: [] } },
      last_reload_error: null,
    });
  renderPanel();

  expect(
    await screen.findByText(
      "Add at least one allowed sender before starting this channel.",
    ),
  ).toBeTruthy();
  expect(screen.getByTestId("runtime-status").dataset.enabled).toBe("true");
});

it("renders the WeChat QR login only for the weixin channel", async () => {
  await settledPanel();

  expect(screen.getByTestId("weixin-qr")).toBeTruthy();
  expect(screen.getByTestId("runtime-status").dataset.channel).toBe("weixin");

  fireEvent.click(screen.getByRole("button", { name: "Telegram" }));
  expect(screen.queryByTestId("weixin-qr")).toBeNull();
  expect(screen.getByTestId("runtime-status").dataset.channel).toBe("telegram");
  expect(screen.getByTestId("runtime-status").dataset.enabled).toBe("false");
});

it("renders the onboarding panel for wecom but not telegram", async () => {
  await settledPanel();

  expect(screen.queryByTestId("onboarding-panel")).toBeNull();

  fireEvent.click(screen.getByRole("button", { name: "WeCom" }));
  expect(screen.getByTestId("onboarding-panel").dataset.channel).toBe("wecom");
});

it("recovers from a catalog failure via Retry", async () => {
  api.schemas.mockRejectedValueOnce(new Error("schema down"));
  renderPanel();

  expect(await screen.findByText("Could not load this section.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect(api.schemas).toHaveBeenCalledTimes(2);
  expect(await screen.findByRole("heading", { name: /WeChat/ })).toBeTruthy();
});

it("recovers from a detail failure via Retry", async () => {
  let calls = 0;
  detailHandler = () => {
    calls += 1;
    return calls === 1 ? errRes({}, 500) : okRes(detailBody());
  };
  renderPanel();

  expect(await screen.findByText("Could not load this section.")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));

  expect(await screen.findByRole("heading", { name: /Telegram/ })).toBeTruthy();
  expect(detailCalls()).toBe(2);
});

it("keeps the save button usable again after a failed save", async () => {
  const onToast = vi.fn();
  patchHandler = () => errRes({ detail: "quota exceeded" }, 500);
  const { container } = await settledPanel(onToast);

  await save();
  await waitFor(() =>
    expect(container.querySelector(".animate-spin")).toBeNull(),
  );
  expect(
    (screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled,
  ).toBe(false);
});
