const express = require("express");
const cors = require("cors");
const dotenv = require("dotenv");
const batchRoutes = require("./routes/batchRoutes");
const notificationRoutes = require("./routes/notificationRoutes");

dotenv.config();

const app = express();

app.use(cors());
app.use(express.json());

app.use("/api/batches", batchRoutes);
app.use("/api/notifications", notificationRoutes);

module.exports = app;