from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
import uuid

from database import SessionLocal
from models.tracking import Tracking
from models.content import Content
from models.campaign import Campaign
from models.offer import Offer

router = APIRouter(prefix="/tracking", tags=["Tracking"])


class TrackingCreate(BaseModel):
    content_id: int


@router.post("/")
def create_tracking(tracking: TrackingCreate):
    db: Session = SessionLocal()

    tracking_code = uuid.uuid4().hex[:8]

    new_tracking = Tracking(
        content_id=tracking.content_id,
        tracking_code=tracking_code
    )

    db.add(new_tracking)
    db.commit()
    db.refresh(new_tracking)

    result = {
        "id": new_tracking.id,
        "content_id": new_tracking.content_id,
        "tracking_code": new_tracking.tracking_code,
        "clicks": new_tracking.clicks,
        "registrations": new_tracking.registrations,
        "ftd": new_tracking.ftd,
        "revenue": new_tracking.revenue
    }

    db.close()

    return {
        "message": "Tracking link created",
        "tracking": result
    }

@router.get("/stats")
def get_tracking_stats():
    db: Session = SessionLocal()

    trackings = db.query(Tracking).all()

    clicks = sum(t.clicks for t in trackings)
    registrations = sum(t.registrations for t in trackings)
    ftd = sum(t.ftd for t in trackings)
    revenue = sum(t.revenue for t in trackings)

    epc = revenue / clicks if clicks > 0 else 0

    db.close()

    return {
        "clicks": clicks,
        "registrations": registrations,
        "ftd": ftd,
        "revenue": revenue,
        "epc": round(epc, 2)
    }

@router.get("/campaign-stats")
def get_campaign_stats():

    db: Session = SessionLocal()
    campaigns = db.query(Campaign).all()
    result = []

    for campaign in campaigns:
        contents = db.query(Content).filter(
            Content.campaign_id == campaign.id
        ).all()

        content_ids = [content.id for content in contents]

        if not content_ids:
            result.append({
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "clicks": 0,
                "registrations": 0,
                "ftd": 0,
                "revenue": 0,
                "epc": 0
            })
            continue

        trackings = db.query(Tracking).filter(
            Tracking.content_id.in_(content_ids)
        ).all()

        clicks = sum(t.clicks or 0 for t in trackings)
        registrations = sum(t.registrations or 0 for t in trackings)
        ftd = sum(t.ftd or 0 for t in trackings)
        revenue = sum(t.revenue or 0 for t in trackings)

        epc = round(revenue / clicks, 2) if clicks > 0 else 0

        result.append({
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "clicks": clicks,
            "registrations": registrations,
            "ftd": ftd,
            "revenue": revenue,
            "epc": epc
        })

    db.close()

    return {"campaigns": result}


