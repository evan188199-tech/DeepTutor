import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatDate, formatTime, getLocale } from "@/lib/datetime";
import { formatMediaTime, timeFromSourceHref } from "@/lib/reading-media-time";
import { formatRelativeTime, getDayGroupKey } from "@/lib/relative-time";

const noonSecondsDaysAgo = (daysAgo: number): number => {
  const now = new Date();
  const noon = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate() - daysAgo,
    12,
    0,
    0,
    0,
  );
  return noon.getTime() / 1000;
};

const startOfTodaySeconds = (): number => {
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return midnight.getTime() / 1000;
};

describe("reading-media-time timeFromSourceHref", () => {
  it("parses integer and fractional fragment offsets", () => {
    expect(timeFromSourceHref("#t=90")).toBe(90);
    expect(timeFromSourceHref("#t=1.5")).toBe(1.5);
    expect(timeFromSourceHref("#t=0")).toBe(0);
    expect(timeFromSourceHref("#t=3600")).toBe(3600);
  });

  it("returns null for malformed fragments", () => {
    expect(timeFromSourceHref("")).toBeNull();
    expect(timeFromSourceHref("#t=")).toBeNull();
    expect(timeFromSourceHref("#t=abc")).toBeNull();
    expect(timeFromSourceHref("#t=-3")).toBeNull();
    expect(timeFromSourceHref("#t=1e3")).toBeNull();
    expect(timeFromSourceHref("#t=90.5.2")).toBeNull();
  });

  it("returns null when the fragment carries extra segments or missing marker", () => {
    expect(timeFromSourceHref("#t=90&start=1")).toBeNull();
    expect(timeFromSourceHref("#t=90s")).toBeNull();
    expect(timeFromSourceHref("t=90")).toBeNull();
    expect(timeFromSourceHref("#t90")).toBeNull();
  });

  it("treats missing input as an empty string", () => {
    expect(timeFromSourceHref(undefined as unknown as string)).toBeNull();
  });
});

describe("reading-media-time formatMediaTime", () => {
  it("formats sub-minute, minute and hour boundaries", () => {
    expect(formatMediaTime(0)).toBe("0:00");
    expect(formatMediaTime(59)).toBe("0:59");
    expect(formatMediaTime(60)).toBe("1:00");
    expect(formatMediaTime(61)).toBe("1:01");
    expect(formatMediaTime(3599)).toBe("59:59");
    expect(formatMediaTime(3600)).toBe("1:00:00");
    expect(formatMediaTime(3661)).toBe("1:01:01");
    expect(formatMediaTime(86399)).toBe("23:59:59");
  });

  it("floors fractional seconds", () => {
    expect(formatMediaTime(90.9)).toBe("1:30");
    expect(formatMediaTime(0.9)).toBe("0:00");
  });

  it("clamps illegal numeric input to zero", () => {
    expect(formatMediaTime(-5)).toBe("0:00");
    expect(formatMediaTime(Number.NaN)).toBe("0:00");
    expect(formatMediaTime(undefined as unknown as number)).toBe("0:00");
    expect(formatMediaTime(Number("not-a-number"))).toBe("0:00");
  });
});

describe("datetime getLocale", () => {
  it("maps supported languages to their locale tags", () => {
    expect(getLocale("zh")).toBe("zh-CN");
    expect(getLocale("fr")).toBe("fr-FR");
    expect(getLocale("de")).toBe("de-DE");
    expect(getLocale("uk")).toBe("uk-UA");
    expect(getLocale("pl")).toBe("pl-PL");
  });

  it("falls back to en-US for English and unknown languages", () => {
    expect(getLocale("en")).toBe("en-US");
    expect(getLocale("es" as never)).toBe("en-US");
    expect(getLocale("klingon" as never)).toBe("en-US");
  });
});

describe("datetime formatDate/formatTime", () => {
  it("formats a mid-January date per locale without shifting calendar days", () => {
    const localDate = new Date(2026, 0, 15, 12, 0, 0);
    expect(formatDate(localDate, "en")).toBe("Jan 15, 2026");
    expect(formatDate(localDate, "zh")).toBe("2026年1月15日");
  });

  it("honours custom Intl options", () => {
    const localDate = new Date(2026, 0, 15, 12, 0, 0);
    expect(
      formatDate(localDate, "de", {
        year: "numeric",
        month: "long",
        day: "numeric",
      }),
    ).toBe("15. Januar 2026");
  });

  it("formats time-of-day per locale without shifting hours", () => {
    const localTime = new Date(2026, 0, 15, 14, 5, 0);
    expect(formatTime(localTime, "en")).toBe("02:05 PM");
    expect(
      formatTime(localTime, "en", { hour: "2-digit", minute: "2-digit", hour12: false }),
    ).toBe("14:05");
  });
});

