from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..schemas import TransactionIn, TransactionResult
from ..services import loyalty
from .auth import authorize_merchant, current_user

router = APIRouter(prefix="/api/v1", tags=["transactions"])


@router.post("/transactions", response_model=TransactionResult)
def ingest(
    payload: TransactionIn,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.AdminUser = Depends(current_user),
) -> TransactionResult:
    """Single ingestion endpoint shared by Getnet / ecommerce / other systems.

    Requires a bearer session authorized for the merchant. External integrations
    must authenticate; the original anonymous pilot ingestion is no longer accepted.
    """
    authorize_merchant(payload.merchant_id, user, db)
    result = loyalty.ingest_transaction(db, payload, user)
    if result.notification_id:
        from ..services.notifications import dispatch_pending

        background.add_task(dispatch_pending)
    return result
