const generateWasteNotificationMessage = (fishType, batchId, predictedWaste) => {
  return `${fishType} Fish Type (${batchId}) is expected to generate ${predictedWaste} kg of fish waste. Prepare collection for reuse or fish meal processing.`;
};

module.exports = {
  generateWasteNotificationMessage,
};