import os
import sys
import tempfile
from pathlib import Path

# Import the app against a disposable database, never a user's workspace DB.
temp_db = tempfile.TemporaryDirectory()
os.environ['DATABASE_URL'] = 'sqlite:///' + str(Path(temp_db.name) / 'test.db')
os.environ.pop('OPENAI_API_KEY', None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import pytest
from fastapi.testclient import TestClient
from main import app
from database import Base, engine

@pytest.fixture(scope='session', autouse=True)
def cleanup_database():
    yield
    engine.dispose()
    temp_db.cleanup()

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('ADMIN_TOKEN', raising=False)
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    Base.metadata.drop_all(engine)
    with TestClient(app) as client:
        yield client

def create_chain(client):
    offer = client.post('/offers/', json={'name':'Test partner','brand':'Sample','geo':'DE','affiliate_url':'https://example.com/partner','cpa':50,'revenue_share':20}).json()['offer']
    campaign = client.post('/campaigns/', json={'name':'Test campaign','offer_id':offer['id'],'channel':'telegram','status':'active'}).json()['campaign']
    content = client.post('/content/', json={'campaign_id':campaign['id'],'platform':'telegram','title':'Intro','body':'A sample draft for review.'}).json()['content']
    return offer,campaign,content

def test_startup_without_ai_key(client):
    assert client.get('/health').json()['status'] == 'ok'
    assert client.get('/dashboard/').status_code == 200
    assert client.get('/agent/analytics').json() == {'campaigns':[]}
    _,campaign,_ = create_chain(client)
    assert client.post('/agent/generate-content',json={'campaign_id':campaign['id']}).status_code == 503

def test_approval_tracking_and_metrics(client):
    _,campaign,content = create_chain(client)
    cid = content['id']
    assert client.post(f'/agent/publish/{cid}').status_code == 400
    assert client.post(f'/agent/approve/{cid}').json()['content']['status'] == 'approved'
    assert client.get('/agent/pending').json()['items'][0]['status'] == 'approved'
    published = client.post(f'/agent/publish/{cid}').json()
    tracking = published['tracking']['tracking_code']
    assert client.post(f'/agent/publish/{cid}').json()['tracking']['tracking_code'] == tracking
    assert client.post(f'/content/{cid}/publish').json()['content']['tracking_code'] == tracking
    assert client.get(f'/tracking/{tracking}', follow_redirects=False).headers['location'] == 'https://example.com/partner'
    for event,value in [('registration',0),('ftd',0),('revenue',50)]:
        assert client.post(f'/agent/tracking/{tracking}',json={'event':event,'value':value}).status_code == 200
    metrics = client.get('/agent/analytics').json()['campaigns'][0]
    assert (metrics['clicks'],metrics['registrations'],metrics['ftd'],metrics['revenue'],metrics['conversion_rate'],metrics['epc']) == (1,1,1,50,100,50)
    assert client.get('/content/').json()['contents'][0]['published_at'] is not None
    assert client.get('/content/').json()['contents'][0]['tracking_url'] == f'/tracking/{tracking}'

def test_validation_and_orphans(client):
    assert client.post('/offers/',json={'name':'x','brand':'x','geo':'DE','affiliate_url':'javascript:alert(1)'}).status_code == 422
    assert client.post('/campaigns/',json={'name':'x','offer_id':999,'channel':'blog'}).status_code == 404
    assert client.post('/content/',json={'campaign_id':999,'platform':'blog','title':'x','body':'x'}).status_code == 404
    _,_,content = create_chain(client)
    assert client.post('/content/',json={'campaign_id':content['campaign_id'],'platform':'blog','title':'x','body':'x','status':'published'}).status_code == 422
    assert client.post('/agent/tracking/missing',json={'event':'revenue','value':-10}).status_code == 422

def test_rejected_content_cannot_be_published(client):
    _,_,content = create_chain(client)
    cid=content['id']
    assert client.post(f'/agent/reject/{cid}').status_code == 200
    assert client.post(f'/agent/approve/{cid}').status_code == 400
    assert client.post(f'/agent/publish/{cid}').status_code == 400

def test_token_protection(client,monkeypatch):
    monkeypatch.setenv('ADMIN_TOKEN','test-workspace-token')
    assert client.get('/health').status_code == 200
    assert client.get('/dashboard/').status_code == 200
    assert client.get('/agent/analytics').status_code == 401
    assert client.post('/campaigns/',json={}).status_code == 401
    assert client.get('/agent/analytics',headers={'Authorization':'Bearer test-workspace-token'}).status_code == 200

def test_ai_language_and_draft(client,monkeypatch):
    from api import agent
    prompts=[]
    def fake_generate(prompt):
        prompts.append(prompt)
        return 'English draft for human review.'
    monkeypatch.setattr(agent,'generate_text',fake_generate)
    _,campaign,_=create_chain(client)
    result=client.post('/agent/generate-content',json={'campaign_id':campaign['id'],'language':'English','topic':'English introduction'}).json()
    assert result['content']['status']=='draft'
    assert 'entirely in English' in prompts[0]
    assert 'entirely in Russian' not in prompts[0]

def test_auto_cycle_ignores_paused_campaigns(client,monkeypatch):
    from api import agent
    from database import SessionLocal
    from models.campaign import Campaign
    monkeypatch.setattr(agent,'generate_text',lambda prompt:'Sample test draft')
    _,campaign,_=create_chain(client)
    with SessionLocal() as db:
        db.get(Campaign,campaign['id']).status='paused'
        db.commit()
    assert client.post('/agent/run-cycle').status_code==404
