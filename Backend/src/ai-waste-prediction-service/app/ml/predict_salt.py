import sys
import json
import pandas as pd
from sklearn.linear_model import LinearRegression

fish_type = sys.argv[1]
cleaned_weight = float(sys.argv[2])

import os
csv_path = "app/ml/salt_dataset.csv" if os.path.exists("app/ml/salt_dataset.csv") else ("ml/salt_dataset.csv" if os.path.exists("ml/salt_dataset.csv") else "salt_dataset.csv")
df = pd.read_csv(csv_path)
df_encoded = pd.get_dummies(df, columns=["fish_type"])

X = df_encoded.drop("salt_amount", axis=1)
y = df_encoded["salt_amount"]

model = LinearRegression()
model.fit(X, y)

input_data = {"cleaned_weight": cleaned_weight}

for col in X.columns:
    if col != "cleaned_weight":
        input_data[col] = 1 if col == f"fish_type_{fish_type}" else 0

input_df = pd.DataFrame([input_data])
input_df = input_df[X.columns]

predicted_salt = model.predict(input_df)[0]

# Species-specific & weight-adjusted recommended salting duration (in hours)
if fish_type in ["Thalapath", "Thora", "Mora"]:
    if cleaned_weight <= 0.5:
        recommended_duration = 8
    elif cleaned_weight <= 1.5:
        recommended_duration = 12
    elif cleaned_weight <= 3.0:
        recommended_duration = 18
    else:
        recommended_duration = 24
elif fish_type in ["Salaya", "Kumbalawa", "Sprats", "Sardine", "Anchovy"]:
    if cleaned_weight <= 0.5:
        recommended_duration = 4
    elif cleaned_weight <= 1.5:
        recommended_duration = 6
    elif cleaned_weight <= 3.0:
        recommended_duration = 8
    else:
        recommended_duration = 12
else:
    if cleaned_weight <= 0.5:
        recommended_duration = 6
    elif cleaned_weight <= 1.5:
        recommended_duration = 8
    elif cleaned_weight <= 3.0:
        recommended_duration = 12
    else:
        recommended_duration = 16

print(json.dumps({
    "saltAmount": round(float(predicted_salt), 2),
    "recommendedDuration": recommended_duration
}))