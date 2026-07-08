from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Notification(BaseModel):
    batchId: str
    fishType: str
    predictedWaste: float
    recipientType: str = "recycler"
    message: str
    status: str = "generated"
    sentAt: datetime = datetime.utcnow()