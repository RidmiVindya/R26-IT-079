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

    # --- Drying safety limits --------------------------------------------
    # Hard caps applied to anything this service recommends to the drying
    # oven. The oven acts on target_temperature_c directly (it drives the
    # heater toward it), so an out-of-range prediction must never reach it.
    #
    # Change these here, or override per-environment in .env
    # (e.g. MAX_DRYING_TEMPERATURE_C=65).
    #
    # The oven-drying dataset spans 83-110 C (fast oven drying of small
    # samples, anchored to a measured balaya 163 g / 100 C / 30 min run).
    # 120 C matches the oven service's own ControlProfileRequest bound
    # (target_temperature_c: le=120), so this is the real hardware ceiling
    # rather than an arbitrary limit.
    MAX_DRYING_TEMPERATURE_C: float = 120.0
    MIN_DRYING_TEMPERATURE_C: float = 40.0
    # Longest drying run the oven should ever be asked to schedule. Oven-scale
    # batches finish in well under an hour; this only blocks runaway values.
    MAX_DRYING_DURATION_HOURS: float = 12.0

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
