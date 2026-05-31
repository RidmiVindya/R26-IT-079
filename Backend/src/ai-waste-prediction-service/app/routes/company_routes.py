from fastapi import APIRouter, HTTPException
from app.models.company import Company
from app.config.db import db
from bson import ObjectId

router = APIRouter(tags=["Companies"])

@router.post("/")
async def create_company(company: Company):
    result = db.companies.insert_one(company.dict())

    return {
        "message": "Company created successfully",
        "id": str(result.inserted_id)
    }

@router.get("/")
async def get_companies():
    companies = []

    for company in db.companies.find():
        company["_id"] = str(company["_id"])
        companies.append(company)

    return companies

@router.get("/{company_id}")
async def get_company(company_id: str):
    if not ObjectId.is_valid(company_id):
        raise HTTPException(status_code=400, detail="Invalid company ID")

    company = db.companies.find_one({"_id": ObjectId(company_id)})

    if not company:
        raise HTTPException(status_code=404, detail="Company not found")

    company["_id"] = str(company["_id"])
    return company

@router.put("/{company_id}")
async def update_company(company_id: str, company: Company):
    if not ObjectId.is_valid(company_id):
        raise HTTPException(status_code=400, detail="Invalid company ID")

    result = db.companies.update_one(
        {"_id": ObjectId(company_id)},
        {"$set": company.dict()}
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    return {"message": "Company updated successfully"}

@router.delete("/{company_id}")
async def delete_company(company_id: str):
    if not ObjectId.is_valid(company_id):
        raise HTTPException(status_code=400, detail="Invalid company ID")

    result = db.companies.delete_one({"_id": ObjectId(company_id)})

    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Company not found")

    return {"message": "Company deleted successfully"}