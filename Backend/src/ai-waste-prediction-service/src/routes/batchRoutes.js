const express = require("express");
const router = express.Router();

const {
  createBatch,
  getBatchById,
  getAllBatches,
  updateBatch,
  deleteBatch,
  predictWaste,
  predictSalt,
  startSalting,
  sendWasteNotification,
 
} = require("../controllers/batchController");

router.post("/", createBatch);
router.get("/", getAllBatches);
router.get("/:batchId", getBatchById);
router.put("/:batchId", updateBatch);
router.delete("/:batchId", deleteBatch);
router.post("/:batchId/predict-waste", predictWaste);
router.post("/:batchId/predict-salt", predictSalt);
router.post("/:batchId/start-salting", startSalting);
router.post("/:batchId/send-waste-notification", sendWasteNotification);

module.exports = router;