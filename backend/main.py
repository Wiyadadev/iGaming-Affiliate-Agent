import asyncio
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
from database import Base, engine
from models.offer import Offer
from models.campaign import Campaign
from models.content import Content
from models.tracking import Tracking
from api import agent
from api.offers import router as offers_router
from api.campaigns import router as campaigns_router
from api.content import router as content_router
from api.tracking import router as tracking_router

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(bind=engine)
    yield
    agent.scheduler_running = False
    if agent.scheduler_task:
        agent.scheduler_task.cancel()
        try:
            await agent.scheduler_task
        except asyncio.CancelledError:
            pass
        agent.scheduler_task = None

app = FastAPI(title='iGaming Affiliate Agent', version='1.0.0', lifespan=lifespan)

@app.middleware('http')
async def protect_backend(request: Request, call_next):
    token = os.getenv('ADMIN_TOKEN', '')
    public = request.url.path in ('/', '/health') or request.url.path.startswith('/dashboard')
    click = request.method == 'GET' and request.url.path.startswith('/tracking/') and request.url.path.count('/') == 2 and request.url.path not in ('/tracking/stats', '/tracking/campaign-stats', '/tracking/recommendations')
    if token and not public and not click:
        supplied = request.headers.get('Authorization', '')
        if not hmac.compare_digest(supplied, 'Bearer ' + token):
            return JSONResponse({'detail': 'Enter the workspace access token.'}, status_code=401)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    return response

app.mount('/dashboard', StaticFiles(directory=BASE_DIR / 'frontend', html=True), name='dashboard')
for router in (offers_router, campaigns_router, content_router, tracking_router, agent.router):
    app.include_router(router)

@app.get('/')
def root():
    return RedirectResponse('/dashboard/')

@app.get('/health')
def health():
    return {'status': 'ok', 'version': '1.0.0'}

@app.get('/workspace/status')
def workspace_status():
    return {'ai_configured': bool(os.getenv('OPENAI_API_KEY')), 'telegram_configured': bool(os.getenv('TELEGRAM_BOT_TOKEN') and os.getenv('TELEGRAM_CHAT_ID')), 'model': os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')}
