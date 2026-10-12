import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ImaConnectionFields from "@/components/knowledge/ImaConnectionFields";
import type { ImaConnectionController } from "@/hooks/useImaConnection";
import {
  emptyImaLookupState,
  type ImaKnowledgeBaseOption,
  type ImaLookupState,
} from "@/lib/ima-connection";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function makeConnection(
  overrides: Partial<ImaConnectionController> = {},
): ImaConnectionController {
  return {
    accountConfigured: false,
    useOwnCredentials: false,
    setUseOwnCredentials: vi.fn(),
    clientId: "",
    setClientId: vi.fn(),
    apiKey: "",
    setApiKey: vi.fn(),
    mode: "automatic",
    setMode: vi.fn(),
    manualKnowledgeBaseId: "",
    setManualKnowledgeBaseId: vi.fn(),
    lookup: emptyImaLookupState(),
    manualProbe: null,
    credentialsReady: true,
    canSubmit: false,
    knowledgeBaseId: "",
    submittedClientId: "",
    submittedApiKey: "",
    reset: vi.fn(),
    load: vi.fn(async () => {}),
    select: vi.fn(),
    probe: vi.fn(async () => {}),
    ...overrides,
  };
}

function lookupWith(
  overrides: Partial<ImaLookupState> = {},
): ImaLookupState {
  return { ...emptyImaLookupState(), ...overrides };
}

const listItems: ImaKnowledgeBaseOption[] = [
  { id: "kb-1", name: "Alpha KB", description: "First knowledge base" },
  { id: "kb-2", name: "Beta KB", description: null },
];

function inputAfterLabel(label: string): HTMLInputElement {
  const input = screen
    .getByText(label)
    .parentElement?.querySelector("input");
  if (!(input instanceof HTMLInputElement)) {
    throw new Error(`input for label ${label} not found`);
  }
  return input;
}

