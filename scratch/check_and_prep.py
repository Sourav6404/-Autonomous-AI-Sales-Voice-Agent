import os
import sys
sys.path.insert(0, os.path.abspath("."))
import psutil
import socket
import asyncio
from sqlalchemy import text
from backend.app.core.config import settings
from backend.app.core.database import AsyncSessionLocal

def clear_port(port=8000):
    cleared = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            for conn in proc.net_connections(kind='inet'):
                if conn.laddr.port == port:
                    print(f"Terminating PID {proc.pid} ({proc.name()}) using port {port}")
                    proc.kill()
                    cleared.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if not cleared:
        print(f"Port {port} is clear.")
    else:
        print(f"Killed {len(cleared)} processes on port {port}.")

async def check_services():
    # 1. Check PostgreSQL
    try:
        async with AsyncSessionLocal() as session:
            res = await session.execute(text("SELECT 1"))
            assert res.scalar_one() == 1
            print("PostgreSQL 16: CONNECTED & HEALTHY")
    except Exception as e:
        print(f"PostgreSQL Connection Error: {e}")
        return False

    # 2. Check Redis
    try:
        if settings.REDIS_URL:
            import redis
            r = redis.from_url(settings.REDIS_URL, socket_timeout=1.0)
            r.ping()
            print("Redis: CONNECTED & HEALTHY")
        else:
            print("Redis: In-memory store active (development fallback)")
    except Exception as e:
        print(f"Redis Notice: {e} (Falling back to in-memory)")

    # 3. Check Providers in Settings
    print(f"AI Provider: {settings.DEFAULT_AI_PROVIDER} (Model: {settings.OPENAI_MODEL})")
    print(f"OpenAI API Key: {'DETECTED & CONFIGURED' if settings.OPENAI_API_KEY and not settings.OPENAI_API_KEY.startswith('mock-') else 'NOT CONFIGURED'}")
    print(f"STT Provider: {settings.STT_PROVIDER} (Model: {settings.DEEPGRAM_MODEL})")
    print(f"Deepgram API Key: {'DETECTED & CONFIGURED' if settings.DEEPGRAM_API_KEY else 'NOT CONFIGURED'}")
    print(f"TTS Provider: {settings.TTS_PROVIDER} (Model: {settings.CARTESIA_MODEL})")
    print(f"Cartesia API Key: {'DETECTED & CONFIGURED' if settings.CARTESIA_API_KEY else 'NOT CONFIGURED'}")

    return True

if __name__ == "__main__":
    clear_port(8000)
    asyncio.run(check_services())
