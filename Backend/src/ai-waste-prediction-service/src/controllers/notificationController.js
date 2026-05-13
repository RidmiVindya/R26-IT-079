const Notification = require("../models/Notification");

const getAllNotifications = async (req, res) => {
  try {
    const notifications = await Notification.find().sort({ createdAt: -1 });

    res.status(200).json({
      message: "Notifications fetched successfully",
      count: notifications.length,
      notifications,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error fetching notifications",
      error: error.message,
    });
  }
};

const getNotificationsByBatchId = async (req, res) => {
  try {
    const { batchId } = req.params;

    const notifications = await Notification.find({ batchId }).sort({ createdAt: -1 });

    res.status(200).json({
      message: "Batch notifications fetched successfully",
      count: notifications.length,
      notifications,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error fetching batch notifications",
      error: error.message,
    });
  }
};

module.exports = {
  getAllNotifications,
  getNotificationsByBatchId,
};