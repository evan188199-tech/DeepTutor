import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  AddCard,
  CardAction,
  ModelCard,
  ProfileCard,
  UseRow,
} from "@/components/settings/ModelCards";
import type {
  CatalogModel,
  CatalogProfile,
} from "@/features/settings/store/SettingsStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, args?: any) =>
      key.replace(/{{(\w+)}}/g, (_, name) => String(args?.[name] ?? name)),
  }),
}));

const model: CatalogModel = {
  id: "m1",
  name: "Chat model",
  model: "gpt-test",
  context_window: "65536",
};

const profile: CatalogProfile = {
  id: "p1",
  name: "OpenAI",
  binding: "openai",
  base_url: "https://api.openai.com/v1",
  api_key: "sk-test",
  api_version: "",
  models: [
    model,
    { id: "m2", name: "Second", model: "gpt-other" },
  ],
};

type CardCallbacks = ReturnType<typeof cardCallbacks>;

function cardCallbacks() {
  return {
    onRenameChange: vi.fn(),
    onRenameCommit: vi.fn(),
    onRenameCancel: vi.fn(),
    onRenameStart: vi.fn(),
    onToggleExpand: vi.fn(),
    onUse: vi.fn(),
    onDelete: vi.fn(),
  };
}

function renderModelCard(
  overrides: Partial<Parameters<typeof ModelCard>[0]> = {},
  callbacks: CardCallbacks = cardCallbacks(),
) {
  const view = render(
    <ModelCard
      model={model}
      service="llm"
      language="en"
      index={0}
      inUse={false}
      expanded={false}
      renaming={false}
      renameValue=""
      {...callbacks}
      {...overrides}
    />,
  );
  return { view, callbacks };
}

describe("ModelCards settings components", () => {
  it("AddCard triggers its click handler for adding a card", () => {
    const onClick = vi.fn();
    render(<AddCard label="Add provider" onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Add provider" }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("CardAction stays inert while disabled and fires when enabled", () => {
    const onClick = vi.fn();
    const { rerender } = render(
      <CardAction onClick={onClick} disabled>
        Sync models
      </CardAction>,
    );
    const button = screen.getByRole("button", { name: "Sync models" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();

    rerender(
      <CardAction onClick={onClick}>Sync models</CardAction>,
    );
    expect(button).toBeEnabled();
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("ModelCard delete stops propagation so it never expands the card", () => {
    const { callbacks } = renderModelCard();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(callbacks.onDelete).toHaveBeenCalledTimes(1);
    expect(callbacks.onToggleExpand).not.toHaveBeenCalled();
  });

  it("ModelCard double-click starts a rename and the draft flows through commit", () => {
    const { callbacks } = renderModelCard();
    fireEvent.doubleClick(screen.getByText("Chat model"));
    expect(callbacks.onRenameStart).toHaveBeenCalledTimes(1);

    const { callbacks: editing } = renderModelCard(
      { renaming: true, renameValue: "Renamed" },
    );
    const input = screen.getByDisplayValue("Renamed");
    fireEvent.change(input, { target: { value: "Renamed again" } });
    expect(editing.onRenameChange).toHaveBeenCalledWith("Renamed again");
    fireEvent.blur(input);
    expect(editing.onRenameCommit).toHaveBeenCalledTimes(1);
    expect(editing.onRenameCancel).not.toHaveBeenCalled();
  });

  it("ModelCard Escape cancels an in-flight rename without committing", () => {
    const { callbacks } = renderModelCard({
      renaming: true,
      renameValue: "Half typed",
    });
    fireEvent.keyDown(screen.getByDisplayValue("Half typed"), {
      key: "Escape",
    });
    expect(callbacks.onRenameCancel).toHaveBeenCalledTimes(1);
    expect(callbacks.onRenameCommit).not.toHaveBeenCalled();
  });

  it("ModelCard marks the default: select button when free, badge when in use", () => {
    const first = renderModelCard();
    fireEvent.click(screen.getByRole("button", { name: "Set as default" }));
    expect(first.callbacks.onUse).toHaveBeenCalledTimes(1);
    expect(first.callbacks.onToggleExpand).not.toHaveBeenCalled();
    first.view.unmount();

    renderModelCard({ inUse: true });
    expect(screen.getByText("Default model")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Set as default" }),
    ).not.toBeInTheDocument();
  });

  it("ModelCard expands on click and on Enter, and flags the editing state", () => {
    const { callbacks, view } = renderModelCard();
    const shell = view.container.querySelector<HTMLElement>('[role="button"]');
    expect(shell).not.toBeNull();
    fireEvent.click(shell!);
    expect(callbacks.onToggleExpand).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(shell!, { key: "Enter" });
    expect(callbacks.onToggleExpand).toHaveBeenCalledTimes(2);

    renderModelCard({ expanded: true });
    expect(screen.getByText("Configuring")).toBeInTheDocument();
  });

  it("ModelCard derives per-service detail and falls back to a numbered name", () => {
    renderModelCard({
      model: { ...model, name: "", model: "" },
      index: 1,
    });
    expect(screen.getByText("Model 2")).toBeInTheDocument();
    expect(screen.getByText("No model id yet")).toBeInTheDocument();

    renderModelCard({
      model: { id: "e1", name: "Emb", model: "emb-test", dimension: "768" },
      service: "embedding",
    });
    expect(screen.getByText("768 dim")).toBeInTheDocument();

    renderModelCard({
      model: { id: "t1", name: "Voice", model: "tts-test", voice: "alloy" },
      service: "tts",
    });
    expect(screen.getByText("alloy")).toBeInTheDocument();
  });

  it("UseRow falls back to generic Select/Selected labels", () => {
    const onUse = vi.fn();
    const { rerender } = render(<UseRow inUse={false} onUse={onUse} />);
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    expect(onUse).toHaveBeenCalledTimes(1);

    rerender(<UseRow inUse={true} onUse={onUse} />);
    expect(screen.getByText("Selected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select" })).not.toBeInTheDocument();
  });

  it("ProfileCard opens on click, renames, and counts its models", () => {
    const callbacks = {
      ...cardCallbacks(),
      onOpen: vi.fn(),
    };
    render(
      <ProfileCard
        profile={profile}
        service="llm"
        inUse={false}
        open={false}
        renaming={false}
        renameValue=""
        {...callbacks}
      />,
    );
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("2 models")).toBeInTheDocument();
    expect(screen.getByText("api.openai.com/v1")).toBeInTheDocument();

    const toggle = screen.getByRole("button", { expanded: false });
    fireEvent.click(toggle);
    expect(callbacks.onOpen).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(callbacks.onRenameStart).toHaveBeenCalledTimes(1);
  });

  it("ProfileCard shows Select for search and a check for the in-use llm", () => {
    const callbacks = {
      ...cardCallbacks(),
      onOpen: vi.fn(),
    };
    const { rerender } = render(
      <ProfileCard
        profile={{ ...profile, base_url: "" }}
        service="search"
        inUse={false}
        open={false}
        renaming={false}
        renameValue=""
        {...callbacks}
      />,
    );
    expect(screen.getByText("Provider default endpoint")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select" }));
    expect(callbacks.onUse).toHaveBeenCalledTimes(1);

    rerender(
      <ProfileCard
        profile={profile}
        service="llm"
        inUse={true}
        open={false}
        renaming={false}
        renameValue=""
        {...callbacks}
      />,
    );
    expect(screen.getByLabelText("Selected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select" })).not.toBeInTheDocument();
  });
});
