from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from models.offer import Offer
from sqlalchemy.orm import Session

from database import SessionLocal
from models.campaign import Campaign

router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    offer_id: int
    channel: str
    status: Literal["draft", "active", "paused"] = "draft"


@router.get("/")
def get_campaigns():
    db: Session = SessionLocal()

    campaigns = db.query(Campaign).all()

    result = []

    for campaign in campaigns:
        result.append({
            "id": campaign.id,
            "name": campaign.name,
            "offer_id": campaign.offer_id,
            "channel": campaign.channel,
            "status": campaign.status
        })

    db.close()

    return {
        "campaigns": result
    }


@router.post("/")
def create_campaign(campaign: CampaignCreate):
    db: Session = SessionLocal()

    if not db.get(Offer, campaign.offer_id):
        db.close()
        raise HTTPException(404, "Offer not found")

    new_campaign = Campaign(
        name=campaign.name,
        offer_id=campaign.offer_id,
        channel=campaign.channel,
        status=campaign.status
    )

    db.add(new_campaign)
    db.commit()
    db.refresh(new_campaign)

    result = {
        "id": new_campaign.id,
        "name": new_campaign.name,
        "offer_id": new_campaign.offer_id,
        "channel": new_campaign.channel,
        "status": new_campaign.status
    }

    db.close()

    return {
        "message": "Campaign created",
        "campaign": result
    }