from fastapi import HTTPException
from datetime import datetime
from app.config.db import batches_collection, notifications_collection
from app.services.notification_service import generate_waste_notification_message


def serialize_doc(doc):
    if doc and "_id" in doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def create_batch(data: dict):
    fish_type = data.get("fishType")
    raw_weight = data.get("rawWeight")

    if not fish_type or raw_weight is None:
        raise HTTPException(status_code=400, detail="fishType and rawWeight are required")

    batch_id = f"BATCH-{int(datetime.now().timestamp() * 1000)}"

    batch = {
        "batchId": batch_id,
        "fishType": fish_type,
        "rawWeight": raw_weight,
        "date": data.get("date"),
        "location": data.get("location", ""),
        "predictedWaste": 0,
        "cleanedWeight": 0,
        "saltAmount": 0,
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

    predicted_waste = float(batch["rawWeight"]) * 0.15

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "predictedWaste": predicted_waste,
                "updatedAt": datetime.now(),
            }
        }
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
        "message": "Waste predicted and notification generated successfully",
        "batch": {
            "batchId": batch["batchId"],
            "fishType": batch["fishType"],
            "rawWeight": batch["rawWeight"],
            "predictedWaste": predicted_waste,
        },
        "notification": serialize_doc(notification),
    }


async def predict_salt(batch_id: str, data: dict):
    cleaned_weight = data.get("cleanedWeight")

    if cleaned_weight is None:
        raise HTTPException(status_code=400, detail="cleanedWeight is required")

    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    salt_amount = float(cleaned_weight) * 0.25

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "cleanedWeight": cleaned_weight,
                "saltAmount": salt_amount,
                "updatedAt": datetime.now(),
            }
        }
    )

    return {
        "message": "Salt predicted successfully",
        "batchId": batch_id,
        "fishType": batch["fishType"],
        "cleanedWeight": cleaned_weight,
        "saltAmount": salt_amount,
    }


async def start_salting(batch_id: str, data: dict):
    initial_salted_weight = data.get("initialSaltedWeight")

    if initial_salted_weight is None:
        raise HTTPException(status_code=400, detail="initialSaltedWeight is required")

    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    salting_start_time = datetime.now()

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "initialSaltedWeight": initial_salted_weight,
                "currentWeight": initial_salted_weight,
                "saltingStartTime": salting_start_time,
                "saltingStatus": "in_progress",
                "updatedAt": datetime.now(),
            }
        }
    )

    return {
        "message": "Salting started successfully",
        "batchId": batch_id,
        "initialSaltedWeight": initial_salted_weight,
        "currentWeight": initial_salted_weight,
        "saltingStartTime": salting_start_time,
        "saltingStatus": "in_progress",
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