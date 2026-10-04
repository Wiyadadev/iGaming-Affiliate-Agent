import os
import uuid
from datetime import datetime

from dotenv import load_dotenv
from ai import generate_text
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.orm import Session

from database import SessionLocal
from models.content import Content
from models.campaign import Campaign
from models.offer import Offer
from models.tracking import Tracking


load_dotenv()


router = APIRouter(
    prefix="/content",
    tags=["Content"]
)


# =========================
# Request Models
# =========================

class ContentCreate(BaseModel):
    campaign_id: int
    platform: str
    title: str
    body: str = Field(min_length=1, max_length=20000)
    status: Literal["draft"] = "draft"


class ContentGenerate(BaseModel):
    campaign_id: int
    platform: str
    topic: str
    language: str = "English"


# =========================
# GET ALL CONTENT
# =========================

@router.get("/")
def get_content():

    db: Session = SessionLocal()

    contents = db.query(Content).all()

    result = []

    for content in contents:
        tracking = db.query(Tracking).filter(Tracking.content_id == content.id).first()
        result.append({
            "id": content.id,
            "campaign_id": content.campaign_id,
            "platform": content.platform,
            "title": content.title,
            "body": content.body,
            "status": content.status,
            "published_at": content.published_at,
            "tracking_url": f"/tracking/{tracking.tracking_code}" if tracking else None
        })

    db.close()

    return {
        "contents": result
    }


# =========================
# CREATE CONTENT MANUALLY
# =========================

@router.post("/")
def create_content(content: ContentCreate):

    db: Session = SessionLocal()

    if not db.get(Campaign, content.campaign_id):
        db.close()
        raise HTTPException(404, "Campaign not found")

    new_content = Content(
        campaign_id=content.campaign_id,
        platform=content.platform,
        title=content.title,
        body=content.body,
        status=content.status
    )

    db.add(new_content)
    db.commit()
    db.refresh(new_content)

    result = {
        "id": new_content.id,
        "campaign_id": new_content.campaign_id,
        "platform": new_content.platform,
        "title": new_content.title,
        "body": new_content.body,
        "status": new_content.status,
        "published_at": new_content.published_at
    }

    db.close()

    return {
        "message": "Content created",
        "content": result
    }


# =========================
# AI GENERATE CONTENT
# =========================

@router.post("/generate")
def generate_content(request: ContentGenerate):

    db: Session = SessionLocal()

    # Find campaign
    campaign = (
        db.query(Campaign)
        .filter(Campaign.id == request.campaign_id)
        .first()
    )

    if not campaign:
        db.close()

        raise HTTPException(
            status_code=404,
            detail="Campaign not found"
        )

    # Find offer
    offer = (
        db.query(Offer)
        .filter(Offer.id == campaign.offer_id)
        .first()
    )

    if not offer:
        db.close()

        raise HTTPException(
            status_code=404,
            detail="Offer not found"
        )

    # AI Prompt
    prompt = f"""
You are an iGaming affiliate content assistant.

Create affiliate marketing content based ONLY on
the information provided below.

Campaign:
- Name: {campaign.name}
- Platform: {request.platform}

Offer:
- Brand: {offer.brand}
- Name: {offer.name}
- GEO: {offer.geo}
- CPA: {offer.cpa}
- Revenue Share: {offer.revenue_share}

Topic:
{request.topic}

Language:
{request.language}

Requirements:
- Make the content natural and engaging.
- Adapt the style to the requested platform.
- Do not invent bonuses.
- Do not invent prices.
- Do not invent statistics.
- Do not invent guarantees.
- Do not invent offer details.
- Do not make unsupported claims.
- Keep the content appropriate for the target GEO.

Return only the content text.
"""

    # Generate with OpenAI
    try:
        generated_content = generate_text(prompt)
    except HTTPException:
        db.close()
        raise

    # Save generated content
    new_content = Content(
        campaign_id=campaign.id,
        platform=request.platform,
        title=request.topic,
        body=generated_content,
        status="draft"
    )

    db.add(new_content)
    db.commit()
    db.refresh(new_content)

    result = {
        "id": new_content.id,
        "campaign_id": new_content.campaign_id,
        "platform": new_content.platform,
        "title": new_content.title,
        "body": new_content.body,
        "status": new_content.status,
        "published_at": new_content.published_at
    }

    db.close()

    return {
        "message": "AI content generated and saved",
        "content": result
    }


# =========================
# APPROVE CONTENT
# =========================

@router.post("/{content_id}/approve")
def approve_content(content_id: int):

    db: Session = SessionLocal()

    content = (
        db.query(Content)
        .filter(Content.id == content_id)
        .first()
    )

    if not content:
        db.close()

        raise HTTPException(
            status_code=404,
            detail="Content not found"
        )

    if content.status != "draft":
        db.close()

        raise HTTPException(
            status_code=400,
            detail="Only draft content can be approved"
        )

    content.status = "approved"

    db.commit()
    db.refresh(content)

    result = {
        "id": content.id,
        "campaign_id": content.campaign_id,
        "platform": content.platform,
        "title": content.title,
        "body": content.body,
        "status": content.status,
        "published_at": content.published_at
    }

    db.close()

    return {
        "message": "Content approved",
        "content": result
    }


# =========================
# PUBLISH CONTENT
# + CREATE TRACKING LINK
# =========================

@router.post("/{content_id}/publish")
def publish_content(content_id: int):

    from api.agent import publish_content as publish
    result = publish(content_id)
    item = result['content']
    item['tracking_code'] = result['tracking']['tracking_code']
    item['tracking_url'] = result['tracking']['url']
    return {'message': result['message'], 'content': item}
