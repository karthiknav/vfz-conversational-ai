import { initChat, prefillComposer } from "./chat.js";

let launcherEl;
let panelEl;
let closeBtnEl;
let badgeEl;
let isOpen = false;

export function openWidget() {
  isOpen = true;
  panelEl.classList.add("open");
  launcherEl.classList.add("open");
  badgeEl.classList.add("hidden");
}

export function closeWidget() {
  isOpen = false;
  panelEl.classList.remove("open");
  launcherEl.classList.remove("open");
}

function toggleWidget() {
  if (isOpen) {
    closeWidget();
  } else {
    openWidget();
  }
}

export function openWidgetWithMessage(text) {
  openWidget();
  prefillComposer(text);
}

export function initWidget() {
  launcherEl = document.getElementById("vz-launcher");
  panelEl = document.getElementById("vz-panel");
  closeBtnEl = document.getElementById("vz-panel-close");
  badgeEl = document.getElementById("vz-launcher-badge");

  launcherEl.addEventListener("click", toggleWidget);
  closeBtnEl.addEventListener("click", closeWidget);

  initChat();
}
