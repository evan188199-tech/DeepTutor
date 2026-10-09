import { afterEach, describe, expect, it } from "vitest";
import { findCitationAnchor } from "@/lib/markdown-anchors";

afterEach(() => {
  document.body.replaceChildren();
});

function heading(id: string, text = id): HTMLElement {
  const el = document.createElement("h2");
  el.id = id;
  el.textContent = text;
  return el;
}

function referencesSection(): { details: HTMLDetailsElement; section: HTMLElement } {
  const details = document.createElement("details");
  const summary = document.createElement("summary");
  const section = document.createElement("section");
  section.id = "references";
  details.append(summary, section);
  return { details, section };
}

describe("findCitationAnchor", () => {
  it("resolves a plain hash link to the element with that id", () => {
    const { details, section } = referencesSection();
    const target = heading("heading-slug", "Installation");
    document.body.append(details, target);

    expect(findCitationAnchor("#heading-slug")).toBe(target);
    expect(details.open).toBe(false);
  });

  it("decodes percent-encoded CJK and special characters in the hash", () => {
    const { details, section } = referencesSection();
    const cjk = heading("标题", "标题");
    const spaced = heading("my section", "my section");
    document.body.append(details, cjk, spaced);

    expect(findCitationAnchor("#%E6%A0%87%E9%A2%98")).toBe(cjk);
    expect(findCitationAnchor("#my%20section")).toBe(spaced);
    expect(details.open).toBe(false);
  });

  it("falls back to the references section for a malformed percent-encoded hash", () => {
    const { details, section } = referencesSection();
    document.body.append(details);

    expect(findCitationAnchor("#%E6%9C")).toBe(section);
    expect(details.open).toBe(true);
  });

  it("falls back to references for an empty hash or a missing hash", () => {
    const { details, section } = referencesSection();
    document.body.append(details);

    expect(findCitationAnchor("#")).toBe(section);
    expect(findCitationAnchor(undefined)).toBe(section);
    expect(findCitationAnchor("#missing-slug")).toBe(section);
    expect(details.open).toBe(true);
  });

  it("maps citation ids to their reference anchors case-insensitively", () => {
    const { details, section } = referencesSection();
    const lower = heading("ref-cit-12-3");
    const plan = heading("ref-plan-7");
    const upper = heading("ref-cit-1-2");
    document.body.append(details, lower, plan, upper);

    expect(findCitationAnchor("#ignored", "CIT-12-3")).toBe(lower);
    expect(findCitationAnchor("#ignored", "cit-12-3")).toBe(lower);
    expect(findCitationAnchor("#ignored", " PLAN-7 ")).toBe(plan);
    expect(findCitationAnchor("#ignored", "CIT-1-2")).toBe(upper);
    expect(details.open).toBe(false);
  });

  it("prefers the citation anchor over the href hash and skips non-citation ids", () => {
    const { details, section } = referencesSection();
    const citationTarget = heading("ref-cit-1-1");
    const hashTarget = heading("heading-slug");
    document.body.append(details, citationTarget, hashTarget);

    expect(findCitationAnchor("#heading-slug", "CIT-1-1")).toBe(citationTarget);

    const notCitation = findCitationAnchor("#heading-slug", "CIT-abc");
    expect(notCitation).toBe(hashTarget);

    expect(findCitationAnchor("#heading-slug", "REFERENCES-1")).toBe(hashTarget);
  });

  it("falls back to references when the citation anchor is absent from the DOM", () => {
    const { details, section } = referencesSection();
    const hashTarget = heading("heading-slug");
    document.body.append(details, hashTarget);

    expect(findCitationAnchor("#heading-slug", "CIT-404-1")).toBe(section);
    expect(findCitationAnchor(undefined, "PLAN-404")).toBe(section);
  });

  it("returns the first element when duplicate ids exist", () => {
    const { details, section } = referencesSection();
    const first = heading("dup-heading", "first");
    const second = heading("dup-heading", "second");
    document.body.append(details, first, second);

    const resolved = findCitationAnchor("#dup-heading");
    expect(resolved).toBe(first);
    expect(resolved).not.toBe(second);
    expect(resolved?.textContent).toBe("first");
  });

  it("auto-opens the enclosing details of the resolved fallback", () => {
    const outer = document.createElement("details");
    const summary = document.createElement("summary");
    const refList = document.createElement("ol");
    refList.id = "references";
    const inner = document.createElement("details");
    const item = document.createElement("li");
    item.id = "ref-cit-2-2";
    inner.append(item);
    refList.append(inner);
    outer.append(summary, refList);
    document.body.append(outer);

    expect(outer.open).toBe(false);
    expect(inner.open).toBe(false);

    expect(findCitationAnchor("#ref-cit-2-2", "CIT-2-2")).toBe(item);
    expect(inner.open).toBe(true);
    expect(outer.open).toBe(false);
  });

  it("returns null when neither the hash nor a references section exists", () => {
    document.body.replaceChildren();
    expect(findCitationAnchor("#missing")).toBeNull();
    expect(findCitationAnchor("#missing", "CIT-1-1")).toBeNull();
  });
});
