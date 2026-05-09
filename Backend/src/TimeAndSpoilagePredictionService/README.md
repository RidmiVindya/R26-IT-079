# Time & Spoilage Prediction Service

Microservice within the **R26-IT-079** fish-drying platform that exposes
predictive-analytics APIs:

- **Drying completion time prediction** (RandomForestRegressor)
- **Spoilage risk prediction** (RandomForestClassifier)
- **Smart drying recommendation** (rule-based, sensor-driven)

> The IoT hardware is still being built, so all current dataset/training data
> is **simulated**. The service ships with a deterministic rule-based fallback
> so the API is fully functional even before any `.pkl` model is trained.

---

## Tech Stack

| Layer        | Tools                                              |
| ------------ | -------------------------------------------------- |
| API          | FastAPI, Uvicorn                                   |
| Validation   | Pydantic v2, pydantic-settings                     |
| ML           | scikit-learn, NumPy, Pandas, Joblib                |
| Persistence  | MongoDB (via Motor async driver)                   |
| Datasets     | Excel (`openpyxl`)                                 |

---

## Folder Structure

```
TimeAndSpoilagePredictionService/
├── app/
│   ├── main.py                # FastAPI entry point
│   ├── config.py              # Settings via pydantic-settings (.env)
│   ├── database.py            # Async MongoDB connection
│   ├── models/
│   │   └── prediction_record.py
│   ├── schemas/
│   │   └── prediction_schema.py
│   ├── routes/
│   │   └── prediction_routes.py
│   ├── services/
│   │   ├── drying_time_service.py
│   │   ├── spoilage_risk_service.py
│   │   └── recommendation_service.py
│   ├── ml_models/
│   │   ├── drying_time_model.pkl       # produced by training script
│   │   └── spoilage_risk_model.pkl
│   └── utils/
│       └── helper.py
├── train_models/
│   ├── train_drying_time_model.py
│   └── train_spoilage_risk_model.py
├── datasets/
│   ├── drying_time_dataset.xlsx        # optional - synthetic if missing
│   └── spoilage_risk_dataset.xlsx
├── requirements.txt
├── .env
└── README.md
```

---

## Setup

### 1. Create a virtual environment

```powershell
cd Backend\src\TimeAndSpoilagePredictionService
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure environment

Edit `.env` if MongoDB or ports differ from the defaults:

```
APP_PORT=8001
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=fish_drying_db
```

> If MongoDB is unreachable the service still starts — persistence is simply
> skipped and a warning is logged.

### 4. Train models (optional but recommended)

```powershell
python -m train_models.train_drying_time_model
python -m train_models.train_spoilage_risk_model
```

Models are written to `app/ml_models/*.pkl`. If these files are absent the API
automatically uses its rule-based fallback predictors.

### 5. Run the service

```powershell
uvicorn app.main:app --reload --port 8001
```

Or just:

```powershell
python -m app.main
```

API docs:

- Swagger UI: <http://localhost:8001/docs>
- ReDoc: <http://localhost:8001/redoc>

---

## API Endpoints

Base prefix: `/api/predict`

### `POST /api/predict/drying-time`

**Request**

```json
{
  "fish_type": "sardine",
  "initial_weight_kg": 10.0,
  "current_weight_kg": 7.5,
  "temperature_c": 35.0,
  "humidity_percent": 55.0,
  "elapsed_drying_time_hours": 6.0,
  "weight_loss_rate": 0.42
}
```

**Response**

```json
{
  "batch_id": "BATCH-9F12A4B6CD",
  "predicted_remaining_drying_time_hours": 8.42,
  "model_used": "RandomForestRegressor",
  "created_at": "2026-05-09T12:34:56Z"
}
```

### `POST /api/predict/spoilage-risk`

**Request**

```json
{
  "temperature_c": 32.5,
  "humidity_percent": 65.0,
  "elapsed_drying_time_hours": 8.0,
  "weight_loss_percentage": 28.5,
  "mq136_value": 410
}
```

**Response**

```json
{
  "batch_id": "BATCH-9F12A4B6CD",
  "smell_level": "Medium",
  "spoilage_risk": "Medium",
  "model_used": "RandomForestClassifier",
  "created_at": "2026-05-09T12:34:56Z"
}
```

### `POST /api/predict/recommendation`

**Request**

```json
{
  "temperature_c": 31.0,
  "humidity_percent": 72.0,
  "elapsed_drying_time_hours": 10.0,
  "weight_loss_percentage": 35.0,
  "weight_loss_rate": 0.38,
  "mq136_value": 250,
  "spoilage_risk": "Low"
}
```

**Response**

```json
{
  "batch_id": "BATCH-9F12A4B6CD",
  "drying_status": "Drying In Progress - Early Stage",
  "smart_recommendation": "Increase airflow and reduce humidity",
  "smell_level": "Low",
  "created_at": "2026-05-09T12:34:56Z"
}
```

---

## Business Logic

### MQ-136 smell classification

| Sensor value | Smell level |
| ------------ | ----------- |
| 0 – 300      | Low         |
| 301 – 600    | Medium      |
| 601+         | High        |

### Recommendation set

- Maintain current conditions
- Increase airflow and reduce humidity
- Increase temperature slightly
- Inspect batch and reduce humidity
- Prepare for completion check
- Continue monitoring closely

### Helper functions (`app/utils/helper.py`)

- `calculate_weight_loss_percentage`
- `calculate_weight_loss_rate`
- `classify_smell_level`
- `generate_drying_status`
- `generate_recommendation`

---

## Validation & Error Handling

- All endpoints validate required fields, numeric ranges, and supported
  fish types via Pydantic.
- Validation errors return **400** with a structured JSON body.
- Unhandled exceptions return **500** with a sanitized JSON body.

```json
{
  "success": false,
  "error": "Invalid request payload",
  "detail": [ ... ]
}
```

---

## MongoDB Schema (collection: `prediction_records`)

```json
{
  "batch_id": "BATCH-9F12A4B6CD",
  "prediction_type": "drying_time | spoilage_risk | recommendation",
  "inputs": { ... },
  "predicted_drying_time_hours": 8.42,
  "smell_level": "Low",
  "spoilage_risk": "Low",
  "drying_status": "Drying In Progress - Early Stage",
  "smart_recommendation": "Maintain current conditions",
  "model_used": "RandomForestRegressor",
  "created_at": "2026-05-09T12:34:56Z"
}
```

---

## Notes for Integration

- Default port is `8001` to avoid clashes with other microservices in this
  repo.
- CORS is open (`*`) for development; tighten this before production.
- When real IoT data is wired in, replace the synthetic-data branch in the
  training scripts with the real Excel dataset and re-run training.
