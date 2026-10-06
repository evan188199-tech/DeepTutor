import type { TFunction } from "i18next";

export type ToolAvailabilityCopy = {
  badge: string;
  detail: string;
  href?: string;
};

export function toolEffectiveEnabled(
  savedEnabled: boolean,
  available: boolean,
  comingSoon: boolean,
): boolean {
  return savedEnabled && available && !comingSoon;
}

export function toolAvailabilityCopy(
  reason: string | null | undefined,
  t: TFunction,
): ToolAvailabilityCopy {
  if (reason === "search_provider_not_configured") {
    return {
      badge: t("toolAvailability.searchProviderNotConfigured.badge"),
      detail: t("toolAvailability.searchProviderNotConfigured.detail"),
      href: "/settings#search",
    };
  }
  if (reason === "search_credentials_missing") {
    return {
      badge: t("toolAvailability.searchCredentialsMissing.badge"),
      detail: t("toolAvailability.searchCredentialsMissing.detail"),
      href: "/settings#search",
    };
  }
  return {
    badge: t("toolAvailability.unavailable.badge"),
    detail: t("toolAvailability.unavailable.detail"),
  };
}