describe("ImaConnectionFields credentials block", () => {
  it("shows the account banner instead of fields while engine credentials are used", () => {
    const connection = makeConnection({ accountConfigured: true });
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    expect(
      screen.getByText(
        "Using the IMA credentials configured for this engine in the Knowledge Center.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Client ID")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use other credentials" }));
    expect(connection.setUseOwnCredentials).toHaveBeenCalledWith(true);
  });

  it("keeps the switch-to-own-credentials button disabled while submitting", () => {
    const connection = makeConnection({ accountConfigured: true });
    render(<ImaConnectionFields connection={connection} submitting={true} />);

    expect(
      screen.getByRole("button", { name: "Use other credentials" }),
    ).toBeDisabled();
  });

  it("edits own credentials and offers the way back to engine credentials", () => {
    const connection = makeConnection({
      accountConfigured: true,
      useOwnCredentials: true,
      clientId: "client-a",
      apiKey: "key-a",
    });
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    const clientId = inputAfterLabel("Client ID");
    expect(clientId).toHaveValue("client-a");
    fireEvent.change(clientId, { target: { value: "client-b" } });
    expect(connection.setClientId).toHaveBeenCalledWith("client-b");

    const apiKey = inputAfterLabel("API key");
    expect(apiKey).toHaveAttribute("type", "password");
    expect(apiKey).toHaveValue("key-a");
    fireEvent.change(apiKey, { target: { value: "key-b" } });
    expect(connection.setApiKey).toHaveBeenCalledWith("key-b");

    fireEvent.click(
      screen.getByRole("button", { name: "Use the engine's credentials instead" }),
    );
    expect(connection.setUseOwnCredentials).toHaveBeenCalledWith(false);
  });

  it("disables credential inputs while submitting", () => {
    const connection = makeConnection({ useOwnCredentials: true });
    render(<ImaConnectionFields connection={connection} submitting={true} />);

    expect(inputAfterLabel("Client ID")).toBeDisabled();
    expect(inputAfterLabel("API key")).toBeDisabled();
  });

  it("points credential-less users at IMA and the Knowledge Center preset", () => {
    const connection = makeConnection();
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    expect(
      screen.queryByRole("button", {
        name: "Use the engine's credentials instead",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Set these once for the engine in the Knowledge Center to skip this step next time.",
      ),
    ).toBeInTheDocument();

    const link = screen.getByRole("link", { name: "Open IMA" });
    expect(link).toHaveAttribute("href", "https://ima.qq.com/agent-interface");
    expect(link).toHaveAttribute("target", "_blank");
  });
});

describe("ImaConnectionFields mode selection", () => {
  it("switches between automatic and manual modes", () => {
    const connection = makeConnection();
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    const automatic = screen.getByRole("button", {
      name: "Choose from knowledge base list",
    });
    expect(automatic.className).toContain("border-[var(--primary)]");

    fireEvent.click(
      screen.getByRole("button", { name: "Use knowledge base ID instead" }),
    );
    expect(connection.setMode).toHaveBeenCalledWith("manual");

    fireEvent.click(automatic);
    expect(connection.setMode).toHaveBeenCalledWith("automatic");
  });

  it("disables mode buttons while submitting", () => {
    const connection = makeConnection();
    render(<ImaConnectionFields connection={connection} submitting={true} />);

    expect(
      screen.getByRole("button", { name: "Choose from knowledge base list" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Use knowledge base ID instead" }),
    ).toBeDisabled();
  });
});

describe("ImaConnectionFields automatic lookup", () => {
  it("gates the load button on credentials and forwards reset loads", () => {
    const connection = makeConnection({ credentialsReady: false });
    const view = render(
      <ImaConnectionFields connection={connection} submitting={false} />,
    );
    const load = screen.getByRole("button", {
      name: "Verify and load knowledge bases",
    });
    expect(load).toBeDisabled();

    const ready = makeConnection({ credentialsReady: true });
    view.rerender(<ImaConnectionFields connection={ready} submitting={false} />);
    const loadReady = screen.getByRole("button", {
      name: "Verify and load knowledge bases",
    });
    expect(loadReady).toBeEnabled();
    fireEvent.click(loadReady);
    expect(ready.load).toHaveBeenCalledWith(true);
  });

  it("shows a spinner and keeps the button disabled while loading from empty", () => {
    const connection = makeConnection({
      lookup: lookupWith({ status: "loading" }),
    });
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    const load = screen.getByRole("button", {
      name: "Verify and load knowledge bases",
    });
    expect(load).toBeDisabled();
    expect(load.querySelector("svg.animate-spin")).not.toBeNull();
  });

  it("reports when no knowledge bases are accessible", () => {
    const connection = makeConnection({
      lookup: lookupWith({ status: "empty" }),
    });
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    expect(
      screen.getByText("No accessible knowledge bases found."),
    ).toBeInTheDocument();
  });

  it("lists loaded knowledge bases, highlights the selection and selects on click", () => {
    const connection = makeConnection({
      lookup: lookupWith({
        status: "ready",
        knowledgeBases: listItems,
        selectedId: "kb-1",
      }),
    });
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    const alpha = screen.getByRole("button", { name: /Alpha KB/ });
    expect(alpha.className).toContain("border-[var(--primary)]");
    expect(
      screen.getByText("First knowledge base"),
    ).toBeInTheDocument();
    expect(screen.getByText("Beta KB")).toBeInTheDocument();

    fireEvent.click(alpha);
    expect(connection.select).toHaveBeenCalledWith(listItems[0]);
  });

  it("pages further results through load(false) until the end", () => {
    const connection = makeConnection({
      lookup: lookupWith({
        status: "ready",
        knowledgeBases: listItems,
        selectedId: "kb-1",
        isEnd: false,
      }),
    });
    const view = render(
      <ImaConnectionFields connection={connection} submitting={false} />,
    );

    const more = screen.getByRole("button", { name: "Load more" });
    expect(more).toBeEnabled();
    fireEvent.click(more);
    expect(connection.load).toHaveBeenCalledWith(false);

    view.rerender(
      <ImaConnectionFields
        connection={makeConnection({
          lookup: lookupWith({
            status: "loading",
            knowledgeBases: listItems,
            selectedId: "kb-1",
            isEnd: false,
          }),
        })}
        submitting={false}
      />,
    );
    expect(screen.getByRole("button", { name: "Load more" })).toBeDisabled();

    view.rerender(
      <ImaConnectionFields
        connection={makeConnection({
          lookup: lookupWith({
            status: "ready",
            knowledgeBases: listItems,
            selectedId: "kb-1",
            isEnd: true,
          }),
        })}
        submitting={false}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Load more" }),
    ).not.toBeInTheDocument();
  });
});

describe("ImaConnectionFields manual mode", () => {
  it("edits the id and probes once an id and credentials exist", () => {
    const connection = makeConnection({
      mode: "manual",
      manualKnowledgeBaseId: "",
    });
    const view = render(
      <ImaConnectionFields connection={connection} submitting={false} />,
    );

    expect(
      screen.getByRole("button", { name: "Verify knowledge base" }),
    ).toBeDisabled();

    fireEvent.change(inputAfterLabel("Knowledge Base ID"), {
      target: { value: "kb-9" },
    });
    expect(connection.setManualKnowledgeBaseId).toHaveBeenCalledWith("kb-9");

    const readyConnection = makeConnection({
      mode: "manual",
      manualKnowledgeBaseId: "kb-9",
    });
    view.rerender(
      <ImaConnectionFields connection={readyConnection} submitting={false} />,
    );
    const ready = screen.getByRole("button", {
      name: "Verify knowledge base",
    });
    expect(ready).toBeEnabled();
    fireEvent.click(ready);
    expect(readyConnection.probe).toHaveBeenCalledTimes(1);
  });

  it("keeps the verify button disabled while submitting or loading", () => {
    const view = render(
      <ImaConnectionFields
        connection={makeConnection({
          mode: "manual",
          manualKnowledgeBaseId: "kb-9",
        })}
        submitting={true}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Verify knowledge base" }),
    ).toBeDisabled();

    view.rerender(
      <ImaConnectionFields
        connection={makeConnection({
          mode: "manual",
          manualKnowledgeBaseId: "kb-9",
          lookup: lookupWith({ status: "loading" }),
        })}
        submitting={false}
      />,
    );
    const button = screen.getByRole("button", {
      name: "Verify knowledge base",
    });
    expect(button).toBeDisabled();
    expect(button.querySelector("svg.animate-spin")).not.toBeNull();
  });

  it("shows the verified knowledge base details after a successful probe", () => {
    const connection = makeConnection({
      mode: "manual",
      manualKnowledgeBaseId: "kb-9",
      manualProbe: {
        knowledge_base_id: "kb-9",
        ok: true,
        credentials_ok: true,
        knowledge_base_name: "Manual KB",
        description: "A manual knowledge base",
        error: null,
      },
    });
    render(<ImaConnectionFields connection={connection} submitting={false} />);

    expect(screen.getByText("Knowledge base verified")).toBeInTheDocument();
    expect(screen.getByText("Manual KB")).toBeInTheDocument();
    expect(screen.getByText("A manual knowledge base")).toBeInTheDocument();
  });

  it("surfaces the probe error, falling back to a generic message", () => {
    const view = render(
      <ImaConnectionFields
        connection={makeConnection({
          mode: "manual",
          manualKnowledgeBaseId: "kb-9",
          manualProbe: {
            knowledge_base_id: "kb-9",
            ok: false,
            credentials_ok: false,
            knowledge_base_name: null,
            description: null,
            error: "Invalid credentials",
          },
        })}
        submitting={false}
      />,
    );
    expect(screen.getByText("Invalid credentials")).toBeInTheDocument();

    view.rerender(
      <ImaConnectionFields
        connection={makeConnection({
          mode: "manual",
          manualKnowledgeBaseId: "kb-9",
          manualProbe: {
            knowledge_base_id: "kb-9",
            ok: false,
            credentials_ok: false,
            knowledge_base_name: null,
            description: null,
            error: null,
          },
        })}
        submitting={false}
      />,
    );
    expect(screen.getByText("Could not connect")).toBeInTheDocument();
  });
});
