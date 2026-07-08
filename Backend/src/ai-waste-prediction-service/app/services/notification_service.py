def generate_waste_notification_message(fish_type, batch_id, predicted_waste):
    return (
        f"Waste available from {fish_type} batch {batch_id}. "
        f"Predicted waste amount: {predicted_waste} kg. "
        f"Please collect for recycling."
    )