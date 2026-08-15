import asyncio
import logging

from app.alert_service import check_alerts, save_alerts
from app.database import get_active_session
from app.drying_controller import ControllerError, controller
from app.sensor_parser import get_live_sensor_data
from app.settings import SENSOR_SAVE_INTERVAL_SECONDS

logger = logging.getLogger(__name__)


async def auto_save_sensor_data():
    """The controller heartbeat: captures telemetry and drives AUTO/cooling without a UI poll."""
    while True:
        try:
            data = await asyncio.to_thread(get_live_sensor_data)
            data = await asyncio.to_thread(controller.process_reading, data)
            active = get_active_session()
            alerts = check_alerts(data)
            if alerts:
                save_alerts(alerts, data["device_id"], active["batch_id"] if active else None)
        except ControllerError as exc:
            logger.error("Controller heartbeat fault: %s", exc)
        except Exception:
            logger.exception("Controller heartbeat failed")
        await asyncio.sleep(SENSOR_SAVE_INTERVAL_SECONDS)
