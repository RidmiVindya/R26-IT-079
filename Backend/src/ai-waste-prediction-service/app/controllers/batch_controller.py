# pyrefly: ignore-file
# type: ignore
from fastapi import HTTPException
from datetime import datetime
from app.config.db import batches_collection, notifications_collection
from app.services.notification_service import generate_waste_notification_message

FISH_WASTE_RATIOS = {
    "Balaya": 0.3333,
    "Linna": 0.4872,
    "Salaya": 0.0526,
    "Thalapath": 0.2000,
    "Thora": 0.4000,
    "Paraw": 0.4000,
    "Mora": 0.2500,
    "Hurulla": 0.3900,
    "Kelawalla": 0.1875,
    "Kumbalawa": 0.0500,
    "Sprats": 0.3000,
    "Mackerel": 0.3000,
    "Sardine": 0.3000,
    "Anchovy": 0.3000,
}

FISH_SALT_RATIOS = {
    "Balaya": 0.20,
    "Linna": 0.22,
    "Salaya": 0.18,
    "Thalapath": 0.25,
    "Thora": 0.25,
    "Paraw": 0.22,
    "Mora": 0.25,
    "Hurulla": 0.20,
    "Kelawalla": 0.20,
    "Kumbalawa": 0.18,
    "Sprats": 0.20,
    "Mackerel": 0.20,
    "Sardine": 0.20,
    "Anchovy": 0.20,
}


def get_waste_ratio(fish_type: str) -> float:
    if not fish_type:
        return 0.25
    normalized = str(fish_type).strip().title()
    return FISH_WASTE_RATIOS.get(normalized, 0.25)


def get_salt_ratio(fish_type: str) -> float:
    if not fish_type:
        return 0.20
    normalized = str(fish_type).strip().title()
    return FISH_SALT_RATIOS.get(normalized, 0.20)


def clean_weight_val(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).lower().replace("kg", "").replace("g", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def serialize_doc(doc):
    if not doc:
        return doc
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])

    weight_keys = [
        "rawWeight",
        "cleanedWeight",
        "predictedWaste",
        "saltAmount",
        "currentWeight",
        "initialSaltedWeight",
        "weightGain",
        "weightLoss",
    ]

    for key in weight_keys:
        if key in doc and doc[key] is not None:
            doc[key] = clean_weight_val(doc[key])

    return doc


def calculate_recommended_duration(cleaned_weight: float, fish_type: str = "Mackerel") -> int:
    cleaned_weight = float(cleaned_weight)
    normalized = str(fish_type).strip().title() if fish_type else ""

    if normalized in ["Thalapath", "Thora", "Mora", "Paraw", "Balaya"]:
        if cleaned_weight <= 0.5:
            return 8
        elif cleaned_weight <= 1.5:
            return 12
        elif cleaned_weight <= 3.0:
            return 18
        else:
            return 24
    elif normalized in ["Salaya", "Kumbalawa", "Kelawalla", "Linna", "Hurulla", "Sprats", "Sardine", "Anchovy"]:
        if cleaned_weight <= 0.5:
            return 4
        elif cleaned_weight <= 1.5:
            return 6
        elif cleaned_weight <= 3.0:
            return 8
        else:
            return 12
    else:
        if cleaned_weight <= 0.5:
            return 6
        elif cleaned_weight <= 1.5:
            return 8
        elif cleaned_weight <= 3.0:
            return 12
        else:
            return 16


