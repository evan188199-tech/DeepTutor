import { cleanup, render, screen, waitFor } from "@testing-library/react";
import i18n from "i18next";
import { useTranslation } from "react-i18next";
import { afterEach, beforeEach, expect, it } from "vitest";

import { I18nProvider } from "@/i18n/I18nProvider";
import zhApp from "@/locales/zh/app.json";

const LOADABLE_LANGUAGES = ["zh", "fr", "de", "uk", "pl"] as const;
const MISSING_KEY = "__i18n_provider_missing_key_probe__";

function Probe({
  text,
  options,
}: {
  text: string;
  options?: Record<string, unknown>;
}) {
  const { t } = useTranslation();
  return <p data-testid="probe">{t(text, options)}</p>;
}

function mount(language: string, enabled = true) {
  return render(
    <I18nProvider language={language} enabled={enabled}>
      <Probe text="Update to {{version}}" options={{ version: "1.6.14" }} />
    </I18nProvider>,
  );
}

function busyPlaceholder(): Element | null {
  return document.querySelector('[aria-busy="true"]');
}

async function resetI18n() {
  await i18n.changeLanguage("en");
  for (const language of LOADABLE_LANGUAGES) {
    if (i18n.hasResourceBundle(language, "app")) {
      i18n.removeResourceBundle(language, "app");
    }
  }
  document.documentElement.lang = "";
}

beforeEach(resetI18n);
afterEach(cleanup);

it("initializes i18n at module load so a ready language renders children immediately", async () => {
  mount("en");

  expect(i18n.isInitialized).toBe(true);
  expect(busyPlaceholder()).toBeNull();
  expect(screen.getByTestId("probe")).toHaveTextContent("Update to 1.6.14");

  await waitFor(() => expect(document.documentElement.lang).toBe("en"));
});

it("holds the busy placeholder until a deferred bundle loads, then renders children", async () => {
  mount("zh");

  expect(busyPlaceholder()).not.toBeNull();
  expect(screen.queryByTestId("probe")).toBeNull();

  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent("更新到 1.6.14");
  });
  expect(busyPlaceholder()).toBeNull();
  expect(document.documentElement.lang).toBe("zh");
});

it("re-gates through the busy placeholder and swaps copy when the language prop switches", async () => {
  const view = mount("en");
  await waitFor(() => expect(screen.getByTestId("probe")).toBeInTheDocument());

  view.rerender(
    <I18nProvider language="fr">
      <Probe text="Update to {{version}}" options={{ version: "1.6.14" }} />
    </I18nProvider>,
  );

  expect(busyPlaceholder()).not.toBeNull();

  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent(
      "Mettre à jour vers 1.6.14",
    );
  });
  expect(busyPlaceholder()).toBeNull();
  expect(document.documentElement.lang).toBe("fr");
});

it("never loads a bundle or renders children while disabled", async () => {
  const beforeLang = document.documentElement.lang;
  mount("zh", false);

  expect(busyPlaceholder()).not.toBeNull();

  await new Promise((resolve) => setTimeout(resolve, 50));

  expect(screen.queryByTestId("probe")).toBeNull();
  expect(busyPlaceholder()).not.toBeNull();
  expect(i18n.hasResourceBundle("zh", "app")).toBe(false);
  expect(document.documentElement.lang).toBe(beforeLang);
});

it("normalizes persisted raw selections such as zh_CN onto the real bundle", async () => {
  mount("zh_CN");

  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent("更新到 1.6.14");
  });
  expect(document.documentElement.lang).toBe("zh");
});

it("falls back to English for unsupported persisted selections", async () => {
  mount("ko-KR");

  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent("Update to 1.6.14");
  });
  expect(document.documentElement.lang).toBe("en");
});

it("returns the literal key for missing entries because keySeparator is disabled", async () => {
  render(
    <I18nProvider language="zh">
      <Probe text={MISSING_KEY} />
    </I18nProvider>,
  );

  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent(MISSING_KEY);
  });
});

it("falls back to English copy when the selected bundle value is empty", async () => {
  const view = render(
    <I18nProvider language="zh">
      <Probe text="File too large: {{name}}" options={{ name: "demo.mkv" }} />
    </I18nProvider>,
  );
  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent("文件过大：demo.mkv");
  });

  i18n.addResourceBundle("zh", "app", { "File too large: {{name}}": "" }, true, true);

  view.rerender(
    <I18nProvider language="zh">
      <Probe key="after-emptying" text="File too large: {{name}}" options={{ name: "demo.mkv" }} />
    </I18nProvider>,
  );

  await waitFor(() => {
    expect(screen.getByTestId("probe")).toHaveTextContent("File too large: demo.mkv");
  });
  expect(i18n.t("File too large: {{name}}", { lng: "zh", name: "demo.mkv" })).toBe(
    "File too large: demo.mkv",
  );

  i18n.addResourceBundle(
    "zh",
    "app",
    { "File too large: {{name}}": zhApp["File too large: {{name}}"] },
    true,
    true,
  );
});

it("interpolates raw option values without HTML-escaping them", async () => {
  render(
    <I18nProvider language="zh">
      <Probe
        text="Unsupported file type: {{name}}"
        options={{ name: "<b>demo</b>" }}
      />
    </I18nProvider>,
  );

  await waitFor(() => {
    expect(screen.getByTestId("probe").textContent).toBe(
      "不支持的文件类型：<b>demo</b>",
    );
  });
  expect(screen.getByTestId("probe").textContent).not.toContain("&lt;");
});
