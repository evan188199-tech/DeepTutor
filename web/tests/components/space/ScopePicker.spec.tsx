import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ScopePicker, {
  type ScopePickerProps,
} from "@/components/space/ScopePicker";
import type { SelectGroup, SessionRef } from "@/lib/chat-import";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: translate }),
}));

function translate(key: string, params?: Record<string, unknown>) {
  if (!params) return key;
  return key.replace(/\{\{(\w+)\}\}/g, (_match, name: string) =>
    String(params[name] ?? ""),
  );
}

function sessionRef(externalId: string, title: string, cwd = "/repo/a") {
  return {
    externalId,
    provisionalTitle: title,
    cwd,
    date: "2026-01-02",
    lastModified: Date.parse("2026-01-02T10:00:00Z"),
    sizeBytes: 128,
    handle: {} as FileSystemFileHandle,
  } satisfies SessionRef;
}

function makeGroup(
  key: string,
  label: string,
  sessions: SessionRef[],
  sublabel?: string,
): SelectGroup {
  return sublabel ? { key, label, sublabel, sessions } : { key, label, sessions };
}

function baseProps(overrides?: Partial<ScopePickerProps>): ScopePickerProps {
  return {
    groups: [
      makeGroup("/repo/a", "Alpha", [
        sessionRef("s1", "Alpha chat one"),
        sessionRef("s2", "Alpha chat two"),
      ], "/repo/a"),
      makeGroup("/repo/b", "Beta", [sessionRef("s3", "Beta chat", "/repo/b")], "/repo/b"),
    ],
    unit: "projects",
    selected: new Set<string>(),
    onToggle: vi.fn(),
    onSelectAll: vi.fn(),
    onClearAll: vi.fn(),
    lang: "en",
    ...overrides,
  };
}

function cardOf(label: string): HTMLElement {
  const card = screen.getByText(label).closest(".overflow-hidden");
  expect(card).not.toBeNull();
  return card as HTMLElement;
}

describe("ScopePicker", () => {
  let props: ScopePickerProps;

  beforeEach(() => {
    props = baseProps();
  });

  it("renders project groups with sublabels, per-group chat counts, and the totals line", () => {
    render(<ScopePicker {...props} />);
    expect(screen.getByText("2 projects · 3 conversations")).toBeTruthy();
    expect(screen.getByText("Alpha")).toBeTruthy();
    expect(screen.getByText("/repo/a")).toBeTruthy();
    expect(screen.getByText("Beta")).toBeTruthy();
    expect(screen.getByText("2 chats")).toBeTruthy();
    expect(screen.getByText("1 chats")).toBeTruthy();
  });

  it("marks preselected groups as pressed and reports the selected conversation count", () => {
    render(<ScopePicker {...props} selected={new Set(["/repo/a"])} />);
    expect(
      within(cardOf("Alpha")).getByRole("button", { name: "Select" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(cardOf("Beta")).getByRole("button", { name: "Select" }),
    ).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("· 2 selected")).toBeTruthy();
  });

  it("renders the zero-state totals with no selected badge and no group cards", () => {
    render(<ScopePicker {...props} groups={[]} />);
    expect(screen.getByText("0 projects · 0 conversations")).toBeTruthy();
    expect(screen.queryByText(/selected/)).toBeNull();
    expect(screen.queryByText("Alpha")).toBeNull();
  });

  it("toggling a group checkbox calls onToggle with that group key", () => {
    render(<ScopePicker {...props} />);
    fireEvent.click(
      within(cardOf("Beta")).getByRole("button", { name: "Select" }),
    );
    expect(props.onToggle).toHaveBeenCalledTimes(1);
    expect(props.onToggle).toHaveBeenCalledWith("/repo/b");
  });

  it("select-all and clear buttons drive the bulk selection callbacks", () => {
    render(<ScopePicker {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(props.onSelectAll).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(props.onClearAll).toHaveBeenCalledTimes(1);
  });

  it("expanding a group previews its sessions read-only and collapsing hides them", () => {
    render(
      <ScopePicker
        {...props}
        groups={[
          makeGroup("/repo/a", "Alpha", [
            sessionRef("s1", "Alpha chat one"),
            sessionRef("s2", ""),
          ]),
        ]}
      />,
    );
    expect(screen.queryByText("Alpha chat one")).toBeNull();
    fireEvent.click(screen.getByText("Alpha"));
    expect(screen.getByText("Alpha chat one")).toBeTruthy();
    expect(screen.getByText("Untitled conversation")).toBeTruthy();
    fireEvent.click(screen.getByText("Alpha"));
    expect(screen.queryByText("Alpha chat one")).toBeNull();
  });

  it("date units render localized day labels and fall back to the raw key when unparseable", () => {
    render(
      <ScopePicker
        {...props}
        unit="dates"
        groups={[
          makeGroup("2026-01-02", "2026-01-02", [
            sessionRef("s1", "Alpha chat one"),
          ]),
          makeGroup("not-a-date", "not-a-date", []),
        ]}
      />,
    );
    expect(screen.getByText("2 days · 1 conversations")).toBeTruthy();
    expect(screen.getByText(/Jan/)).toBeTruthy();
    expect(screen.getByText(/2026/)).toBeTruthy();
    expect(screen.getByText("not-a-date")).toBeTruthy();
  });
});
