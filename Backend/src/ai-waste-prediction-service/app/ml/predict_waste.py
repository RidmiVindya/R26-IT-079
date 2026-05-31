import sys
import json
import pandas as pd
from sklearn.linear_model import LinearRegression

# Read command-line arguments
fish_type = sys.argv[1]
raw_weight = float(sys.argv[2])

# Load dataset
df = pd.read_csv("ml/dataset.csv")

# One-hot encode fish_type
df_encoded = pd.get_dummies(df, columns=["fish_type"])

# Prepare training data
X = df_encoded.drop("waste_amount", axis=1)
y = df_encoded["waste_amount"]

# Train model
model = LinearRegression()
model.fit(X, y)

# Create input row
input_data = {"raw_weight": raw_weight}

for col in X.columns:
    if col != "raw_weight":
        input_data[col] = 1 if col == f"fish_type_{fish_type}" else 0

input_df = pd.DataFrame([input_data])

# Ensure same column order
input_df = input_df[X.columns]

# Predict
predicted_waste = model.predict(input_df)[0]

# Return JSON
print(json.dumps({
    "predictedWaste": round(float(predicted_waste), 2)
}))