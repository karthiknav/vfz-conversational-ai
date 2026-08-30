import json
import os
from contextlib import asynccontextmanager
from urllib.parse import quote

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DSN = (
    f"postgresql://{quote(os.environ['POSTGRES_USER'], safe='')}:{quote(os.environ['POSTGRES_PASSWORD'], safe='')}"
    f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DSN, min_size=1, max_size=5)
    yield
    await app.state.pool.close()


app = FastAPI(title="Salesforce Mock (Case management)", lifespan=lifespan)


class CreateCaseRequest(BaseModel):
    customer_id: str
    subject: str
    reason: str | None = None
    # Demo-only injection hook for the induced partial-failure / compensation
    # walkthrough (plan step: Turn 3'' — order commits, CRM sync fails). Not
    # a real Salesforce concept; lets the orchestrator's compensation path
    # be exercised deterministically without a fault-injection framework.
    force_fail: bool = False


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/Case/{case_id}")
async def get_case(case_id: str):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT raw_json FROM salesforce.case WHERE id = $1", case_id
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
    return json.loads(row["raw_json"])


@app.post("/Case", status_code=201)
async def create_case(req: CreateCaseRequest):
    if req.force_fail:
        raise HTTPException(status_code=500, detail="Simulated CRM sync failure")

    async with app.state.pool.acquire() as conn:
        case_seq = await conn.fetchval("SELECT nextval('salesforce.case_id_seq')")
        case_id = f"CASE-{case_seq}"

        raw_json = {
            "Id": case_id,
            "Case_Status__c": "New",
            "Subject": req.subject,
            "CustomerId__c": req.customer_id,
            "Reason__c": req.reason,
        }

        await conn.execute(
            'INSERT INTO salesforce.case (id, customer_id, subject, "Case_Status__c", reason, raw_json) '
            "VALUES ($1, $2, $3, 'New', $4, $5)",
            case_id,
            req.customer_id,
            req.subject,
            req.reason,
            json.dumps(raw_json),
        )

    return raw_json
