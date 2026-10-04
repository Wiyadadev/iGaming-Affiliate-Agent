from fastapi import APIRouter
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.orm import Session

from database import SessionLocal
from models.offer import Offer

router = APIRouter(prefix="/offers", tags=["Offers"])


class OfferCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    brand: str
    geo: str
    affiliate_url: HttpUrl
    cpa: float = Field(default=0, ge=0, allow_inf_nan=False)
    revenue_share: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)


@router.get("/")
def get_offers():
    db: Session = SessionLocal()

    offers = db.query(Offer).all()

    result = []

    for offer in offers:
        result.append({
            "id": offer.id,
            "name": offer.name,
            "brand": offer.brand,
            "geo": offer.geo,
            "affiliate_url": offer.affiliate_url,
            "cpa": offer.cpa,
            "revenue_share": offer.revenue_share,
            "active": offer.active
        })

    db.close()

    return {
        "offers": result
    }


@router.post("/")
def create_offer(offer: OfferCreate):
    db: Session = SessionLocal()

    new_offer = Offer(
        name=offer.name,
        brand=offer.brand,
        geo=offer.geo,
        affiliate_url=str(offer.affiliate_url),
        cpa=offer.cpa,
        revenue_share=offer.revenue_share
    )

    db.add(new_offer)
    db.commit()
    db.refresh(new_offer)

    result = {
        "id": new_offer.id,
        "name": new_offer.name,
        "brand": new_offer.brand,
        "geo": new_offer.geo,
        "affiliate_url": new_offer.affiliate_url,
        "cpa": new_offer.cpa,
        "revenue_share": new_offer.revenue_share,
        "active": new_offer.active
    }

    db.close()

    return {
        "message": "Offer created",
        "offer": result
    }