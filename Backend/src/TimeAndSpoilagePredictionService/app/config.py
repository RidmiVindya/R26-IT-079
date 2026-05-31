from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "TimeAndSpoilagePredictionService"
    APP_VERSION: str = "1.0.0"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8001

    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB_NAME: str = "fish_drying_db"
    MONGO_COLLECTION_PREDICTIONS: str = "prediction_records"

    DRYING_TIME_MODEL_PATH: str = "app/ml_models/drying_time_model.pkl"
    INITIAL_DRYING_TIME_MODEL_PATH: str = "app/ml_models/initial_drying_time_model.pkl"
    SPOILAGE_RISK_MODEL_PATH: str = "app/ml_models/spoilage_risk_model.pkl"

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
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
