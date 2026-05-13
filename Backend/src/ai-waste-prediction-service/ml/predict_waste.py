import sys
import json
import pandas as pd
import joblib
import os

# Get current ml folder path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load trained model
model_path = os.path.join(BASE_DIR, "waste_model.pkl")
model = joblib.load(model_path)

# Read arguments from Node.js
Fish_type = sys.argv[1]
Raw_weight = float(sys.argv[2])

# Match training column names exactly
input_data = pd.DataFrame({
    "Fish Type": [Fish_type.capitalize()],
    "Raw weight": [Raw_weight]
})

# Predict waste
predicted_waste = model.predict(input_data)[0]

print(json.dumps({
    "predictedWaste": round(float(predicted_waste), 2)
}))