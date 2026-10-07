import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import MemoryHub from "@/components/memory/MemoryHub";

const fetcher = vi.hoisted(() => vi.fn());

vi.mock("next/link", () => ({
  default: ({ children, ...props }: { children?: ReactNode }) => (
    <a {...props}>{children}</a>
  ),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));
vi.mock("@/lib/api", () => ({
  apiFetch: fetcher,
  apiUrl: (path: string) => path,
}))

const forbidden = () => ({
  ok: false,
  status: 403,
  json: async () => ({ detail: "Forbidden" }),
})

// Regression guard for the #1228 pattern on /memory: a 403 overview body was
// parsed as data and rendered as zero counts. The hub must instead raise a
// visible error and keep placeholder stats instead of fake zeros.
it("renders a visible error and no zero stats when memory reads are forbidden", async () => {
  fetcher.mockImplementation(async () => forbidden())

  render(<MemoryHub />)

  const alert = await screen.findByText(
    "Some memory data could not be loaded. Press Refresh to retry.",
  )
  expect(alert).toHaveAttribute("role", "alert")
  expect(screen.getAllByText("—").length).toBe(3)
})
