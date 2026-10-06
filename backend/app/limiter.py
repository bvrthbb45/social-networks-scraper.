from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory storage: fine for a single instance. Use Redis storage if the API
# is ever scaled horizontally. Behind a reverse proxy run uvicorn with
# --proxy-headers so the real client address is used.
limiter = Limiter(key_func=get_remote_address)
