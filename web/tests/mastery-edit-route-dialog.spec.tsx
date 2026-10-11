import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { EditTopicRouteDialog } from "@/components/space/learning/EditTopicRouteDialog";
import { initI18n } from "@/i18n/init";
import type {
  MapKnowledgePoint,
  MapModule,
  ModuleInit,
  MasteryTopic,
} from "@/lib/learning-api";

initI18n("en");

const mocks = vi.hoisted(() => ({
  updateMap: vi.fn(),
}));

vi.mock("@/lib/learning-api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  updateMasteryTopicMap: mocks.updateMap,
}));

const LEGACY_MODULE_ID = "topic_m0";
const LEGACY_POINT_IDS = Array.from(
  { length: 8 },
  (_, index) => `${LEGACY_MODULE_ID}-kp-${index}`,
);

function mapPoint(id: string, name: string): MapKnowledgePoint {
  return {
    id,
    name,
    type: "concept",
    prerequisite_ids: [],
    topic_source_ids: [],
    status: "new",
    mastery: 0,
    mastery_source: "",
    override_note: "",
  };
}

function legacyModule(): MapModule {
  return {
    id: LEGACY_MODULE_ID,
    name: "Legacy region",
    objective: "",
    order: 0,
    mastered: 0,
    total: LEGACY_POINT_IDS.length,
    knowledge_points: LEGACY_POINT_IDS.map((id, index) =>
      mapPoint(id, `Objective ${index + 1}`),
    ),
  };
}

function topic(overrides: Partial<MasteryTopic> = {}): MasteryTopic {
  return {
    path_id: "path-1",
    name: "Linear Algebra Basics",
    metadata: {
      path_id: "path-1",
      goal: "learn the basics",
      description: "an older saved route",
      emoji: "",
      map_seed: 0,
      status: "active",
      created_at: 0,
      updated_at: 0,
    },
    sources: [],
    path_revision: 1,
    next: {
      action: "study",
      knowledge_point_id: LEGACY_POINT_IDS[0],
      knowledge_point_name: "Objective 1",
      knowledge_point_type: "concept",
      status: "new",
      gate: "qualitative",
      mastery: 0,
      threshold: 1,
      reason: "",
      forgetting_risk: 0,
      pending_prompt: "",
      session_id: "",
    },
    map: {
      name: "Linear Algebra Basics",
      counts: { mastered: 0, learning: 0, new: 8, total: 8 },
      due_reviews: 0,
      complete: false,
      modules: [legacyModule()],
    },
    reviews: [],
    learner_profile: null,
    session_count: 0,
    updated_at: 0,
    ...overrides,
  };
}

const savedTopic = topic({ path_revision: 2 });

function renderDialog(current: MasteryTopic) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  const returnFocusRef = { current: null as HTMLElement | null };
  const view = render(
    <EditTopicRouteDialog
      topic={current}
      onClose={onClose}
      onSaved={onSaved}
      returnFocusRef={returnFocusRef}
    />,
  );
  return { view, onClose, onSaved };
}

beforeEach(() => {
  mocks.updateMap.mockReset();
  mocks.updateMap.mockResolvedValue(savedTopic);
});

describe("EditTopicRouteDialog objective-count editing", () => {
  it("saves a legacy region with every stored objective intact", async () => {
    const user = userEvent.setup();
    const { onSaved } = renderDialog(topic());

    expect(
      screen.getByLabelText("Knowledge point 8 name in module 1"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(savedTopic));
    expect(mocks.updateMap).toHaveBeenCalledTimes(1);
    const [pathId, modules] = mocks.updateMap.mock.calls[0] as [
      string,
      ModuleInit[],
    ];
    expect(pathId).toBe("path-1");
    expect(modules).toHaveLength(1);
    expect(modules[0].id).toBe(LEGACY_MODULE_ID);
    expect(modules[0].order).toBe(0);
    expect(modules[0].knowledge_points.map((item) => item.id)).toEqual(
      LEGACY_POINT_IDS,
    );
    expect(
      modules[0].knowledge_points.every(
        (item) => item.module_id === LEGACY_MODULE_ID,
      ),
    ).toBe(true);
  });

  it("passes an edited objective count through without trimming it", async () => {
    const user = userEvent.setup();
    renderDialog(topic());

    await user.click(screen.getByRole("button", { name: "Add knowledge point" }));
    expect(
      screen.getByLabelText("Knowledge point 9 name in module 1"),
    ).toHaveValue("New knowledge point");

    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(mocks.updateMap).toHaveBeenCalled());
    const [, modules] = mocks.updateMap.mock.calls[0] as [string, ModuleInit[]];
    const points = modules[0].knowledge_points;
    expect(points).toHaveLength(9);
    expect(points.slice(0, 8).map((item) => item.id)).toEqual(
      LEGACY_POINT_IDS,
    );
    expect(points[8].id).toMatch(/^draft_waypoint_/);
    expect(points[8].module_id).toBe(LEGACY_MODULE_ID);
  });

  it("stops saving while a waypoint name is blank", async () => {
    const user = userEvent.setup();
    renderDialog(topic());

    const nameInput = screen.getByLabelText("Knowledge point 3 name in module 1");
    await user.clear(nameInput);

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(mocks.updateMap).not.toHaveBeenCalled();
  });

  it("disables saving until the map write settles", async () => {
    const user = userEvent.setup();
    let resolveSave: (value: MasteryTopic) => void = () => {};
    mocks.updateMap.mockImplementationOnce(
      () =>
        new Promise<MasteryTopic>((resolve) => {
          resolveSave = resolve;
        }),
    );
    renderDialog(topic());

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();

    resolveSave(savedTopic);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save" })).toBeEnabled(),
    );
  });

  it("surfaces a failed save and lets the learner retry", async () => {
    const user = userEvent.setup();
    mocks.updateMap.mockRejectedValueOnce(new Error("map refused"));
    renderDialog(topic());

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("map refused")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("falls back to a plain failure line for non-error rejections", async () => {
    const user = userEvent.setup();
    mocks.updateMap.mockRejectedValueOnce("nope");
    renderDialog(topic());

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Save failed")).toBeInTheDocument();
  });

  it("closes from the footer and the header without saving", async () => {
    const user = userEvent.setup();
    const { onClose } = renderDialog(topic());

    expect(screen.getByRole("dialog", { name: "Edit modules" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
    expect(mocks.updateMap).not.toHaveBeenCalled();
  });
});
