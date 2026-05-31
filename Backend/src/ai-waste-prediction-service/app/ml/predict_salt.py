import sys
import json
import pandas as pd
from sklearn.linear_model import LinearRegression

fish_type = sys.argv[1]
cleaned_weight = float(sys.argv[2])

df = pd.read_csv("ml/salt_dataset.csv")
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

print(json.dumps({
    "saltAmount": round(float(predicted_salt), 2)
}))