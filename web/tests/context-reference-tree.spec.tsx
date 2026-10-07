import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { FileText } from "lucide-react";
import ContextReferenceTree, {
  type ContextTreeItem,
} from "@/components/chat/home/ContextReferenceTree";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const item = (over: Partial<ContextTreeItem> = {}): ContextTreeItem => ({
  key: "item-1",
  icon: FileText,
  kind: "Book",
  label: "Algebra.pdf",
  ...over,
});

const rowSelector = 'span[class*="group/ref"]';

it("renders nothing for an empty reference list", () => {
  const { container } = render(
    <ContextReferenceTree items={[]} direction="up" summaryNoun="references" />,
  );
  expect(container.firstChild).toBeNull();
});

it("shows a single reference directly without a collapse summary", () => {
  const { container } = render(
    <ContextReferenceTree
      items={[item({ key: "a", label: "One.pdf" })]}
      direction="up"
      summaryNoun="references"
    />,
  );
  expect(screen.getByText("One.pdf")).toBeInTheDocument();
  expect(screen.getByText("Book")).toBeInTheDocument();
  // No summary toggle and no remove affordance: nothing to collapse or drop.
  expect(container.querySelectorAll("button")).toHaveLength(0);
});

it("collapses several references into an N-item summary", () => {
  render(
    <ContextReferenceTree
      items={[
        item({ key: "a", label: "One.pdf" }),
        item({ key: "b", label: "Two.pdf" }),
      ]}
      direction="up"
      summaryNoun="attachments"
    />,
  );
  const summary = screen.getByRole("button", { name: "2 attachments" });
  expect(summary).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("One.pdf")).not.toBeInTheDocument();
  expect(screen.queryByText("Two.pdf")).not.toBeInTheDocument();
});

it("expands on the summary toggle and collapses again", () => {
  render(
    <ContextReferenceTree
      items={[
        item({ key: "a", label: "One.pdf" }),
        item({ key: "b", label: "Two.pdf" }),
      ]}
      direction="up"
      summaryNoun="attachments"
    />,
  );
  const summary = screen.getByRole("button", { name: "2 attachments" });
  fireEvent.click(summary);
  expect(summary).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("One.pdf")).toBeInTheDocument();
  expect(screen.getByText("Two.pdf")).toBeInTheDocument();
  fireEvent.click(summary);
  expect(summary).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("One.pdf")).not.toBeInTheDocument();
});

it("opens a clickable reference when the item carries an action", () => {
  const open = vi.fn();
  render(
    <ContextReferenceTree
      items={[item({ key: "a", label: "One.pdf", onClick: open })]}
      direction="up"
      summaryNoun="references"
    />,
  );
  // The row itself is the only button; a lone item never grows a summary.
  const [row] = screen.getAllByRole("button");
  expect(row).toHaveTextContent("One.pdf");
  fireEvent.click(row);
  expect(open).toHaveBeenCalledTimes(1);
});

it("offers a remove action for composer rows", () => {
  const remove = vi.fn();
  render(
    <ContextReferenceTree
      items={[item({ key: "a", label: "One.pdf", onRemove: remove })]}
      direction="up"
      summaryNoun="references"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  expect(remove).toHaveBeenCalledTimes(1);
});

it("swaps the icon for a thumbnail when the item has one", () => {
  const { container } = render(
    <ContextReferenceTree
      items={[
        item({ key: "a", label: "Photo.png", thumbnailUrl: "/thumb/a.png" }),
      ]}
      direction="up"
      summaryNoun="references"
    />,
  );
  expect(container.querySelector("img")?.getAttribute("src")).toBe(
    "/thumb/a.png",
  );
  cleanup();

  const plain = render(
    <ContextReferenceTree
      items={[item({ key: "a", label: "One.pdf" })]}
      direction="up"
      summaryNoun="references"
    />,
  );
  expect(plain.container.querySelector("img")).not.toBeInTheDocument();
  expect(plain.container.querySelector("svg")).toBeInTheDocument();
});

it("renders every row of a long list and truncates overlong labels", () => {
  const labels = Array.from({ length: 40 }, (_, i) => `Reference ${i + 1}`);
  render(
    <ContextReferenceTree
      items={labels.map((label, i) => item({ key: `k${i}`, label }))}
      direction="up"
      summaryNoun="references"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "40 references" }));
  // No built-in cap: every item gets its row once expanded.
  expect(document.body.querySelectorAll(rowSelector)).toHaveLength(40);
  cleanup();

  // The full label stays in the DOM for accessibility; truncation is CSS-only.
  const long = `${"An unusually long textbook chapter title that keeps going ".repeat(4)}and ends here`;
  const overflow = render(
    <ContextReferenceTree
      items={[item({ key: "long", label: long })]}
      direction="up"
      summaryNoun="references"
    />,
  );
  expect(overflow.container.textContent).toContain(long);
  expect(screen.getByText(long)).toHaveClass("truncate");
});

it("stacks rows above the summary for up and below it for down", () => {
  const items = [
    item({ key: "a", label: "One.pdf" }),
    item({ key: "b", label: "Two.pdf" }),
  ];
  const up = render(
    <ContextReferenceTree items={items} direction="up" summaryNoun="references" />,
  );
  fireEvent.click(screen.getByRole("button", { name: "2 references" }));
  // "up" reads bottom-to-top: the rows grow away from the textarea, so the
  // summary toggle sits after them in the DOM.
  const upRoot = up.container.firstElementChild as HTMLElement;
  expect(upRoot.children[0].tagName).toBe("SPAN");
  expect(upRoot.children[upRoot.children.length - 1].tagName).toBe("BUTTON");
  cleanup();

  const down = render(
    <ContextReferenceTree
      items={items}
      direction="down"
      summaryNoun="references"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "2 references" }));
  const downRoot = down.container.firstElementChild as HTMLElement;
  expect(downRoot.children[0].tagName).toBe("BUTTON");
  expect(downRoot.children[downRoot.children.length - 1].tagName).toBe("SPAN");
});

it("mirrors right-aligned rows to hug the message bubble", () => {
  const { container } = render(
    <ContextReferenceTree
      items={[
        item({ key: "a", label: "One.pdf" }),
        item({ key: "b", label: "Two.pdf" }),
      ]}
      direction="down"
      align="right"
      summaryNoun="references"
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "2 references" }));
  expect(container.firstElementChild).toHaveClass("items-end");
  // The label span's parent is the row; mirrored rows reverse the flex order.
  const row = screen.getByText("One.pdf").parentElement!;
  expect(row.tagName).toBe("SPAN");
  expect(row).toHaveClass("flex-row-reverse");
});
