from pydantic import BaseModel
from typing import Optional

class StartSaltingRequest(BaseModel):
    recommendedDuration: int = 12
    recommendedSalt: Optional[float] = None