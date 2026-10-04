from sqlalchemy import Column, Integer, String, Float, Boolean
from database import Base


class Offer(Base):
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    brand = Column(String)
    geo = Column(String)
    affiliate_url = Column(String)
    cpa = Column(Float, default=0)
    revenue_share = Column(Float, default=0)
    active = Column(Boolean, default=True)