async def create_batch(data: dict):
    fish_type = data.get("fishType")
    raw_weight = data.get("rawWeight")

    if not fish_type or raw_weight is None:
        raise HTTPException(status_code=400, detail="fishType and rawWeight are required")

    try:
        raw_weight_val = clean_weight_val(raw_weight)
        if raw_weight_val <= 0:
            raise HTTPException(
                status_code=400,
                detail="Raw fish weight must be greater than 0"
            )
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid rawWeight format")

    batch_id = data.get("batchId") or f"BATCH-{int(datetime.now().timestamp() * 1000)}"

    waste_ratio = get_waste_ratio(fish_type)
    predicted_waste = round(raw_weight_val * waste_ratio, 3)
    cleaned_weight = round(raw_weight_val - predicted_waste, 3)

    salt_ratio = get_salt_ratio(fish_type)
    salt_amount = round(cleaned_weight * salt_ratio, 3)
    duration = calculate_recommended_duration(cleaned_weight, fish_type)

    batch = {
        "batchId": batch_id,
        "fishType": fish_type,
        "rawWeight": raw_weight_val,
        "date": data.get("date") or datetime.now().strftime("%Y-%m-%d"),
        "location": data.get("location", ""),
        "predictedWaste": predicted_waste,
        "cleanedWeight": cleaned_weight,
        "saltAmount": salt_amount,
        "recommendedDuration": duration,
        "saltingDurationHours": duration,
        "saltingStartTime": None,
        "saltingStatus": "Not Started",
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


def sync_batch_current_weight(batch):
    if not batch:
        return batch
    status = str(batch.get("saltingStatus", "")).strip().lower()
    if status == "completed":
        initial = float(batch.get("initialSaltedWeight") or batch.get("cleanedWeight") or 0)
        salt_amount = float(batch.get("saltAmount") or 0)
        if salt_amount <= 0 and initial > 0:
            fish_type = batch.get("fishType", "Mackerel")
            salt_ratio = get_salt_ratio(fish_type)
            salt_amount = round(initial * salt_ratio, 3)

        added_salt = round(0.75 * salt_amount, 3)
        expected_current = round(initial + added_salt, 3)
        weight_gain_pct = round((added_salt / initial) * 100, 1) if initial > 0 else 0.0

        batch["currentWeight"] = expected_current
        batch["weightGain"] = added_salt
        batch["weightGainPercentage"] = weight_gain_pct
        batch["weightChange"] = added_salt
        batch["weightChangeGrams"] = round(added_salt * 1000, 1) if initial < 10 else round(added_salt, 1)
        batch["weightChangeFormatted"] = f"+{round(added_salt * 1000, 1)} g" if initial < 10 else f"+{round(added_salt, 1)} g"
        batch["weightLoss"] = 0
        batch["weightLossPercentage"] = 0
        
        batches_collection.update_one(
            {"_id": batch["_id"]},
            {
                "$set": {
                    "currentWeight": expected_current,
                    "weightGain": added_salt,
                    "weightGainPercentage": weight_gain_pct,
                    "weightChange": added_salt,
                    "weightLoss": 0,
                    "weightLossPercentage": 0,
                    "updatedAt": datetime.now(),
                }
            }
        )
    return batch


async def get_batch_by_id(batch_id: str):
    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    batch = sync_batch_current_weight(batch)

    return {
        "message": "Batch fetched successfully",
        "batch": serialize_doc(batch),
    }


async def get_all_batches():
    batches = list(batches_collection.find().sort("createdAt", -1))
    batches = [serialize_doc(sync_batch_current_weight(batch)) for batch in batches]

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
        "predictedWaste",
        "saltAmount",
        "recommendedDuration",
        "saltingDurationHours",
        "saltingStatus",
        "date",
        "location",
    ]

    update_data = {}

    for field in allowed_fields:
        if field in data and data[field] is not None:
            update_data[field] = data[field]

    if "rawWeight" in update_data or "fishType" in update_data:
        fish_type = update_data.get("fishType", batch.get("fishType", "Mackerel"))
        raw_w = float(update_data.get("rawWeight", batch.get("rawWeight", 0)))
        if raw_w > 0:
            w_ratio = get_waste_ratio(fish_type)
            p_waste = round(raw_w * w_ratio, 3)
            c_weight = round(raw_w - p_waste, 3)

            s_ratio = get_salt_ratio(fish_type)
            s_amount = round(c_weight * s_ratio, 3)
            dur = calculate_recommended_duration(c_weight, fish_type)

            update_data["predictedWaste"] = p_waste
            update_data["cleanedWeight"] = c_weight
            update_data["saltAmount"] = s_amount
            update_data["recommendedDuration"] = dur
            update_data["saltingDurationHours"] = dur

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
    fish_type = batch.get("fishType", "Mackerel")

    ratio = get_waste_ratio(fish_type)
    predicted_waste = round(raw_weight * ratio, 3)
    cleaned_weight = round(raw_weight - predicted_waste, 3)

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

    fish_type = batch.get("fishType", "Mackerel")
    cleaned_weight = float(batch.get("cleanedWeight", 0))

    if cleaned_weight <= 0:
        raw_weight = float(batch.get("rawWeight", 0))
        if raw_weight > 0:
            w_ratio = get_waste_ratio(fish_type)
            predicted_waste = round(raw_weight * w_ratio, 3)
            cleaned_weight = round(raw_weight - predicted_waste, 3)
        else:
            raise HTTPException(status_code=400, detail="Please set a valid raw fish weight first")

    s_ratio = get_salt_ratio(fish_type)
    salt_amount = round(cleaned_weight * s_ratio, 3)

    recommended_duration = calculate_recommended_duration(cleaned_weight, fish_type)

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "cleanedWeight": cleaned_weight,
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
        "fishType": fish_type,
        "cleanedWeight": cleaned_weight,
        "saltAmount": salt_amount,
        "saltingDurationHours": recommended_duration,
        "recommendedDuration": recommended_duration,
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

    now = datetime.now()
    cleaned_weight = float(batch.get("cleanedWeight") or 0)

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "saltingStartTime": now,
                "saltingStatus": "In Progress",
                "initialSaltedWeight": cleaned_weight,
                "currentWeight": cleaned_weight,
                "updatedAt": now,
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

    if isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        except ValueError:
            start_time = datetime.now()

    duration = float(batch.get("recommendedDuration") or 12)

    elapsed_hours = (datetime.now() - start_time).total_seconds() / 3600

    already_completed = str(batch.get("saltingStatus", "")).strip().lower() == "completed"

    progress = min((elapsed_hours / duration) * 100, 100) if duration > 0 else 100
    if already_completed:
        progress = 100

    cleaned_weight = float(batch.get("cleanedWeight") or 0)
    initial = float(batch.get("initialSaltedWeight") or cleaned_weight or 0)

    # Fetch or compute recommended salt amount
    salt_amount = float(batch.get("saltAmount") or 0)
    if salt_amount <= 0 and initial > 0:
        fish_type = batch.get("fishType", "Mackerel")
        salt_ratio = get_salt_ratio(fish_type)
        salt_amount = round(initial * salt_ratio, 3)

    # Increase weight by up to 3/4 of recommended salt amount as salting completes
    added_salt_weight = 0.75 * salt_amount
    completion_ratio = min(elapsed_hours / duration, 1.0) if duration > 0 else 1.0
    if already_completed:
        completion_ratio = 1.0

    current = initial + (completion_ratio * added_salt_weight)

    weight_gain = current - initial
    weight_gain_percentage = (weight_gain / initial) * 100 if initial > 0 else 0

    remaining = max(duration - elapsed_hours, 0)
    if already_completed:
        remaining = 0

    # Once a batch has been marked Completed (by elapsed time or manually),
    # never let a status recompute here revert it back to In Progress.
    status = "Completed" if already_completed or progress >= 100 else "In Progress"

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "initialSaltedWeight": initial,
                "currentWeight": current,
                "weightGain": weight_gain,
                "weightGainPercentage": weight_gain_percentage,
                "weightLoss": 0,
                "weightLossPercentage": 0,
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
        "cleanedWeight": round(cleaned_weight if cleaned_weight > 0 else initial, 3),
        "initialSaltedWeight": round(initial, 3),
        "currentWeight": round(current, 3),
        "saltAmount": round(salt_amount, 3),
        "addedSaltWeight": round(added_salt_weight, 3),
        "weightGain": round(weight_gain, 3),
        "weightGainPercentage": round(weight_gain_percentage, 1),
        "weightChange": round(weight_gain, 3),
        "weightChangeGrams": round(weight_gain * 1000, 1) if initial < 10 else round(weight_gain, 1),
        "weightChangeFormatted": f"+{round(weight_gain * 1000, 1)} g" if initial < 10 else f"+{round(weight_gain, 1)} g",
        "weightLoss": 0,
        "weightLossPercentage": 0,
        "remainingHours": round(remaining, 2),
    }

