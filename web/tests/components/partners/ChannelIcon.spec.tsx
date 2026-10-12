import { render } from "@testing-library/react";
import { expect, it } from "vitest";
import ChannelIcon from "@/components/partners/ChannelIcon";

function renderIcon(props: Parameters<typeof ChannelIcon>[0]) {
  const { container } = render(<ChannelIcon {...props} />);
  return container;
}

function svgOf(container: HTMLElement) {
  const svg = container.querySelector("svg");
  expect(svg).not.toBeNull();
  return svg as SVGSVGElement;
}

function badgeColor(el: Element): string {
  const style = (el as HTMLElement).style;
  return (style.backgroundColor || style.background).toLowerCase();
}

function expectColor(el: Element, hex: string, rgb: string) {
  expect([hex.toLowerCase(), rgb]).toContain(badgeColor(el));
}

it("renders the Feishu bird as a stroked three-path svg", () => {
  const container = renderIcon({ name: "feishu" });
  const svg = svgOf(container);
  expect(svg.getAttribute("viewBox")).toBe("0 0 48 48");
  expect(svg.getAttribute("fill")).toBe("none");
  const paths = [...svg.querySelectorAll("path")];
  expect(paths).toHaveLength(3);
  expect(paths[0].getAttribute("stroke")).toBe("#3370FF");
  expect(paths[1].getAttribute("fill")).toBe("#3370FF");
});

it("renders DingTalk as a single filled wing path", () => {
  const container = renderIcon({ name: "dingtalk" });
  const svg = svgOf(container);
  expect(svg.getAttribute("viewBox")).toBe("0 0 1024 1024");
  expect(svg.getAttribute("fill")).toBe("#0089FF");
  expect(svg.querySelectorAll("path")).toHaveLength(1);
});

it("renders WeCom as five brand-colored subpaths", () => {
  const container = renderIcon({ name: "wecom" });
  const svg = svgOf(container);
  expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
  const fills = [...svg.querySelectorAll("path")].map((p) => p.getAttribute("fill"));
  expect(fills).toEqual(["#0082EF", "#2CB800", "#0081EE", "#FB6500", "#FFCC00"]);
});

it("renders MS Teams as two people circles plus four tile paths", () => {
  const container = renderIcon({ name: "msteams" });
  const svg = svgOf(container);
  expect(svg.getAttribute("viewBox")).toBe("0 0 256 239");
  expect(svg.querySelectorAll("circle")).toHaveLength(2);
  expect(svg.querySelectorAll("path")).toHaveLength(4);
});

it("renders NapCat as a QQ-blue badge around the cat mark", () => {
  const container = renderIcon({ name: "napcat", size: 20 });
  const span = container.querySelector("span");
  expect(span).not.toBeNull();
  expectColor(span as Element, "#1EBAFC", "rgb(30, 186, 252)");
  expect((span as HTMLElement).style.width).toBe("20px");
  const cat = svgOf(container);
  expect(Number(cat.getAttribute("width"))).toBeCloseTo(14.4, 6);
  expect(cat.getAttribute("class")).toContain("lucide-cat");
});

it("renders simple-icons brand marks with their brand fill", () => {
  const container = renderIcon({ name: "telegram" });
  const svg = svgOf(container);
  expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
  expect(svg.getAttribute("fill")).toBe("#26A5E4");
  expect(svg.querySelectorAll("path")).toHaveLength(1);
  expect(svg.getAttribute("aria-hidden")).toBe("true");
});

it("renders the pure-black Matrix mark as currentColor instead", () => {
  const container = renderIcon({ name: "matrix" });
  expect(svgOf(container).getAttribute("fill")).toBe("currentColor");
});

it("renders Slack and MoChat as brand-colored letter badges", () => {
  const slack = renderIcon({ name: "slack" }).querySelector("span");
  expect(slack).not.toBeNull();
  expect((slack as HTMLElement).textContent).toBe("S");
  expectColor(slack as Element, "#4A154B", "rgb(74, 21, 75)");

  const mochat = renderIcon({ name: "mochat" }).querySelector("span");
  expect(mochat).not.toBeNull();
  expect((mochat as HTMLElement).textContent).toBe("M");
  expectColor(mochat as Element, "#07C160", "rgb(7, 193, 96)");
});

it("renders email as a neutral envelope icon", () => {
  const container = renderIcon({ name: "email" });
  const svg = svgOf(container);
  expect(svg.getAttribute("class")).toContain("lucide-mail");
  expect(svg.getAttribute("class")).toContain("text-[var(--muted-foreground)]");
});

it("falls back to a neutral radio mark for unknown channels", () => {
  const container = renderIcon({ name: "carrier-pigeon" });
  const svg = svgOf(container);
  expect(svg.getAttribute("class")).toContain("lucide-radio");
});

it("dispatches case-insensitively and falls back for spaced names", () => {
  const telegram = svgOf(renderIcon({ name: "Telegram" }));
  expect(telegram.getAttribute("fill")).toBe("#26A5E4");

  const feishu = svgOf(renderIcon({ name: "Feishu" }));
  expect(feishu.getAttribute("viewBox")).toBe("0 0 48 48");

  const wecom = svgOf(renderIcon({ name: "WeCom" }));
  expect(wecom.querySelectorAll("path")).toHaveLength(5);

  const spaced = svgOf(renderIcon({ name: "MS Teams" }));
  expect(spaced.getAttribute("class")).toContain("lucide-radio");
});

it("applies size and merges className into the brand svg", () => {
  const container = renderIcon({ name: "discord", size: 28, className: "ci-x" });
  const svg = svgOf(container);
  expect(svg.getAttribute("width")).toBe("28");
  expect(svg.getAttribute("height")).toBe("28");
  expect(svg.getAttribute("fill")).toBe("#5865F2");
  expect(svg.getAttribute("class")).toContain("shrink-0");
  expect(svg.getAttribute("class")).toContain("ci-x");
});
