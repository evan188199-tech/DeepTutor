import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import KbIndexFailureBanner from "@/components/knowledge/KbIndexFailureBanner";
import type { KnowledgeBase } from "@/lib/knowledge-helpers";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

function kb(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return { name: "papers", ...overrides } as KnowledgeBase;
}

describe("KbIndexFailureBanner", () => {
  it("renders nothing for a healthy knowledge base", () => {
    const { container } = render(
      <KbIndexFailureBanner kb={kb({ status: "ready" })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when status is missing or not an error", () => {
    const { container } = render(
      <KbIndexFailureBanner kb={kb({ status: "indexing" })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the stored error message when one exists", () => {
    render(
      <KbIndexFailureBanner
        kb={kb({
          status: "error",
          progress: { error: "disk full while writing index" },
        })}
      />,
    );
    expect(
      screen.getByText("disk full while writing index"),
    ).toBeInTheDocument();
  });

  it("falls back to the generic guidance text without a stored message", () => {
    render(<KbIndexFailureBanner kb={kb({ status: "error" })} />);
    expect(
      screen.getByText(
        "Indexing failed. Review the error details, update the configuration if needed, then retry.",
      ),
    ).toBeInTheDocument();
  });

  it("reads the error from stored statistics when live progress is empty", () => {
    render(
      <KbIndexFailureBanner
        kb={kb({
          status: "error",
          statistics: { status: "error", progress: { error: "stale failure" } },
        })}
      />,
    );
    expect(screen.getByText("stale failure")).toBeInTheDocument();
  });

  it("links to model settings when the failure code needs a completion model change", () => {
    render(
      <KbIndexFailureBanner
        kb={kb({
          status: "error",
          progress: { error_code: "indexing_model_unavailable" },
        })}
      />,
    );
    const link = screen.getByRole("link", { name: "Open model settings" });
    expect(link).toHaveAttribute("href", "/settings#models");
  });

  it("links to embedding settings when the failure code needs an embedding change", () => {
    render(
      <KbIndexFailureBanner
        kb={kb({
          status: "error",
          progress: { error_code: "graphrag_embedding_dimension_mismatch" },
        })}
      />,
    );
    const link = screen.getByRole("link", { name: "Open model settings" });
    expect(link).toHaveAttribute("href", "/settings#embedding");
  });

  it("omits the settings link for non-configuration failures", () => {
    render(
      <KbIndexFailureBanner
        kb={kb({
          status: "error",
          progress: { error: "boom" },
        })}
      />,
    );
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders the caller's action slot inside the banner", () => {
    render(
      <KbIndexFailureBanner
        kb={kb({ status: "error" })}
        action={<button type="button">Retry indexing</button>}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Retry indexing" }),
    ).toBeInTheDocument();
  });
});