async def complete_salting(batch_id: str):

    batch = batches_collection.find_one({"batchId": batch_id})

    if not batch:
        raise HTTPException(
            status_code=404,
            detail="Batch not found"
        )

    if batch.get("saltingStartTime") is None:
        raise HTTPException(
            status_code=400,
            detail="Salting has not started."
        )

    cleaned_weight = float(batch.get("cleanedWeight") or 0)
    initial = float(batch.get("initialSaltedWeight") or cleaned_weight or 0)

    salt_amount = float(batch.get("saltAmount") or 0)
    if salt_amount <= 0 and initial > 0:
        fish_type = batch.get("fishType", "Mackerel")
        salt_ratio = get_salt_ratio(fish_type)
        salt_amount = round(initial * salt_ratio, 3)

    added_salt_weight = 0.75 * salt_amount
    final_weight = initial + added_salt_weight

    batches_collection.update_one(
        {"batchId": batch_id},
        {
            "$set": {
                "saltingStatus": "Completed",
                "currentWeight": final_weight,
                "weightGain": added_salt_weight,
                "weightGainPercentage": (added_salt_weight / initial) * 100 if initial > 0 else 0,
                "weightLoss": 0,
                "weightLossPercentage": 0,
                "updatedAt": datetime.now(),
            }
        }
    )

    updated_batch = batches_collection.find_one({"batchId": batch_id})

    return {
        "message": "Salting marked as completed",
        "batch": serialize_doc(updated_batch),
    }


