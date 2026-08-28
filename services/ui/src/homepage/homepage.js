import { openWidgetWithMessage } from "../widget/widget.js";

export function initHomepage() {
  document.querySelectorAll("[data-vz-chat-message]").forEach((btn) => {
    btn.addEventListener("click", () => {
      openWidgetWithMessage(btn.dataset.vzChatMessage);
    });
  });
}
