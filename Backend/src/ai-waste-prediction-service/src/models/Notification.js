const mongoose = require("mongoose");

const notificationSchema = new mongoose.Schema(
  {
    batchId: {
      type: String,
      required: true,
    },
    fishType: {
      type: String,
      required: true,
    },
    predictedWaste: {
      type: Number,
      required: true,
    },
    recipientType: {
      type: String,
      default: "recycler",
    },
    message: {
      type: String,
      required: true,
    },
    status: {
      type: String,
      default: "generated",
    },
    sentAt: {
      type: Date,
      default: Date.now,
    },
  },
  { timestamps: true }
);

module.exports = mongoose.model("Notification", notificationSchema);