import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { PartnerDraftCard } from "@/components/chat/home/PartnerDraftCard";
import type { PartnerDraftData } from "@/lib/partner-draft";
import { confirmPartnerDraft, type PartnerInfo } from "@/lib/partners-api";
import { initI18n } from "@/i18n/init";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));
vi.mock("@/lib/partners-api", () => ({
  confirmPartnerDraft: vi.fn(),
}));

initI18n("en");

const draft = (overrides: Partial<PartnerDraftData> = {}): PartnerDraftData => ({
  draft_id: "d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9",
  owner_id: "user-1",
  name: "Study Buddy",
  description: "A friendly study companion",
  soul: "You are a patient tutor.",
  language: "en",
  emoji: "🤝",
  color: "#6366f1",
  status: "pending",
  created_partner_id: "",
  version: 1,
  ...overrides,
});

const confirmed = (partnerId: string): PartnerInfo => ({
  partner_id: partnerId,
  name: "Study Buddy",
  description: "A friendly study companion",
  channels: [],
});

const renderCard = (data = draft()) => render(<PartnerDraftCard data={data} />);

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(confirmPartnerDraft).mockResolvedValue(confirmed("partner-9"));
});

it("renders the draft summary with the soul profile collapsed by default", () => {
  renderCard();

  expect(screen.getByText("Partner draft")).toBeInTheDocument();
  expect(screen.getByText("Study Buddy")).toBeInTheDocument();
  expect(screen.getByText("A friendly study companion")).toBeInTheDocument();
  expect(screen.getByText("Soul profile")).toBeInTheDocument();
  expect(
    screen.queryByText("You are a patient tutor."),
  ).not.toBeInTheDocument();
  expect(screen.getByText("Nothing is created until you confirm")).toBeInTheDocument();

  const confirmButton = screen.getByRole("button", { name: /Confirm & create/ });
  expect(confirmButton).toBeEnabled();
  expect(confirmPartnerDraft).not.toHaveBeenCalled();
});

it("expands and collapses the soul profile from the view mode toggle", () => {
  renderCard();

  fireEvent.click(screen.getByRole("button", { name: /Soul profile/ }));
  expect(screen.getByText("You are a patient tutor.")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Soul profile/ }));
  expect(
    screen.queryByText("You are a patient tutor."),
  ).not.toBeInTheDocument();
});

it("edits draft fields, returns to view mode, and sends the edited values on confirm", async () => {
  const data = draft();
  renderCard(data);

  fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
  fireEvent.change(screen.getByLabelText("Partner name"), {
    target: { value: "Math Coach" },
  });
  fireEvent.change(screen.getByLabelText("Language"), {
    target: { value: "zh" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Done/ }));

  expect(screen.getByText("Math Coach")).toBeInTheDocument();
  expect(screen.queryByLabelText("Partner name")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /Confirm & create/ }));

  await waitFor(() => {
    expect(confirmPartnerDraft).toHaveBeenCalledOnce();
  });
  expect(confirmPartnerDraft).toHaveBeenCalledWith(data.draft_id, {
    name: "Math Coach",
    description: "A friendly study companion",
    soul: "You are a patient tutor.",
    language: "zh",
    emoji: "🤝",
    color: "#6366f1",
    start: true,
  });
});

it("creates the partner on confirm and switches to the created state", async () => {
  const data = draft();
  renderCard(data);

  fireEvent.click(screen.getByRole("button", { name: /Confirm & create/ }));

  expect(await screen.findByRole("button", { name: /Open partner/ })).toBeInTheDocument();
  expect(screen.getByText("Partner created")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Edit/ })).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /Confirm & create/ }),
  ).not.toBeInTheDocument();
  expect(confirmPartnerDraft).toHaveBeenCalledWith(
    data.draft_id,
    expect.objectContaining({ start: true }),
  );
});

it("opens the created partner through an encoded detail route", () => {
  renderCard(draft({ status: "created", created_partner_id: "partner 9" }));

  fireEvent.click(screen.getByRole("button", { name: /Open partner/ }));
  expect(push).toHaveBeenCalledExactlyOnceWith("/partners/partner%209");
});

it("shows the error message and recovers the confirm action when creation fails", async () => {
  vi.mocked(confirmPartnerDraft).mockRejectedValueOnce(
    new Error("partner service unavailable"),
  );
  renderCard();

  fireEvent.click(screen.getByRole("button", { name: /Confirm & create/ }));

  expect(await screen.findByText("partner service unavailable")).toBeInTheDocument();
  expect(screen.queryByText("Partner created")).not.toBeInTheDocument();
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /Confirm & create/ })).toBeEnabled();
  });
  expect(screen.queryByRole("button", { name: /Open partner/ })).not.toBeInTheDocument();
});

it("falls back to the generic failure message when the rejection is not an Error", async () => {
  vi.mocked(confirmPartnerDraft).mockRejectedValueOnce("boom");
  renderCard();

  fireEvent.click(screen.getByRole("button", { name: /Confirm & create/ }));

  expect(await screen.findByText("Failed to create partner")).toBeInTheDocument();
});

it("disables confirming while the name or soul is blank", () => {
  renderCard();

  fireEvent.click(screen.getByRole("button", { name: /Edit/ }));
  fireEvent.change(screen.getByLabelText("Partner name"), {
    target: { value: "   " },
  });
  expect(screen.getByRole("button", { name: /Confirm & create/ })).toBeDisabled();

  fireEvent.change(screen.getByLabelText("Partner name"), {
    target: { value: "Renamed" },
  });
  fireEvent.change(screen.getByLabelText("Soul profile"), {
    target: { value: "  " },
  });
  expect(screen.getByRole("button", { name: /Confirm & create/ })).toBeDisabled();
});

it("shows an in-flight state while the creation request is pending", async () => {
  let resolveCreate: (partner: PartnerInfo) => void = () => {};
  vi.mocked(confirmPartnerDraft).mockImplementation(
    () =>
      new Promise<PartnerInfo>((resolve) => {
        resolveCreate = resolve;
      }),
  );
  renderCard();

  fireEvent.click(screen.getByRole("button", { name: /Confirm & create/ }));

  const creating = await screen.findByRole("button", { name: /Creating…/ });
  expect(creating).toBeDisabled();

  resolveCreate(confirmed("partner-9"));
  expect(await screen.findByRole("button", { name: /Open partner/ })).toBeInTheDocument();
});
