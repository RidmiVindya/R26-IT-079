from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class Batch(BaseModel):
    batchId: str
    fishType: str
    rawWeight: float

    date: Optional[datetime] = None
    location: str = ""

    # Waste Prediction
    predictedWaste: float = 0
    cleanedWeight: float = 0

    # Salt Prediction
    saltAmount: float = 0
    recommendedDuration: int = 0   # NEW FIELD
    saltingDurationHours: float = 0

    # Salting Monitoring
    saltingStartTime: Optional[datetime] = None
    saltingStatus: str = "not_started"

    initialSaltedWeight: float = 0
    currentWeight: float = 0

    weightLoss: float = 0
    weightLossPercentage: float = 0

    createdAt: datetime = datetime.utcnow()
    updatedAt: datetime = datetime.utcnow()