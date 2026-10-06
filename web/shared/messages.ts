import i18n from "i18next";

/**
 * The single locale key for "the server could not be reached" copy
 * (error-messages scan #15: four divergent writings used to compete for it).
 */
export const NETWORK_FAILURE_MESSAGE =
  "Couldn't reach the server. Please check your connection and retry.";

/**
 * Localized network-failure copy for non-React modules (API client, auth).
 * `i18n.t` returns `undefined` before i18next initializes — node tests and
 * early SSR — so fall back to the English key, which is also what the
 * fallback language resolves to.
 */
export function networkFailureMessage(): string {
  return i18n.isInitialized ? i18n.t(NETWORK_FAILURE_MESSAGE) : NETWORK_FAILURE_MESSAGE;
}
