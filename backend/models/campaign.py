from sqlalchemy import Column, Integer, String, ForeignKey
from database import Base


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    offer_id = Column(Integer, ForeignKey("offers.id"))
    channel = Column(String)
    status = Column(String, default="draft")