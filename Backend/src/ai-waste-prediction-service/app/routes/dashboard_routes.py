from fastapi import APIRouter
from app.config.db import db

router = APIRouter(tags=["Dashboard"])


@router.get("")
@router.get("/")
@router.get("/stats")
@router.get("/stats/")
async def get_dashboard_stats():
    total_batches = db.batches.count_documents({})

    completed_batches = db.batches.count_documents({
        "$or": [
            {"status": "completed"},
            {"saltingStatus": "completed"}
        ]
    })

    in_progress_batches = db.batches.count_documents({
        "$or": [
            {"status": "in_progress"},
            {"saltingStatus": "in_progress"}
        ]
    })

    total_notifications = db.notifications.count_documents({})

    total_waste = 0
    total_raw_weight = 0

    batches = db.batches.find({})

    recent_batches = []

    for batch in batches:
        raw_weight = float(batch.get("rawWeight", 0) or 0)
        predicted_waste = float(batch.get("predictedWaste", 0) or 0)

        total_raw_weight += raw_weight
        total_waste += predicted_waste

        recent_batches.append({
            "_id": str(batch.get("_id")),
            "batchId": batch.get("batchId"),
            "fishType": batch.get("fishType"),
            "rawWeight": raw_weight,
            "predictedWaste": predicted_waste,
            "wastePercentage": round((predicted_waste / raw_weight) * 100, 2)
            if raw_weight > 0 else 0,
            "status": batch.get("saltingStatus", batch.get("status", "pending")),
            "date": batch.get("date"),
            "location": batch.get("location"),
        })

    avg_waste_percentage = (
        round((total_waste / total_raw_weight) * 100, 2)
        if total_raw_weight > 0 else 0
    )

    return {
        "totalBatches": total_batches,
        "totalWasteKg": round(total_waste, 2),
        "averageWastePercentage": avg_waste_percentage,
        "completedBatches": completed_batches,
        "inProgressBatches": in_progress_batches,
        "totalNotifications": total_notifications,
        "records": len(recent_batches),
        "recentBatches": recent_batches
    }