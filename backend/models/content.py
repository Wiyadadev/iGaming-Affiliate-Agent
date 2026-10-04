from sqlalchemy import Column, Integer, String, ForeignKey, Text, DateTime
from database import Base
from datetime import datetime


class Content(Base):
    __tablename__ = "contents"

    id = Column(Integer, primary_key=True, index=True)

    campaign_id = Column(
        Integer,
        ForeignKey("campaigns.id"),
        nullable=False
    )

    platform = Column(String, nullable=False)

    title = Column(String)

    body = Column(Text)

    status = Column(
        String,
        default="draft"
    )

    published_at = Column(
        DateTime,
        nullable=True
    )