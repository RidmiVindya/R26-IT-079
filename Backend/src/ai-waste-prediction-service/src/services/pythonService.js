const { exec } = require("child_process");

const runWastePrediction = (fishType, rawWeight) => {
  return new Promise((resolve, reject) => {
    const command = `py ml/predict_waste.py "${fishType}" ${rawWeight}`;

    exec(command, (error, stdout, stderr) => {
      if (error) {
        return reject(error);
      }

      if (stderr) {
        return reject(stderr);
      }

      try {
        const result = JSON.parse(stdout);
        resolve(result);
      } catch (parseError) {
        reject(parseError);
      }
    });
  });
};

module.exports = {
  runWastePrediction,
};