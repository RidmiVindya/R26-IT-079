const { exec } = require("child_process");

const runSaltPrediction = (fishType, cleanedWeight) => {
  return new Promise((resolve, reject) => {
    const command = `py ml/predict_salt.py "${fishType}" ${cleanedWeight}`;

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
  runSaltPrediction,
};