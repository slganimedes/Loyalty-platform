from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import TransactionIn, TransactionResult
from ..services import loyalty

router = APIRouter(prefix="/api/v1", tags=["transactions"])


@router.post("/transactions", response_model=TransactionResult)
def ingest(payload: TransactionIn, db: Session = Depends(get_db)) -> TransactionResult:
    """Single ingestion endpoint shared by Getnet / ecommerce / other systems.

    NOTE (MVP): this endpoint has NO authentication by design. Protect it at
    the network layer (Cloudflare WAF/Access or IP allow-list) during the pilot.
    """
    return loyalty.ingest_transaction(db, payload)
