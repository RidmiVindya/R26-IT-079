from fastapi import APIRouter
from app.config.db import db

router = APIRouter(tags=["Dashboard"])

@router.get("/stats")
async def get_dashboard_stats():

    total_batches = db.batches.count_documents({})

    completed_batches = db.batches.count_documents({
        "status": "completed"
    })

    total_notifications = db.notifications.count_documents({})

    waste_data = db.batches.find(
        {},
        {"predictedWaste": 1}
    )

    total_waste = 0

    for item in waste_data:
        total_waste += item.get("predictedWaste", 0)

    return {
        "totalBatches": total_batches,
        "completedBatches": completed_batches,
        "totalWaste": round(total_waste, 2),
        "totalNotifications": total_notifications
    }