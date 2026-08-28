# pyrefly: ignore [missing-import]
from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from app.config.db import db
from app.models.salting_model import StartSaltingRequest

router = APIRouter(tags=["Salting Monitoring"])


@router.post("/{batch_id}/start")
async def start_salting(batch_id: str, data: StartSaltingRequest):
    batch = db.batches.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    start_time = datetime.utcnow()
    completion_time = start_time + timedelta(hours=data.recommendedDuration)

    db.batches.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "saltingStartTime": start_time,
                "recommendedDuration": data.recommendedDuration,
                "recommendedSalt": data.recommendedSalt,
                "saltingCompletionTime": completion_time,
                "saltingStatus": "in_progress",
            }
        },
    )

    return {
        "message": "Salting started successfully",
        "batchId": batch_id,
        "startTime": start_time,
        "recommendedDuration": data.recommendedDuration,
        "completionTime": completion_time,
        "status": "in_progress",
    }


@router.get("/{batch_id}/status")
async def get_salting_status(batch_id: str):
    batch = db.batches.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    start_time = batch.get("saltingStartTime")
    recommended_duration = batch.get("recommendedDuration", 12)

    if not start_time:
        return {
            "batchId": batch_id,
            "status": "not_started",
            "message": "Salting has not started yet",
        }

    current_time = datetime.utcnow()

    elapsed_seconds = (current_time - start_time).total_seconds()
    elapsed_hours = elapsed_seconds / 3600

    remaining_hours = recommended_duration - elapsed_hours

    progress = (elapsed_hours / recommended_duration) * 100
    progress = min(progress, 100)

    if elapsed_hours >= recommended_duration:
        status = "completed"
        cleaned_weight = float(batch.get("cleanedWeight") or 0)
        initial = float(batch.get("initialSaltedWeight") or cleaned_weight or 0)
        salt_amount = float(batch.get("recommendedSalt") or batch.get("saltAmount") or 0)
        added_salt = round(0.75 * salt_amount, 3)
        final_weight = round(initial + added_salt, 3)

        db.batches.update_one(
            {"batchId": batch_id},
            {
                "$set": {
                    "saltingStatus": "completed",
                    "saltingCompletedAt": current_time,
                    "currentWeight": final_weight,
                    "weightGain": added_salt,
                }
            },
        )

        remaining_hours = 0
    else:
        status = "in_progress"

    return {
        "batchId": batch_id,
        "fishType": batch.get("fishType"),
        "cleanedWeight": batch.get("cleanedWeight"),
        "recommendedSalt": batch.get("recommendedSalt"),
        "recommendedDuration": recommended_duration,
        "startTime": start_time,
        "currentTime": current_time,
        "elapsedHours": round(elapsed_hours, 2),
        "remainingHours": round(remaining_hours, 2),
        "progress": round(progress, 2),
        "status": status,
    }


@router.post("/{batch_id}/complete")
async def complete_salting_manually(batch_id: str):
    batch = db.batches.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    completed_time = datetime.utcnow()
    cleaned_weight = float(batch.get("cleanedWeight") or 0)
    initial = float(batch.get("initialSaltedWeight") or cleaned_weight or 0)
    salt_amount = float(batch.get("recommendedSalt") or batch.get("saltAmount") or 0)
    added_salt = round(0.75 * salt_amount, 3)
    final_weight = round(initial + added_salt, 3)

    db.batches.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "saltingStatus": "completed",
                "saltingCompletedAt": completed_time,
                "currentWeight": final_weight,
                "weightGain": added_salt,
            }
        },
    )

    return {
        "message": "Salting completed manually",
        "batchId": batch_id,
        "status": "completed",
        "completedAt": completed_time,
    }


@router.get("")
@router.get("/")
async def get_all_salting_records():
    records = []

    for batch in db.batches.find({}):
        records.append({
            "_id": str(batch.get("_id")),
            "batchId": batch.get("batchId"),
            "fishType": batch.get("fishType"),
            "cleanedWeight": batch.get("cleanedWeight"),
            "recommendedSalt": batch.get("recommendedSalt"),
            "recommendedDuration": batch.get("recommendedDuration"),
            "saltingStartTime": batch.get("saltingStartTime"),
            "saltingCompletedAt": batch.get("saltingCompletedAt"),
            "saltingStatus": batch.get("saltingStatus", "not_started"),
        })

    return records