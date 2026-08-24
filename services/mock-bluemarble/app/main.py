import json
import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

DSN = (
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}"
    f"@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.pool = await asyncpg.create_pool(DSN, min_size=1, max_size=5)
    yield
    await app.state.pool.close()


app = FastAPI(title="Bluemarble Mock (TM Forum-shaped BSS)", lifespan=lifespan)


class CreateOrderRequest(BaseModel):
    customer_id: str
    product_offering_id: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/catalog")
async def get_catalog():
    async with app.state.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, monthly_price, data_allowance_gb, raw_json "
            "FROM bluemarble.product_offering ORDER BY monthly_price"
        )
    return {
        "productOffering": [
            {
                **json.loads(row["raw_json"]),
                "dataAllowanceGb": row["data_allowance_gb"],
            }
            for row in rows
        ]
    }


@app.get("/productOrderingManagement/v4/productOrder/{order_id}")
async def get_order(order_id: str):
    async with app.state.pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT raw_json FROM bluemarble.product_order WHERE id = $1", order_id
        )
    if row is None:
        raise HTTPException(status_code=404, detail=f"productOrder {order_id} not found")
    return json.loads(row["raw_json"])


@app.post("/productOrderingManagement/v4/productOrder", status_code=201)
async def create_order(req: CreateOrderRequest):
    async with app.state.pool.acquire() as conn:
        offering = await conn.fetchrow(
            "SELECT id, name, monthly_price FROM bluemarble.product_offering WHERE id = $1",
            req.product_offering_id,
        )
        if offering is None:
            raise HTTPException(status_code=404, detail="productOffering not found")

        order_seq = await conn.fetchval("SELECT nextval('bluemarble.order_id_seq')")
        order_id = f"ORD-{order_seq}"

        raw_json = {
            "id": order_id,
            "state": "acknowledged",
            "relatedParty": [{"id": req.customer_id, "role": "customer"}],
            "productOrderItem": [
                {
                    "id": "1",
                    "action": "add",
                    "productOffering": {"id": offering["id"], "name": offering["name"]},
                }
            ],
        }

        await conn.execute(
            "INSERT INTO bluemarble.product_order (id, customer_id, product_offering_id, state, raw_json) "
            "VALUES ($1, $2, $3, 'acknowledged', $4)",
            order_id,
            req.customer_id,
            offering["id"],
            json.dumps(raw_json),
        )

    return raw_json
