const mongoose = require("mongoose");

const batchSchema = new mongoose.Schema(
    {
        batchId: {
            type: String,
            required: true,
            unique: true,
        },
        fishType: {
            type: String,
            required: true,
        },
        rawWeight: {
            type: Number,
            required: true,
        },
        date: {
            type: Date,
            default: null,
        },
        location: {
            type: String,
            default: "",
        },
        predictedWaste: {
            type: Number,
            default: 0,
        },
        cleanedWeight: {
            type: Number,
            default: 0,
        },
        saltAmount: {
            type: Number,
            default: 0,
        },
        saltingDurationHours: {
            type: Number,
            default: 0,
        },
        saltingStartTime: {
            type: Date,
            default: null,
        },
        saltingStatus: {
            type: String,
            default: "not_started",
        },
        initialSaltedWeight: {
            type: Number,
            default: 0,
        },
        currentWeight: {
            type: Number,
            default: 0,
        },
        weightLoss: {
            type: Number,
            default: 0,
        },
        weightLossPercentage: {
            type: Number,
            default: 0,
        },
        
    },
    { timestamps: true }
);

module.exports = mongoose.model("Batch", batchSchema);