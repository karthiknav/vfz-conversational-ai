// The UI only ever talks to the orchestrator — never the Gateway or mocks
// directly. That's a deliberate, checkable property (see plan Phase 7
// verify step): open DevTools → Network while using this page and confirm
// every request targets ORCHESTRATOR_BASE_URL.
const ORCHESTRATOR_BASE_URL = window.ORCHESTRATOR_BASE_URL || "http://localhost:8000";
const CUSTOMER_ID = "CUST-1001";
const THREAD_ID = "demo-" + Math.random().toString(36).slice(2, 10);

const chatEl = document.getElementById("chat");
const composerEl = document.getElementById("composer");
const inputEl = document.getElementById("message-input");
const phaseBadgeEl = document.getElementById("phase-badge");
const proposalCardEl = document.getElementById("proposal-card");
const proposalTitleEl = document.getElementById("proposal-title");
const proposalDetailEl = document.getElementById("proposal-detail");
const approveBtnEl = document.getElementById("approve-btn");
const simulateFailureEl = document.getElementById("simulate-failure");

let currentProposal = null;

function addBubble(text, who) {
  const div = document.createElement("div");
  div.className = `bubble ${who}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
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

composerEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = inputEl.value.trim();
  if (!message) return;

  addBubble(message, "user");
  inputEl.value = "";

  const res = await fetch(`${ORCHESTRATOR_BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ customer_id: CUSTOMER_ID, thread_id: THREAD_ID, message }),
  });
  const data = await res.json();

  addBubble(data.reply, "agent");
  phaseBadgeEl.textContent = data.phase;
  renderProposal(data.pending_proposal);
});

approveBtnEl.addEventListener("click", async () => {
  if (!currentProposal) return;
  const proposalId = currentProposal.proposal_id;

  approveBtnEl.disabled = true;
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
  approveBtnEl.disabled = false;

  addBubble(data.reply, "agent");
  phaseBadgeEl.textContent = "action";
  renderProposal(null);
});

addBubble(
  "Hi Anna, I'm the VodafoneZiggo assistant (POC). Ask me about your usage, or ask to upgrade your plan.",
  "agent"
);
