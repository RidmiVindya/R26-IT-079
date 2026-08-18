import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("APP_HOST", "0.0.0.0")
port = int(os.getenv("APP_PORT", "8003"))

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=host, port=port, reload=True)