describe("relative-time getDayGroupKey", () => {
  it("groups items from today and the future under today", () => {
    expect(getDayGroupKey(startOfTodaySeconds())).toBe("today");
    expect(getDayGroupKey(startOfTodaySeconds() + 43200)).toBe("today");
    expect(getDayGroupKey(startOfTodaySeconds() + 5 * 86400)).toBe("today");
  });

  it("rolls over to yesterday right after local midnight", () => {
    expect(getDayGroupKey(startOfTodaySeconds() - 1)).toBe("yesterday");
    expect(getDayGroupKey(noonSecondsDaysAgo(1))).toBe("yesterday");
  });

  it("groups 2-6 days back as last_7_days with day-boundary edges", () => {
    expect(getDayGroupKey(noonSecondsDaysAgo(2))).toBe("last_7_days");
    expect(getDayGroupKey(noonSecondsDaysAgo(6))).toBe("last_7_days");
  });

  it("groups 7 days back and older as earlier", () => {
    expect(getDayGroupKey(noonSecondsDaysAgo(7))).toBe("earlier");
    expect(getDayGroupKey(noonSecondsDaysAgo(30))).toBe("earlier");
  });
});

describe("relative-time formatRelativeTime", () => {
  const fixedNowMs = Date.UTC(2026, 5, 15, 12, 0, 0);
  const nowSec = fixedNowMs / 1000;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(fixedNowMs);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("formats sub-minute offsets in seconds", () => {
    expect(formatRelativeTime(nowSec, "en")).toBe("now");
    expect(formatRelativeTime(nowSec - 30, "en")).toBe("30 seconds ago");
    expect(formatRelativeTime(nowSec + 45, "en")).toBe("in 45 seconds");
  });

  it("switches to minutes at the 60 second boundary", () => {
    expect(formatRelativeTime(nowSec - 59, "en")).toBe("59 seconds ago");
    expect(formatRelativeTime(nowSec - 60, "en")).toBe("1 minute ago");
    expect(formatRelativeTime(nowSec - 120, "en")).toBe("2 minutes ago");
    expect(formatRelativeTime(nowSec + 90, "en")).toBe("in 2 minutes");
  });

  it("switches to hours at the 60 minute boundary", () => {
    expect(formatRelativeTime(nowSec - 3600, "en")).toBe("1 hour ago");
    expect(formatRelativeTime(nowSec - 7200, "en")).toBe("2 hours ago");
    expect(formatRelativeTime(nowSec + 3600, "en")).toBe("in 1 hour");
  });

  it("switches to days at the 24 hour boundary and uses auto wording", () => {
    expect(formatRelativeTime(nowSec - 86400, "en")).toBe("yesterday");
    expect(formatRelativeTime(nowSec - 172800, "en")).toBe("2 days ago");
    expect(formatRelativeTime(nowSec + 172800, "en")).toBe("in 2 days");
  });

  it("switches to weeks at the 7 day boundary", () => {
    expect(formatRelativeTime(nowSec - 604800, "en")).toBe("last week");
    expect(formatRelativeTime(nowSec - 1209600, "en")).toBe("2 weeks ago");
  });

  it("switches to months at the 30 day boundary", () => {
    expect(formatRelativeTime(nowSec - 2592000, "en")).toBe("last month");
    expect(formatRelativeTime(nowSec - 5184000, "en")).toBe("2 months ago");
  });

  it("switches to years at the 365 day boundary", () => {
    expect(formatRelativeTime(nowSec - 31536000, "en")).toBe("last year");
    expect(formatRelativeTime(nowSec - 94608000, "en")).toBe("3 years ago");
  });

  it("formats through the caller's locale", () => {
    expect(formatRelativeTime(nowSec - 7200, "zh")).toMatch(/^2\s*小时前$/);
    expect(formatRelativeTime(nowSec - 120, "fr")).toBe("il y a 2 minutes");
  });

  it("falls back to English for an empty locale", () => {
    expect(formatRelativeTime(nowSec - 7200, "")).toBe("2 hours ago");
  });

  it("never throws on unsupported locale tags", () => {
    const output = formatRelativeTime(nowSec - 7200, "zz-ZZ");
    expect(typeof output).toBe("string");
    expect(output.length).toBeGreaterThan(0);
  });
});