@router.get("/recommendations")
def get_recommendations():

    db: Session = SessionLocal()

    campaigns = db.query(Campaign).all()

    recommendations = []

    for campaign in campaigns:

        contents = db.query(Content).filter(
            Content.campaign_id == campaign.id
        ).all()

        content_ids = [content.id for content in contents]

        if not content_ids:
            recommendations.append({
                "campaign_id": campaign.id,
                "campaign_name": campaign.name,
                "status": "no_data",
                "recommendation": "Create content for this campaign."
            })
            continue

        trackings = db.query(Tracking).filter(
            Tracking.content_id.in_(content_ids)
        ).all()

        clicks = sum(t.clicks or 0 for t in trackings)
        registrations = sum(t.registrations or 0 for t in trackings)
        ftd = sum(t.ftd or 0 for t in trackings)
        revenue = sum(t.revenue or 0 for t in trackings)

        conversion_rate = (
            registrations / clicks * 100
            if clicks > 0
            else 0
        )

        epc = (
            revenue / clicks
            if clicks > 0
            else 0
        )

        if clicks == 0:

            status = "no_data"

            recommendation = (
                "No traffic yet. Create and publish more content "
                "to generate initial traffic."
            )

        elif registrations == 0:

            status = "weak"

            recommendation = (
                "Traffic is coming in but there are no registrations. "
                "Test a different content angle or call-to-action."
            )

        elif ftd == 0:

            status = "needs_optimization"

            recommendation = (
                "Registrations are happening but there are no FTDs. "
                "Improve offer positioning and conversion quality."
            )

        elif conversion_rate >= 30 and epc >= 10:

            status = "strong"

            recommendation = (
                "Strong performance. Create more content and "
                "prioritize this campaign."
            )

        else:

            status = "stable"

            recommendation = (
                "Campaign is converting. Continue testing new "
                "content variations and monitor performance."
            )

        recommendations.append({
            "campaign_id": campaign.id,
            "campaign_name": campaign.name,
            "clicks": clicks,
            "registrations": registrations,
            "ftd": ftd,
            "revenue": revenue,
            "conversion_rate": round(conversion_rate, 2),
            "epc": round(epc, 2),
            "status": status,
            "recommendation": recommendation
        })

    db.close()

    return {
        "recommendations": recommendations
    }


@router.get("/{tracking_code}")
def track_click(tracking_code: str):
    db: Session = SessionLocal()

    tracking = (
        db.query(Tracking)
        .filter(Tracking.tracking_code == tracking_code)
        .first()
    )

    if not tracking:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Tracking link not found"
        )

    tracking.clicks = (tracking.clicks or 0) + 1

    content = db.query(Content).filter(
        Content.id == tracking.content_id
    ).first()

    if not content:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Content not found"
        )

    campaign = db.query(Campaign).filter(
        Campaign.id == content.campaign_id
    ).first()

    if not campaign:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Campaign not found"
        )

    offer = db.query(Offer).filter(
        Offer.id == campaign.offer_id
    ).first()

    if not offer:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Offer not found"
        )

    destination = offer.affiliate_url

    db.commit()
    db.close()

    return RedirectResponse(url=destination)
class RevenueCreate(BaseModel):
    amount: float = Field(ge=0, allow_inf_nan=False)


@router.post("/{tracking_code}/registration")
def add_registration(tracking_code: str):
    db: Session = SessionLocal()

    tracking = (
        db.query(Tracking)
        .filter(Tracking.tracking_code == tracking_code)
        .first()
    )

    if not tracking:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Tracking link not found"
        )

    tracking.registrations += 1

    db.commit()

    result = {
        "tracking_code": tracking.tracking_code,
        "registrations": tracking.registrations
    }

    db.close()

    return {
        "message": "Registration recorded",
        "tracking": result
    }


@router.post("/{tracking_code}/ftd")
def add_ftd(tracking_code: str):
    db: Session = SessionLocal()

    tracking = (
        db.query(Tracking)
        .filter(Tracking.tracking_code == tracking_code)
        .first()
    )

    if not tracking:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Tracking link not found"
        )

    tracking.ftd += 1

    db.commit()

    result = {
        "tracking_code": tracking.tracking_code,
        "ftd": tracking.ftd
    }

    db.close()

    return {
        "message": "FTD recorded",
        "tracking": result
    }


@router.post("/{tracking_code}/revenue")
def add_revenue(
    tracking_code: str,
    revenue: RevenueCreate
):
    db: Session = SessionLocal()

    tracking = (
        db.query(Tracking)
        .filter(Tracking.tracking_code == tracking_code)
        .first()
    )

    if not tracking:
        db.close()
        raise HTTPException(
            status_code=404,
            detail="Tracking link not found"
        )

    tracking.revenue += revenue.amount

    db.commit()

    result = {
        "tracking_code": tracking.tracking_code,
        "revenue": tracking.revenue
    }

    db.close()

    return {
        "message": "Revenue recorded",
        "tracking": result
    }

