const express = require("express");
const router = express.Router();

const {
  getAllNotifications,
  getNotificationsByBatchId,
} = require("../controllers/notificationController");

router.get("/", getAllNotifications);
router.get("/batch/:batchId", getNotificationsByBatchId);

module.exports = router;