async def get_traceability_dashboard():
    batches = list(batches_collection.find().sort("_id", -1))

    total_batches = len(batches)

    total_waste = 0
    total_percentage = 0

    completed_batches = 0
    in_progress_batches = 0

    recent_batches = []

    for batch in batches:
        predicted = float(batch.get("predictedWaste") or 0)
        raw = float(batch.get("rawWeight") or 0)

        total_waste += predicted

        if raw > 0:
            total_percentage += (predicted / raw) * 100

        status = str(batch.get("saltingStatus", batch.get("status", ""))).strip().lower()

        if status == "completed":
            completed_batches += 1
        elif status in ["in progress", "in_progress"]:
            in_progress_batches += 1

        recent_batches.append({
            "_id": str(batch["_id"]),
            "batchId": batch.get("batchId"),
            "fishType": batch.get("fishType"),
            "rawWeight": raw,
            "predictedWaste": predicted,
            "wastePercentage": round((predicted / raw) * 100, 2) if raw > 0 else 0,
            "status": batch.get("saltingStatus", "Not Started"),
            "date": batch.get("date", ""),
            "location": batch.get("location", ""),
        })

    average_percentage = (
        total_percentage / total_batches
        if total_batches > 0
        else 0
    )

    return {
        "totalBatches": total_batches,
        "totalWasteKg": round(total_waste, 2),
        "averageWastePercentage": round(average_percentage, 2),
        "avgWastePercentage": round(average_percentage, 2),
        "completedBatches": completed_batches,
        "inProgressBatches": in_progress_batches,
        "records": total_batches,
        "recentBatches": recent_batches,
    }


async def get_processing_reports():
    batches = list(batches_collection.find().sort("_id", -1))

    reports = []

    for batch in batches:
        raw = float(batch.get("rawWeight", 0))
        predicted = float(batch.get("predictedWaste", 0))

        reports.append({
            "batchId": batch.get("batchId"),
            "fishType": batch.get("fishType"),
            "date": batch.get("date", ""),
            "rawWeight": raw,
            "predictedWaste": predicted,
            "wastePercentage": round((predicted / raw) * 100, 2) if raw > 0 else 0,
            "status": batch.get("saltingStatus", "Not Started"),
        })

    return {
        "reports": reports
    }