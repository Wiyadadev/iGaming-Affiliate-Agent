from sqlalchemy import Column, Integer, String, Float, ForeignKey
from database import Base


class Tracking(Base):
    __tablename__ = "tracking"

    id = Column(Integer, primary_key=True, index=True)
    content_id = Column(Integer, ForeignKey("contents.id"))

    tracking_code = Column(
        String,
        unique=True,
        index=True,
        nullable=False
    )

    clicks = Column(Integer, default=0)
    registrations = Column(Integer, default=0)
    ftd = Column(Integer, default=0)
    revenue = Column(Float, default=0)