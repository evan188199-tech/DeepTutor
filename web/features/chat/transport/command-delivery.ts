import { NETWORK_FAILURE_MESSAGE } from "@/shared/messages";

/**
 * Local delivery uncertainty is not a server rejection (#1648). The shared
 * network-failure copy is the locale key itself, so callers that wrap it in
 * `t()` resolve the translated wording (error-messages scan #15).
 */
export const COMMAND_CONFIRMATION_FAILED = NETWORK_FAILURE_MESSAGE;

export class CommandDeliveryError extends Error {
  constructor() {
    super(COMMAND_CONFIRMATION_FAILED);
    this.name = "CommandDeliveryError";
  }
}
