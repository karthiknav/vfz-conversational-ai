from langchain_core.messages import AIMessage, HumanMessage
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.agents import governance_agent
from app.graph import get_graph
from app.langfuse_setup import get_callback_handler

app = FastAPI(title="VZ Conversational AI Orchestrator")


class ChatRequest(BaseModel):
    customer_id: str
    thread_id: str
    message: str


class ChatResponse(BaseModel):
    thread_id: str
    phase: str
    reply: str
    pending_proposal: dict | None = None


class ApproveRequest(BaseModel):
    thread_id: str
    customer_id: str
    # Demo-only flag driving the induced partial-failure / compensation
    # branch (plan Turn 3''). Never present in a real approval flow.
    simulate_failure: bool = False


class ApproveResponse(BaseModel):
    thread_id: str
    reply: str
    result: dict | None = None


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _latest_ai_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, AIMessage) and m.content:
            return m.content if isinstance(m.content, str) else str(m.content)
    return ""


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    graph = await get_graph()
    config = _config(req.thread_id)
    if handler := get_callback_handler(req.thread_id, req.customer_id):
        config["callbacks"] = [handler]

    existing = await graph.aget_state(config)
    input_state = {
        "customer_id": req.customer_id,
        "thread_id": req.thread_id,
        "messages": [HumanMessage(content=req.message)],
    }
    if not existing.values:
        input_state["phase"] = "advise"
        input_state["pending_proposal"] = None
        input_state["intent"] = None
        input_state["last_action_result"] = None

    result = await graph.ainvoke(input_state, config=config)
    return ChatResponse(
        thread_id=req.thread_id,
        phase=result["phase"],
        reply=_latest_ai_text(result["messages"]),
        pending_proposal=result.get("pending_proposal"),
    )


@app.post("/approve/{proposal_id}", response_model=ApproveResponse)
async def approve(proposal_id: str, req: ApproveRequest):
    graph = await get_graph()
    config = _config(req.thread_id)

    state = await graph.aget_state(config)
    if not state.values:
        raise HTTPException(status_code=404, detail="unknown thread_id")

    pending = state.values.get("pending_proposal")
    if not pending or pending.get("proposal_id") != proposal_id:
        raise HTTPException(status_code=409, detail="no matching pending proposal for this thread")

    run_state = dict(state.values)
    run_state["simulate_partial_failure"] = req.simulate_failure

    update = await governance_agent.run(run_state)
    await graph.aupdate_state(config, update, as_node="governance_agent")

    return ApproveResponse(
        thread_id=req.thread_id,
        reply=_latest_ai_text(update["messages"]),
        result=update.get("last_action_result"),
    )
