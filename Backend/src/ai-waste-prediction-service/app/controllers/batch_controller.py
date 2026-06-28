from fastapi import HTTPException
from datetime import datetime
from app.config.db import batches_collection, notifications_collection
from app.services.notification_service import generate_waste_notification_message


def serialize_doc(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


def calculate_recommended_duration(cleaned_weight: float):
    """
    Simple salting duration logic.
    You can change these values later based on your project requirement.
    """

    cleaned_weight = float(cleaned_weight)

    if cleaned_weight <= 5:
        return 8
    elif cleaned_weight <= 10:
        return 12
    elif cleaned_weight <= 20:
        return 18
    else:
        return 24


async def create_batch(data: dict):
    fish_type = data.get("fishType")
    raw_weight = data.get("rawWeight")

    if not fish_type or raw_weight is None:
        raise HTTPException(status_code=400, detail="fishType and rawWeight are required")

    batch_id = f"BATCH-{int(datetime.now().timestamp() * 1000)}"

    batch = {
        "batchId": batch_id,
        "fishType": fish_type,
        "rawWeight": float(raw_weight),
        "date": data.get("date"),
        "location": data.get("location", ""),

        "predictedWaste": 0,
        "cleanedWeight": 0,

        "saltAmount": 0,
        "recommendedDuration": 0,
        "saltingDurationHours": 0,

        "saltingStartTime": None,
        "saltingStatus": "not_started",

        "initialSaltedWeight": 0,
        "currentWeight": 0,
        "weightLoss": 0,
        "weightLossPercentage": 0,

        "createdAt": datetime.now(),
        "updatedAt": datetime.now(),
    }

    batches_collection.insert_one(batch)

    return {
        "message": "Batch created successfully",
        "batch": serialize_doc(batch),
    }


async def get_batch_by_id(batch_id: str):
    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    return {
        "message": "Batch fetched successfully",
        "batch": serialize_doc(batch),
    }


async def get_all_batches():
    batches = list(batches_collection.find().sort("createdAt", -1))
    batches = [serialize_doc(batch) for batch in batches]

    return {
        "message": "Batches fetched successfully",
        "count": len(batches),
        "batches": batches,
    }


async def update_batch(batch_id: str, data: dict):
    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    allowed_fields = [
        "fishType",
        "rawWeight",
        "cleanedWeight",
        "saltAmount",
        "recommendedDuration",
        "saltingDurationHours",
        "saltingStatus",
        "date",
        "location",
    ]

    update_data = {}

    for field in allowed_fields:
        if field in data:
            update_data[field] = data[field]

    update_data["updatedAt"] = datetime.now()

    batches_collection.update_one(
        {"batchId": batch_id},
        {"$set": update_data}
    )

    updated_batch = batches_collection.find_one({"batchId": batch_id})

    return {
        "message": "Batch updated successfully",
        "batch": serialize_doc(updated_batch),
    }


async def delete_batch(batch_id: str):
    batch = batches_collection.find_one_and_delete({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    return {
        "message": "Batch deleted successfully",
        "batch": serialize_doc(batch),
    }


async def predict_waste(batch_id: str):
    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    raw_weight = float(batch["rawWeight"])

    predicted_waste = raw_weight * 0.15

    cleaned_weight = raw_weight - predicted_waste

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "predictedWaste": predicted_waste,
                "cleanedWeight": cleaned_weight,
                "updatedAt": datetime.now(),
            }
        }
    )

    updated_batch = batches_collection.find_one({"batchId": batch_id})

    return {
        "message": "Waste predicted successfully",
        "batch": {
            "batchId": updated_batch["batchId"],
            "fishType": updated_batch["fishType"],
            "rawWeight": updated_batch["rawWeight"],
            "predictedWaste": predicted_waste,
            "cleanedWeight": cleaned_weight,
        }
    }
   

async def predict_salt(batch_id: str, data: dict = None):

    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    cleaned_weight = float(batch.get("cleanedWeight", 0))

    if cleaned_weight <= 0:
        raise HTTPException(
            status_code=400,
            detail="Please predict waste first."
        )

    salt_amount = cleaned_weight * 0.25

    recommended_duration = calculate_recommended_duration(cleaned_weight)

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "saltAmount": salt_amount,
                "recommendedDuration": recommended_duration,
                "saltingDurationHours": recommended_duration,
                "updatedAt": datetime.now(),
            }
        }
    )

    return {
        "message": "Salt predicted successfully",
        "batchId": batch["batchId"],
        "fishType": batch["fishType"],
        "cleanedWeight": cleaned_weight,
        "saltAmount": salt_amount,
        "saltingDurationHours": recommended_duration,
    }


async def send_waste_notification(batch_id: str):
    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    predicted_waste = batch.get("predictedWaste", 0)

    if not predicted_waste or predicted_waste <= 0:
        raise HTTPException(
            status_code=400,
            detail="Waste prediction must be completed before sending notification"
        )

    message = generate_waste_notification_message(
        batch["fishType"],
        batch["batchId"],
        predicted_waste
    )

    notification = {
        "batchId": batch["batchId"],
        "fishType": batch["fishType"],
        "predictedWaste": predicted_waste,
        "recipientType": "recycler",
        "message": message,
        "status": "generated",
        "sentAt": datetime.now(),
        "createdAt": datetime.now(),
        "updatedAt": datetime.now(),
    }

    notifications_collection.insert_one(notification)

    return {
        
        "message": "Waste notification generated successfully",
        "notification": serialize_doc(notification),  
    }

async def start_salting(batch_id: str):

    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(
            status_code=404,
            detail="Batch not found"
        )

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "saltingStartTime": datetime.now(),
                "saltingStatus": "In Progress",
                "initialSaltedWeight": batch.get("cleanedWeight", 0),
                "currentWeight": batch.get("cleanedWeight", 0),
                "updatedAt": datetime.now(),
            }
        }
    )

    updated_batch = batches_collection.find_one({"batchId": batch_id})

    return {
        "message": "Salting started successfully",
        "batch": serialize_doc(updated_batch),
    }
    
async def salting_monitor(batch_id: str):

    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(
            status_code=404,
            detail="Batch not found"
        )

    start_time = batch.get("saltingStartTime")

    if start_time is None:
        raise HTTPException(
            status_code=400,
            detail="Salting has not started."
        )

    duration = batch.get("recommendedDuration", 12)

    elapsed_hours = (
        datetime.now() - start_time
    ).total_seconds() / 3600

    progress = min(
        (elapsed_hours / duration) * 100,
        100,
    )

    initial = batch.get("initialSaltedWeight", 0)

    # Demo weight loss (replace later with IoT value)
    current = max(
        initial - (elapsed_hours * 0.15),
        0,
    )

    weight_loss = initial - current

    weight_loss_percentage = (
        (weight_loss / initial) * 100
        if initial > 0
        else 0
    )

    remaining = max(
        duration - elapsed_hours,
        0,
    )

    status = (
        "Completed"
        if progress >= 100
        else "In Progress"
    )

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "currentWeight": current,
                "weightLoss": weight_loss,
                "weightLossPercentage": weight_loss_percentage,
                "saltingStatus": status,
                "updatedAt": datetime.now(),
            }
        }
    )

    return {
        "batchId": batch["batchId"],
        "fishType": batch["fishType"],
        "status": status,
        "startTime": start_time.isoformat(),
        "progress": round(progress, 1),
        "currentWeight": round(current, 2),
        "weightLoss": round(weight_loss, 2),
        "weightLossPercentage": round(weight_loss_percentage, 1),
        "remainingHours": round(remaining, 2),
    }