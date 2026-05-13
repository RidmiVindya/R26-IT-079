const Batch = require("../models/Batch");
const { runWastePrediction } = require("../services/pythonService");
const { runSaltPrediction } = require("../services/saltPythonService");
const Notification = require("../models/Notification");
const { generateWasteNotificationMessage } = require("../services/notificationService");

// CREATE batch
const createBatch = async (req, res) => {
  try {
    const { fishType, rawWeight , date, location } = req.body;

    if (!fishType || rawWeight === undefined) {
      return res.status(400).json({
        message: "fishType and rawWeight are required",
      });
    }

    const batchId = `BATCH-${Date.now()}`;

    const batch = new Batch({
      batchId,
      fishType,
      rawWeight,
       date,
      location
    });

    await batch.save();

    res.status(201).json({
      message: "Batch created successfully",
      batch,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error creating batch",
      error: error.message,
    });
  }
};

// GET one batch by batchId
const getBatchById = async (req, res) => {
  try {
    const { batchId } = req.params;

    const batch = await Batch.findOne({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    res.status(200).json({
      message: "Batch fetched successfully",
      batch,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error fetching batch",
      error: error.message,
    });
  }
};

// GET all batches
const getAllBatches = async (req, res) => {
  try {
    const batches = await Batch.find().sort({ createdAt: -1 });

    res.status(200).json({
      message: "Batches fetched successfully",
      count: batches.length,
      batches,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error fetching batches",
      error: error.message,
    });
  }
};

// UPDATE batch by batchId
const updateBatch = async (req, res) => {
  try {
    const { batchId } = req.params;
    const { fishType, rawWeight, cleanedWeight, saltAmount, saltingDurationHours, saltingStatus } = req.body;

    const batch = await Batch.findOne({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    if (fishType !== undefined) batch.fishType = fishType;
    if (rawWeight !== undefined) batch.rawWeight = rawWeight;
    if (cleanedWeight !== undefined) batch.cleanedWeight = cleanedWeight;
    if (saltAmount !== undefined) batch.saltAmount = saltAmount;
    if (saltingDurationHours !== undefined) batch.saltingDurationHours = saltingDurationHours;
    if (saltingStatus !== undefined) batch.saltingStatus = saltingStatus;

    await batch.save();

    res.status(200).json({
      message: "Batch updated successfully",
      batch,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error updating batch",
      error: error.message,
    });
  }
};

// DELETE batch by batchId
const deleteBatch = async (req, res) => {
  try {
    const { batchId } = req.params;

    const batch = await Batch.findOneAndDelete({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    res.status(200).json({
      message: "Batch deleted successfully",
      batch,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error deleting batch",
      error: error.message,
    });
  }
};

const predictWaste = async (req, res) => {
  try {
    const { batchId } = req.params;

    const batch = await Batch.findOne({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    const result = await runWastePrediction(batch.fishType, batch.rawWeight);

    batch.predictedWaste = result.predictedWaste;
    await batch.save();

    const message = generateWasteNotificationMessage(
      batch.fishType,
      batch.batchId,
      batch.predictedWaste
    );

    const notification = new Notification({
      batchId: batch.batchId,
      fishType: batch.fishType,
      predictedWaste: batch.predictedWaste,
      recipientType: "recycler",
      message,
      status: "generated",
    });

    await notification.save();

    res.status(200).json({
      message: "Waste predicted and notification generated successfully",
      batch: {
        batchId: batch.batchId,
        fishType: batch.fishType,
        rawWeight: batch.rawWeight,
        predictedWaste: batch.predictedWaste,
      },
      notification,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error predicting waste",
      error: error.message,
    });
  }
};
const predictSalt = async (req, res) => {
  try {
    const { batchId } = req.params;
    const { cleanedWeight } = req.body;

    if (cleanedWeight === undefined) {
      return res.status(400).json({
        message: "cleanedWeight is required",
      });
    }

    const batch = await Batch.findOne({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    const result = await runSaltPrediction(batch.fishType, cleanedWeight);

    batch.cleanedWeight = cleanedWeight;
    batch.saltAmount = result.saltAmount;

    await batch.save();

    res.status(200).json({
      message: "Salt predicted successfully",
      batchId: batch.batchId,
      fishType: batch.fishType,
      cleanedWeight: batch.cleanedWeight,
      saltAmount: batch.saltAmount,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error predicting salt",
      error: error.message || error,
    });
  }
};

const startSalting = async (req, res) => {
  try {
    const { batchId } = req.params;
    const { initialSaltedWeight } = req.body;

    if (initialSaltedWeight === undefined) {
      return res.status(400).json({
        message: "initialSaltedWeight is required",
      });
    }

    const batch = await Batch.findOne({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    batch.initialSaltedWeight = initialSaltedWeight;
    batch.currentWeight = initialSaltedWeight;
    batch.saltingStartTime = new Date();
    batch.saltingStatus = "in_progress";

    await batch.save();

    res.status(200).json({
      message: "Salting started successfully",
      batchId: batch.batchId,
      initialSaltedWeight: batch.initialSaltedWeight,
      currentWeight: batch.currentWeight,
      saltingStartTime: batch.saltingStartTime,
      saltingStatus: batch.saltingStatus,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error starting salting",
      error: error.message,
    });
  }
};

const sendWasteNotification = async (req, res) => {
  try {
    const { batchId } = req.params;

    const batch = await Batch.findOne({ batchId });

    if (!batch) {
      return res.status(404).json({
        message: "Batch not found",
      });
    }

    if (!batch.predictedWaste || batch.predictedWaste <= 0) {
      return res.status(400).json({
        message: "Waste prediction must be completed before sending notification",
      });
    }

    const message = generateWasteNotificationMessage(
      batch.fishType,
      batch.batchId,
      batch.predictedWaste
    );

    const notification = new Notification({
      batchId: batch.batchId,
      fishType: batch.fishType,
      predictedWaste: batch.predictedWaste,
      recipientType: "recycler",
      message,
      status: "generated",
    });

    await notification.save();

    res.status(200).json({
      message: "Waste notification generated successfully",
      notification,
    });
  } catch (error) {
    res.status(500).json({
      message: "Error generating waste notification",
      error: error.message,
    });
  }
};

module.exports = {
  createBatch,
  getBatchById,
  getAllBatches,
  updateBatch,
  deleteBatch,
  predictWaste,
  predictSalt,
  startSalting,
  sendWasteNotification,
};