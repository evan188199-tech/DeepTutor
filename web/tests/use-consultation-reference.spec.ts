import { act, renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { useConsultationReference } from "@/hooks/useConsultationReference";
import { getPartnerGroup } from "@/lib/partner-groups-api";
import type { PartnerGroup } from "@/lib/partner-groups-api";
import { getPartner } from "@/lib/partners-api";
import type { PartnerInfo } from "@/lib/partners-api";

vi.mock("@/lib/partners-api", () => ({
  getPartner: vi.fn(),
}));

vi.mock("@/lib/partner-groups-api", () => ({
  getPartnerGroup: vi.fn(),
}));

function partnerGroupEntity(name: string): PartnerGroup {
  return {
    group_id: "",
    owner_id: "",
    name,
    description: "",
    member_ids: [],
    members: [],
    discussion_mode: "panel_parallel",
    shared_memory: "whiteboard",
    emoji: "",
    color: "",
    created_at: "",
    updated_at: "",
    version: 1,
  };
}

function partnerEntity(name: string): PartnerInfo {
  return {
    partner_id: "",
    name,
    description: "",
    channels: [],
    running: false,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.mocked(getPartner).mockResolvedValue(partnerEntity("Named Partner"));
  vi.mocked(getPartnerGroup).mockResolvedValue(partnerGroupEntity("Named Group"));
});

it("returns null and performs no lookups without a usable reference", () => {
  const missing = renderHook(() => useConsultationReference(undefined));
  expect(missing.result.current).toBeNull();

  const empty = renderHook(() => useConsultationReference({}));
  expect(empty.result.current).toBeNull();

  const nonString = renderHook(() =>
    useConsultationReference({
      partner_discussion_group_id: "",
      consult_partner_id: 42,
    }),
  );
  expect(nonString.result.current).toBeNull();

  const blank = renderHook(() =>
    useConsultationReference({
      partner_discussion_group_id: "",
      consult_partner_id: "",
    }),
  );
  expect(blank.result.current).toBeNull();

  expect(getPartner).not.toHaveBeenCalled();
  expect(getPartnerGroup).not.toHaveBeenCalled();
});

it("resolves a partner discussion group reference to its group name", async () => {
  const { result } = renderHook(() =>
    useConsultationReference({ partner_discussion_group_id: "g1" }),
  );

  expect(getPartnerGroup).toHaveBeenCalledWith("g1");
  expect(getPartner).not.toHaveBeenCalled();
  expect(result.current).toEqual({ id: "g1", kind: "partner_group", name: "g1" });

  await act(async () => {});

  expect(result.current).toEqual({
    id: "g1",
    kind: "partner_group",
    name: "Named Group",
  });
});

it("resolves a single partner reference to its partner name", async () => {
  const { result } = renderHook(() =>
    useConsultationReference({ consult_partner_id: "p1" }),
  );

  expect(getPartner).toHaveBeenCalledWith("p1");
  expect(getPartnerGroup).not.toHaveBeenCalled();
  expect(result.current).toEqual({ id: "p1", kind: "partner", name: "p1" });

  await act(async () => {});

  expect(result.current).toEqual({
    id: "p1",
    kind: "partner",
    name: "Named Partner",
  });
});

it("prefers the discussion group when both reference ids are configured", () => {
  renderHook(() =>
    useConsultationReference({
      partner_discussion_group_id: "g1",
      consult_partner_id: "p1",
    }),
  );

  expect(getPartnerGroup).toHaveBeenCalledWith("g1");
  expect(getPartner).not.toHaveBeenCalled();
});

it("falls back to the partner when the group id is blank or not a string", () => {
  renderHook(() =>
    useConsultationReference({
      partner_discussion_group_id: "",
      consult_partner_id: "p1",
    }),
  );
  expect(getPartner).toHaveBeenCalledWith("p1");
  expect(getPartnerGroup).not.toHaveBeenCalled();

  renderHook(() =>
    useConsultationReference({
      partner_discussion_group_id: 99,
      consult_partner_id: "p2",
    }),
  );
  expect(getPartner).toHaveBeenCalledWith("p2");
});

it("keeps the stored identity when the lookup fails", async () => {
  vi.mocked(getPartnerGroup).mockRejectedValueOnce(new Error("deleted"));

  const { result } = renderHook(() =>
    useConsultationReference({ partner_discussion_group_id: "g1" }),
  );

  await act(async () => {});

  expect(result.current).toEqual({ id: "g1", kind: "partner_group", name: "g1" });
});

it("ignores a stale resolution after the reference id changes", async () => {
  const stale = deferred<PartnerGroup>();
  const fresh = deferred<PartnerGroup>();
  vi.mocked(getPartnerGroup)
    .mockReturnValueOnce(stale.promise)
    .mockReturnValueOnce(fresh.promise);

  const { result, rerender } = renderHook(
    ({ id }: { id: string }) =>
      useConsultationReference({ partner_discussion_group_id: id }),
    { initialProps: { id: "g1" } },
  );

  rerender({ id: "g2" });

  expect(getPartnerGroup).toHaveBeenNthCalledWith(1, "g1");
  expect(getPartnerGroup).toHaveBeenNthCalledWith(2, "g2");

  stale.resolve(partnerGroupEntity("Stale Group"));
  await act(async () => {});

  expect(result.current).toEqual({ id: "g2", kind: "partner_group", name: "g2" });

  fresh.resolve(partnerGroupEntity("Fresh Group"));
  await act(async () => {});

  expect(result.current).toEqual({
    id: "g2",
    kind: "partner_group",
    name: "Fresh Group",
  });
});

it("drops the in-flight group lookup when switching to a partner reference", async () => {
  const pendingGroup = deferred<PartnerGroup>();
  vi.mocked(getPartnerGroup).mockReturnValueOnce(pendingGroup.promise);

  const { result, rerender } = renderHook(
    ({ config }: { config: Record<string, unknown> }) =>
      useConsultationReference(config),
    { initialProps: { config: { partner_discussion_group_id: "g1" } } },
  );

  rerender({ config: { consult_partner_id: "p1" } });

  pendingGroup.resolve(partnerGroupEntity("Late Group"));
  await act(async () => {});

  expect(result.current).toEqual({
    id: "p1",
    kind: "partner",
    name: "Named Partner",
  });
});

it("falls back to the stored id when switching back to a previously resolved reference", async () => {
  const { result, rerender } = renderHook(
    ({ id }: { id: string }) =>
      useConsultationReference({ partner_discussion_group_id: id }),
    { initialProps: { id: "g1" } },
  );

  await act(async () => {});
  expect(result.current).toEqual({
    id: "g1",
    kind: "partner_group",
    name: "Named Group",
  });

  rerender({ id: "g2" });
  await act(async () => {});
  expect(result.current).toEqual({
    id: "g2",
    kind: "partner_group",
    name: "Named Group",
  });

  rerender({ id: "g1" });
  expect(getPartnerGroup).toHaveBeenLastCalledWith("g1");
  expect(result.current).toEqual({ id: "g1", kind: "partner_group", name: "g1" });
});

it("does not resolve after unmount", async () => {
  const pending = deferred<PartnerGroup>();
  vi.mocked(getPartnerGroup).mockReturnValueOnce(pending.promise);

  const { unmount } = renderHook(() =>
    useConsultationReference({ partner_discussion_group_id: "g1" }),
  );

  unmount();

  pending.resolve(partnerGroupEntity("Late Group"));
  await act(async () => {});

  // A state update after unmount would surface as a React act failure; reaching
  // this point means the effect cleanup dropped the in-flight resolution.
  expect(getPartnerGroup).toHaveBeenCalledWith("g1");
});
