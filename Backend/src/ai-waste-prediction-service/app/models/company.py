from pydantic import BaseModel
from typing import Optional

class Company(BaseModel):
    companyName: str
    companyType: str
    contactPerson: str
    phoneNumber: str
    email: str
    address: str
    servicesAccepted: str
    notes: Optional[str] = ""
    activeStatus: bool = True