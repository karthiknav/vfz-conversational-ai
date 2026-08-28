// The widget only ever talks to the orchestrator — never the Gateway or mocks
// directly. That's a deliberate, checkable property: open DevTools → Network
// while using this page and confirm every request targets
// ORCHESTRATOR_BASE_URL.
const ORCHESTRATOR_BASE_URL = window.ORCHESTRATOR_BASE_URL || "http://localhost:8000";
const CUSTOMER_ID = "CUST-1001";

const THREAD_ID_KEY = "vz-thread-id";
const GREETED_KEY = "vz-greeted";

function getOrCreateThreadId() {
  let id = sessionStorage.getItem(THREAD_ID_KEY);
  if (!id) {
    id = "demo-" + Math.random().toString(36).slice(2, 10);
    sessionStorage.setItem(THREAD_ID_KEY, id);
  }
  return id;
}

const THREAD_ID = getOrCreateThreadId();

let chatEl;
let composerEl;
let inputEl;
let sendBtnEl;
let phaseBadgeEl;
let proposalCardEl;
let proposalTitleEl;
let proposalDetailEl;
let approveBtnEl;
let simulateFailureEl;

let currentProposal = null;

function addBubble(text, who) {
  const div = document.createElement("div");
  div.className = `vz-bubble ${who}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function showTyping() {
  const div = document.createElement("div");
  div.className = "vz-bubble agent vz-typing";
  div.id = "vz-typing-indicator";
  div.innerHTML = "<span></span><span></span><span></span>";
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
}

function hideTyping() {
  const el = document.getElementById("vz-typing-indicator");
  if (el) el.remove();
}

function setBusy(busy) {
  inputEl.disabled = busy;
  sendBtnEl.disabled = busy;
}

function renderProposal(proposal) {
  currentProposal = proposal;
  if (!proposal) {
    proposalCardEl.classList.add("hidden");
    return;
  }
  proposalTitleEl.textContent = proposal.target_offer_name;
  proposalDetailEl.textContent =
    `€${proposal.target_monthly_price_eur.toFixed(2)}/mo ` +
    `(${proposal.delta_eur >= 0 ? "+" : ""}€${proposal.delta_eur.toFixed(2)} vs. your current plan). ` +
    "Approve to switch today.";
  proposalCardEl.classList.remove("hidden");
}

async function sendMessage(message) {
  if (!message) return;

  addBubble(message, "user");
  inputEl.value = "";
  setBusy(true);
  showTyping();

  try {
    const res = await fetch(`${ORCHESTRATOR_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id: CUSTOMER_ID, thread_id: THREAD_ID, message }),
    });
    const data = await res.json();

    hideTyping();
    addBubble(data.reply, "agent");
    phaseBadgeEl.textContent = data.phase;
    renderProposal(data.pending_proposal);
  } finally {
    setBusy(false);
  }
}

async function approveProposal() {
  if (!currentProposal) return;
  const proposalId = currentProposal.proposal_id;

  approveBtnEl.disabled = true;
  showTyping();
  try {
    const res = await fetch(`${ORCHESTRATOR_BASE_URL}/approve/${proposalId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        thread_id: THREAD_ID,
        customer_id: CUSTOMER_ID,
        simulate_failure: simulateFailureEl.checked,
      }),
    });
    const data = await res.json();

    hideTyping();
    addBubble(data.reply, "agent");
    phaseBadgeEl.textContent = "action";
    renderProposal(null);
  } finally {
    approveBtnEl.disabled = false;
  }
}

export function prefillComposer(text) {
  inputEl.value = text;
  inputEl.focus();
}

export function initChat() {
  chatEl = document.getElementById("vz-chat-log");
  composerEl = document.getElementById("vz-composer");
  inputEl = document.getElementById("vz-message-input");
  sendBtnEl = document.getElementById("vz-send-btn");
  phaseBadgeEl = document.getElementById("vz-phase-badge");
  proposalCardEl = document.getElementById("vz-proposal-card");
  proposalTitleEl = document.getElementById("vz-proposal-title");
  proposalDetailEl = document.getElementById("vz-proposal-detail");
  approveBtnEl = document.getElementById("vz-approve-btn");
  simulateFailureEl = document.getElementById("vz-simulate-failure");

  composerEl.addEventListener("submit", (e) => {
    e.preventDefault();
    sendMessage(inputEl.value.trim());
  });

  approveBtnEl.addEventListener("click", approveProposal);

  if (!sessionStorage.getItem(GREETED_KEY)) {
    addBubble(
      "Hi Anna, I'm the VodafoneZiggo assistant. Ask me about your usage, or ask to upgrade your plan.",
      "agent"
    );
    sessionStorage.setItem(GREETED_KEY, "1");
  }
}
