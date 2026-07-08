from app.config.db import notifications_collection


def serialize_notification(notification):
    notification["_id"] = str(notification["_id"])
    return notification


async def get_all_notifications():
    notifications = list(notifications_collection.find().sort("createdAt", -1))
    notifications = [serialize_notification(n) for n in notifications]

    return {
        "message": "Notifications fetched successfully",
        "count": len(notifications),
        "notifications": notifications,
    }


async def get_notifications_by_batch_id(batch_id: str):
    notifications = list(
        notifications_collection.find({"batchId": batch_id}).sort("createdAt", -1)
    )

    notifications = [serialize_notification(n) for n in notifications]

    return {
        "message": "Batch notifications fetched successfully",
        "count": len(notifications),
        "notifications": notifications,
    }
