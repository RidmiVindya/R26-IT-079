from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "TimeAndSpoilagePredictionService"
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8003

    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "fish_drying_db"
    MONGO_COLLECTION_PREDICTIONS: str = "prediction_records"

    DRYING_TIME_MODEL_PATH: str = "app/ml_models/drying_time_model.pkl"
    INITIAL_DRYING_TIME_MODEL_PATH: str = "app/ml_models/initial_drying_time_model.pkl"
    INITIAL_PREDICTION_MODEL_PATH: str = "app/ml_models/initial_prediction_model.pkl"
    SPOILAGE_RISK_MODEL_PATH: str = "app/ml_models/spoilage_risk_model.pkl"

    # --- Integration with sibling services -------------------------------
    # Jayani's waste/salt/batch service (owns batch data).
    JAYANI_API_URL: str = "http://localhost:8001"
    # Milan's IoT drying-oven service (live sensor readings).
    MILAN_API_URL: str = "http://localhost:8002"
    # Collection holding the single active drying batch pointer.
    MONGO_COLLECTION_ACTIVE_DRYING: str = "active_drying_batch"

    ALLOWED_FISH_TYPES: tuple = (
        "sprats",
        "salaya",
        "hurulla",
        "kumbalawa",
        "kelawalla",
        "balaya",
        "mora",
        "linna",
        "paraw",
        "thalapath",
        "tuna",
        "mackerel",
        # Thora is a distinct species from Thalapath, but no Thora-specific
        # training data exists yet. Accepted here and mapped to the
        # Thalapath model/encoding as a stand-in until real Thora data is
        # collected and the model is retrained (see FISH_TYPE_ALIASES).
        "thora",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
