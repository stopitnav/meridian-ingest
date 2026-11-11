from fastapi import FastAPI, UploadFile
from fastapi.responses import JSONResponse

from core.pipeline import run_ingestion
from core.store import PositionStore

# No auth here by design (see README ground rules) — run this only on the
# internal network/VPN. `uvicorn api:app` binds 127.0.0.1 by default;
# don't pass --host 0.0.0.0 without adding real auth first.
app = FastAPI(title="Meridian Positions Ingestion")
DB_PATH = "positions.sqlite3"


@app.post("/ingest")
async def ingest(file: UploadFile):
    """Upload a positions CSV. Safe to call repeatedly with the same
    file or with corrected re-deliveries — see report for per-row outcomes.
    """
    content = (await file.read()).decode("utf-8")
    report = run_ingestion(content, source_name=file.filename, db_path=DB_PATH)
    return JSONResponse(report)


@app.get("/positions")
def list_positions():
    store = PositionStore(DB_PATH)
    try:
        return store.all_positions()
    finally:
        store.close()
