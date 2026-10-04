import os
import uuid
import asyncio

from dotenv import load_dotenv
from ai import generate_text

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from database import SessionLocal
from models.campaign import Campaign
from models.content import Content
from models.offer import Offer
from models.tracking import Tracking
from api.telegram import send_telegram_message


# =========================================================
# CONFIG
# =========================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")



# =========================================================
# ROUTER
# =========================================================

router = APIRouter(
    prefix="/agent",
    tags=["Agent"]
)


# =========================================================
# SCHEDULER STATE
# =========================================================

scheduler_task = None
scheduler_running = False

# Testing interval
# 60 seconds = 1 minute
# Change to 1800 for 30 minutes later.

scheduler_interval = max(60, int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "1800")))


# =========================================================
# DEFAULT LANGUAGE
# =========================================================

DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "Russian")


# =========================================================
# REQUEST MODELS
# =========================================================

class AgentContentRequest(BaseModel):

    campaign_id: int
    platform: str = "telegram"
    topic: str = "Новый рекламный контент"
    language: str = DEFAULT_LANGUAGE


class TrackingEventRequest(BaseModel):

    event: Literal["click", "registration", "ftd", "revenue"]
    value: float = Field(default=0, ge=0, allow_inf_nan=False)


# =========================================================
# HELPER: CAMPAIGN METRICS
# =========================================================

def get_campaign_metrics(
    db: Session,
    campaign: Campaign
):

    contents = (
        db.query(Content)
        .filter(
            Content.campaign_id == campaign.id
        )
        .all()
    )

    content_ids = [
        content.id
        for content in contents
    ]

    trackings = []

    if content_ids:

        trackings = (
            db.query(Tracking)
            .filter(
                Tracking.content_id.in_(content_ids)
            )
            .all()
        )

    clicks = sum(
        t.clicks or 0
        for t in trackings
    )

    registrations = sum(
        t.registrations or 0
        for t in trackings
    )

    ftd = sum(
        t.ftd or 0
        for t in trackings
    )

    revenue = sum(
        t.revenue or 0
        for t in trackings
    )

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

    score = (
        revenue * 10
        + ftd * 5
        + registrations
        + clicks * 0.1
    )

    return {

        "clicks": clicks,

        "registrations":
            registrations,

        "ftd":
            ftd,

        "revenue":
            revenue,

        "conversion_rate":
            round(
                conversion_rate,
                2
            ),

        "epc":
            round(
                epc,
                2
            ),

        "score":
            score

    }


# =========================================================
# HELPER: AGENT ACTION
# =========================================================

def determine_action(metrics):

    if metrics["clicks"] == 0:

        return (
            "CREATE_CONTENT",
            "Трафик отсутствует. Нужно создать новый контент."
        )

    if metrics["registrations"] == 0:

        return (
            "CHANGE_CONTENT",
            "Есть трафик, но нет регистраций. Нужно изменить контент."
        )

    if metrics["ftd"] == 0:

        return (
            "OPTIMIZE_OFFER",
            "Есть регистрации, но нет FTD. Нужно оптимизировать оффер."
        )

    if (
        metrics["conversion_rate"] >= 30
        and metrics["epc"] >= 10
    ):

        return (
            "SCALE",
            "Кампания показывает сильную конверсию и высокий EPC. Можно масштабировать."
        )

    return (
        "TEST",
        "Кампания показывает результаты. Рекомендуется продолжить тестирование."
    )


# =========================================================
# HELPER: DUPLICATE CHECK
# =========================================================

def is_duplicate_content(
    db: Session,
    campaign_id: int,
    title: str,
    body: str
):

    existing = (
        db.query(Content)
        .filter(
            Content.campaign_id == campaign_id,
            Content.title == title,
            Content.body == body
        )
        .first()
    )

    return existing is not None


# =========================================================
# HELPER: GET BEST CAMPAIGN
# =========================================================

def get_best_campaign(
    db: Session
):

    campaigns = (
        db.query(Campaign)
        .join(Offer, Offer.id == Campaign.offer_id)
        .filter(Campaign.status == "active", Offer.active.is_(True))
        .all()
    )

    if not campaigns:

        raise HTTPException(
            status_code=404,
            detail="No active campaigns with an active offer found"
        )

    best_campaign = None
    best_metrics = None

    for campaign in campaigns:

        metrics = get_campaign_metrics(
            db,
            campaign
        )

        if (
            best_campaign is None
            or metrics["score"]
            > best_metrics["score"]
        ):

            best_campaign = campaign
            best_metrics = metrics

    return (
        best_campaign,
        best_metrics
    )


# =========================================================
# HELPER: GENERATE AI CONTENT
# =========================================================

def generate_ai_content(
    campaign,
    offer,
    platform="telegram",
    language=DEFAULT_LANGUAGE,
    action="TEST"
):

    prompt = f"""
You are an affiliate content assistant.

Create one new marketing content variation.

Campaign:
{campaign.name}

Offer:
{offer.name}

Platform:
{platform}

Language:
{language}

Action:
{action}

Rules:

- Write the final content entirely in {language}.
- Use natural, conversational language.
- Do not invent bonuses.
- Do not invent prices.
- Do not invent statistics.
- Do not make guarantees.
- Do not invent offer details.
- Use only the provided campaign and offer information.
- Create a fresh content angle.
- Keep it natural and engaging.
- Return only the final content body in {language}.
"""

    return generate_text(prompt)


# =========================================================
# HELPER: CREATE DRAFT
# =========================================================

def create_draft_content(
    db: Session,
    campaign,
    offer,
    action,
    platform="telegram",
    language=DEFAULT_LANGUAGE,
    title=None
):

    generated_content = generate_ai_content(
        campaign=campaign,
        offer=offer,
        platform=platform,
        language=language,
        action=action
    )

    if title is None:

        title = f"Agent {action} Content"

    if is_duplicate_content(
        db,
        campaign.id,
        title,
        generated_content
    ):

        return None

    content = Content(
        campaign_id=campaign.id,
        platform=platform,
        title=title,
        body=generated_content,
        status="draft"
    )

    db.add(content)

    db.commit()

    db.refresh(content)

    return content


# =========================================================
# GET AGENT DECISIONS
# =========================================================

@router.get("/decisions")
def get_agent_decisions():

    db = SessionLocal()

    try:

        campaigns = (
            db.query(Campaign)
            .all()
        )

        decisions = []

        for campaign in campaigns:

            metrics = get_campaign_metrics(
                db,
                campaign
            )

            action, reason = determine_action(
                metrics
            )

            decisions.append({

                "campaign_id":
                    campaign.id,

                "campaign_name":
                    campaign.name,

                "clicks":
                    metrics["clicks"],

                "registrations":
                    metrics["registrations"],

                "ftd":
                    metrics["ftd"],

                "revenue":
                    metrics["revenue"],

                "conversion_rate":
                    metrics["conversion_rate"],

                "epc":
                    metrics["epc"],

                "action":
                    action,

                "reason":
                    reason

            })

        return {
            "decisions": decisions
        }

    finally:

        db.close()


# =========================================================
# MANUAL AI CONTENT
# =========================================================

@router.post("/generate-content")
def agent_generate_content(
    request: AgentContentRequest
):

    db = SessionLocal()

    try:

        campaign = (
            db.query(Campaign)
            .filter(
                Campaign.id == request.campaign_id
            )
            .first()
        )

        if not campaign:

            raise HTTPException(
                status_code=404,
                detail="Campaign not found"
            )

        offer = (
            db.query(Offer)
            .filter(
                Offer.id == campaign.offer_id
            )
            .first()
        )

        if not offer:

            raise HTTPException(
                status_code=404,
                detail="Offer not found"
            )

        metrics = get_campaign_metrics(
            db,
            campaign
        )

        content = create_draft_content(
            db=db,
            campaign=campaign,
            offer=offer,
            action="CREATE_CONTENT",
            platform=request.platform,
            language=request.language,
            title=request.topic
        )

        if content is None:

            return {

                "message":
                    "Duplicate content detected",

                "status":
                    "skipped",

                "reason":
                    "Identical content already exists"

            }

        return {

            "message":
                "Agent generated new content",

            "language":
                request.language,

            "content": {

                "id":
                    content.id,

                "campaign_id":
                    content.campaign_id,

                "platform":
                    content.platform,

                "title":
                    content.title,

                "body":
                    content.body,

                "status":
                    content.status

            },

            "performance":
                metrics

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Generate content error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# AUTO GENERATE
# =========================================================

@router.post("/auto-generate")
def auto_generate_content():

    db = SessionLocal()

    try:

        (
            best_campaign,
            best_metrics
        ) = get_best_campaign(db)

        offer = (
            db.query(Offer)
            .filter(
                Offer.id == best_campaign.offer_id
            )
            .first()
        )

        if not offer:

            raise HTTPException(
                status_code=404,
                detail="Offer not found"
            )

        action, reason = determine_action(
            best_metrics
        )

        if action == "OPTIMIZE_OFFER":

            return {

                "message":
                    "Agent analyzed campaign",

                "status":
                    "needs_optimization",

                "action":
                    action,

                "reason":
                    reason,

                "campaign":
                    best_campaign.name,

                "performance":
                    best_metrics

            }

        content = create_draft_content(
            db=db,
            campaign=best_campaign,
            offer=offer,
            action=action,
            platform="telegram",
            language=DEFAULT_LANGUAGE
        )

        if content is None:

            return {

                "message":
                    "Duplicate content detected",

                "status":
                    "skipped",

                "campaign":
                    best_campaign.name,

                "action":
                    action

            }

        return {

            "message":
                "Agent automatically selected campaign and generated content",

            "selected_campaign":
                best_campaign.name,

            "language":
                DEFAULT_LANGUAGE,

            "action":
                action,

            "reason":
                reason,

            "performance":
                best_metrics,

            "content": {

                "id":
                    content.id,

                "title":
                    content.title,

                "body":
                    content.body,

                "status":
                    content.status

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Auto-generate error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# RUN AGENT CYCLE
# =========================================================

@router.post("/run-cycle")
def run_agent_cycle():

    db = SessionLocal()

    try:

        (
            best_campaign,
            best_metrics
        ) = get_best_campaign(db)

        action, reason = determine_action(
            best_metrics
        )

        offer = (
            db.query(Offer)
            .filter(
                Offer.id == best_campaign.offer_id
            )
            .first()
        )

        if not offer:

            raise HTTPException(
                status_code=404,
                detail="Offer not found"
            )

        if action == "OPTIMIZE_OFFER":

            return {

                "message":
                    "Agent analyzed campaign",

                "action":
                    action,

                "reason":
                    reason,

                "campaign": {

                    "id":
                        best_campaign.id,

                    "name":
                        best_campaign.name

                },

                "performance":
                    best_metrics

            }

        content = create_draft_content(
            db=db,
            campaign=best_campaign,
            offer=offer,
            action=action,
            platform="telegram",
            language=DEFAULT_LANGUAGE
        )

        if content is None:

            return {

                "message":
                    "Duplicate content detected",

                "status":
                    "skipped",

                "action":
                    action,

                "campaign":
                    best_campaign.name

            }

        return {

            "message":
                "Agent cycle completed",

            "action":
                action,

            "reason":
                reason,

            "language":
                DEFAULT_LANGUAGE,

            "campaign": {

                "id":
                    best_campaign.id,

                "name":
                    best_campaign.name

            },

            "performance":
                best_metrics,

            "content": {

                "id":
                    content.id,

                "title":
                    content.title,

                "status":
                    content.status,

                "body":
                    content.body

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Agent cycle error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# PENDING CONTENT
# =========================================================

@router.get("/pending")
def get_pending_content():

    db = SessionLocal()

    try:

        contents = (
            db.query(Content)
            .filter(
                Content.status.in_(["draft", "approved"])
            )
            .order_by(
                Content.id.desc()
            )
            .all()
        )

        return {

            "count":
                len(contents),

            "items": [

                {

                    "id":
                        content.id,

                    "campaign_id":
                        content.campaign_id,

                    "platform":
                        content.platform,

                    "title":
                        content.title,

                    "body":
                        content.body,

                    "status":
                        content.status

                }

                for content in contents

            ]

        }

    finally:

        db.close()


# =========================================================
# APPROVE CONTENT
# =========================================================
@router.get("/approved")
def get_approved_content():

    db = SessionLocal()

    try:
        contents = (
            db.query(Content)
            .filter(
                Content.status == "approved"
            )
            .order_by(
                Content.id.desc()
            )
            .all()
        )

        return {
            "count": len(contents),

            "items": [
                {
                    "id": content.id,
                    "campaign_id": content.campaign_id,
                    "platform": content.platform,
                    "title": content.title,
                    "body": content.body,
                    "status": content.status
                }
                for content in contents
            ]
        }

    finally:
        db.close()


@router.post("/approve/{content_id}")
def approve_content(
    content_id: int
):

    db = SessionLocal()

    try:

        content = (
            db.query(Content)
            .filter(
                Content.id == content_id
            )
            .first()
        )

        if not content:

            raise HTTPException(
                status_code=404,
                detail="Content not found"
            )

        if content.status != "draft":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Content status is "
                    f"'{content.status}'"
                )
            )

        content.status = "approved"

        db.commit()

        db.refresh(content)

        return {

            "message":
                "Content approved",

            "content": {

                "id":
                    content.id,

                "campaign_id":
                    content.campaign_id,

                "title":
                    content.title,

                "body":
                    content.body,

                "status":
                    content.status

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Approve error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# REJECT CONTENT
# =========================================================

@router.post("/reject/{content_id}")
def reject_content(
    content_id: int
):

    db = SessionLocal()

    try:

        content = (
            db.query(Content)
            .filter(
                Content.id == content_id
            )
            .first()
        )

        if not content:

            raise HTTPException(
                status_code=404,
                detail="Content not found"
            )

        if content.status != "draft":

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Content status is "
                    f"'{content.status}'"
                )
            )

        content.status = "rejected"

        db.commit()

        db.refresh(content)

        return {

            "message":
                "Content rejected",

            "content": {

                "id":
                    content.id,

                "campaign_id":
                    content.campaign_id,

                "title":
                    content.title,

                "status":
                    content.status

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Reject error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# PUBLISH APPROVED CONTENT
# =========================================================

@router.post("/publish/{content_id}")
def publish_content(
    content_id: int
):

    db = SessionLocal()

    try:

        content = (
            db.query(Content)
            .filter(
                Content.id == content_id
            )
            .first()
        )

        if not content:

            raise HTTPException(
                status_code=404,
                detail="Content not found"
            )

        if content.status == "published":

            existing_tracking = (
                db.query(Tracking)
                .filter(
                    Tracking.content_id == content.id
                )
                .first()
            )

            if existing_tracking:

                return {

                    "message":
                        "Content already published",

                    "content": {

                        "id":
                            content.id,

                        "status":
                            content.status

                    },

                    "tracking": {

                        "id":
                            existing_tracking.id,

                        "tracking_code":
                            existing_tracking.tracking_code,

                        "url":
                            f"/tracking/"
                            f"{existing_tracking.tracking_code}"

                    }

                }

        if content.status != "approved":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Content must be approved "
                    "before publishing"
                )
            )

        existing_tracking = (
            db.query(Tracking)
            .filter(
                Tracking.content_id == content.id
            )
            .first()
        )

        if existing_tracking:

            content.status = "published"

            content.published_at = datetime.now(timezone.utc)

            db.commit()

            db.refresh(content)

            return {

                "message":
                    "Content already published",

                "content": {

                    "id":
                        content.id,

                    "status":
                        content.status

                },

                "tracking": {

                    "id":
                        existing_tracking.id,

                    "tracking_code":
                        existing_tracking.tracking_code,

                    "url":
                        f"/tracking/"
                        f"{existing_tracking.tracking_code}"

                }

            }

        tracking_code = uuid.uuid4().hex[:8]

        tracking = Tracking(
            content_id=content.id,
            tracking_code=tracking_code
        )

        db.add(tracking)

        content.status = "published"

        content.published_at = datetime.now(timezone.utc)

        db.commit()

        db.refresh(content)
        db.refresh(tracking)

        return {

            "message":
                "Content published successfully",

            "content": {

                "id":
                    content.id,

                "campaign_id":
                    content.campaign_id,

                "platform":
                    content.platform,

                "title":
                    content.title,

                "body":
                    content.body,

                "status":
                    content.status

            },

            "tracking": {

                "id":
                    tracking.id,

                "tracking_code":
                    tracking.tracking_code,

                "url":
                    f"/tracking/"
                    f"{tracking.tracking_code}"

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Publish error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# AUTO PIPELINE
# =========================================================

@router.post("/auto-pipeline")
def auto_pipeline():

    db = SessionLocal()

    try:

        (
            best_campaign,
            best_metrics
        ) = get_best_campaign(db)

        offer = (
            db.query(Offer)
            .filter(
                Offer.id == best_campaign.offer_id
            )
            .first()
        )

        if not offer:

            raise HTTPException(
                status_code=404,
                detail="Offer not found"
            )

        action, reason = determine_action(
            best_metrics
        )

        if action == "OPTIMIZE_OFFER":

            return {

                "message":
                    "Pipeline stopped for offer optimization",

                "status":
                    "needs_optimization",

                "action":
                    action,

                "reason":
                    reason,

                "campaign": {

                    "id":
                        best_campaign.id,

                    "name":
                        best_campaign.name

                },

                "performance":
                    best_metrics

            }

        content = create_draft_content(
            db=db,
            campaign=best_campaign,
            offer=offer,
            action=action,
            platform="telegram",
            language=DEFAULT_LANGUAGE,
            title=f"AI Auto Pipeline - {action}"
        )

        if content is None:

            return {

                "message":
                    "Duplicate content detected",

                "status":
                    "skipped",

                "campaign":
                    best_campaign.name,

                "action":
                    action

            }

        return {

            "message":
                "Autonomous pipeline created content",

            "status":
                "pending_approval",

            "action":
                action,

            "reason":
                reason,

            "language":
                DEFAULT_LANGUAGE,

            "campaign": {

                "id":
                    best_campaign.id,

                "name":
                    best_campaign.name

            },

            "performance":
                best_metrics,

            "content": {

                "id":
                    content.id,

                "title":
                    content.title,

                "body":
                    content.body,

                "status":
                    content.status

            },

            "next_step":
                f"POST /agent/approve/{content.id}"

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Auto-pipeline error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# RECORD TRACKING EVENT
# =========================================================

@router.post("/tracking/{tracking_code}")
def record_tracking_event(
    tracking_code: str,
    request: TrackingEventRequest
):

    db = SessionLocal()

    try:

        tracking = (
            db.query(Tracking)
            .filter(
                Tracking.tracking_code == tracking_code
            )
            .first()
        )

        if not tracking:

            raise HTTPException(
                status_code=404,
                detail="Tracking link not found"
            )

        event = (
            request.event
            .lower()
            .strip()
        )

        if event == "click":

            tracking.clicks = (
                tracking.clicks or 0
            ) + 1

        elif event == "registration":

            tracking.registrations = (
                tracking.registrations or 0
            ) + 1

        elif event == "ftd":

            tracking.ftd = (
                tracking.ftd or 0
            ) + 1

        elif event == "revenue":

            tracking.revenue = (
                tracking.revenue or 0
            ) + request.value

        else:

            raise HTTPException(
                status_code=400,
                detail=(
                    "Invalid event. "
                    "Use: click, registration, "
                    "ftd, revenue"
                )
            )

        db.commit()

        db.refresh(tracking)

        return {

            "message":
                "Tracking event recorded",

            "tracking": {

                "id":
                    tracking.id,

                "tracking_code":
                    tracking.tracking_code,

                "clicks":
                    tracking.clicks or 0,

                "registrations":
                    tracking.registrations or 0,

                "ftd":
                    tracking.ftd or 0,

                "revenue":
                    tracking.revenue or 0

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Tracking error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()


# =========================================================
# TRACKING DETAILS
# =========================================================

@router.get("/tracking/{tracking_code}")
def get_tracking_details(
    tracking_code: str
):

    db = SessionLocal()

    try:

        tracking = (
            db.query(Tracking)
            .filter(
                Tracking.tracking_code == tracking_code
            )
            .first()
        )

        if not tracking:

            raise HTTPException(
                status_code=404,
                detail="Tracking link not found"
            )

        clicks = tracking.clicks or 0
        registrations = tracking.registrations or 0
        ftd = tracking.ftd or 0
        revenue = tracking.revenue or 0

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

        return {

            "tracking_code":
                tracking.tracking_code,

            "content_id":
                tracking.content_id,

            "clicks":
                clicks,

            "registrations":
                registrations,

            "ftd":
                ftd,

            "revenue":
                revenue,

            "conversion_rate":
                round(
                    conversion_rate,
                    2
                ),

            "epc":
                round(
                    epc,
                    2
                )

        }

    finally:

        db.close()


# =========================================================
# CAMPAIGN ANALYTICS
# =========================================================

@router.get("/analytics")
def get_agent_analytics():

    db = SessionLocal()

    try:

        campaigns = (
            db.query(Campaign)
            .all()
        )

        results = []

        for campaign in campaigns:

            metrics = get_campaign_metrics(
                db,
                campaign
            )

            action, reason = determine_action(
                metrics
            )

            results.append({

                "campaign_id":
                    campaign.id,

                "campaign_name":
                    campaign.name,

                "clicks":
                    metrics["clicks"],

                "registrations":
                    metrics["registrations"],

                "ftd":
                    metrics["ftd"],

                "revenue":
                    metrics["revenue"],

                "conversion_rate":
                    metrics["conversion_rate"],

                "epc":
                    metrics["epc"],

                "score":
                    metrics["score"],

                "recommended_action":
                    action,

                "reason":
                    reason

            })

        return {

            "campaigns":
                results

        }

    finally:

        db.close()


# =========================================================
# SCHEDULER LOOP
# =========================================================

async def agent_scheduler_loop():

    global scheduler_running

    print("")
    print("========================================")
    print("🤖 AGENT SCHEDULER STARTED")
    print(
        f"⏰ Interval: "
        f"{scheduler_interval} seconds"
    )
    print("🌐 Default Language: Russian")
    print("========================================")

    while scheduler_running:

        try:

            print("")
            print("🤖 Running Agent Cycle...")

            result = await asyncio.to_thread(run_agent_cycle)

            if isinstance(result, dict):

                print(
                    "✅ Agent Cycle Completed"
                )

                print(
                    "📌 Action:",
                    result.get("action")
                )

                print(
                    "🌐 Language:",
                    result.get(
                        "language",
                        DEFAULT_LANGUAGE
                    )
                )

                campaign = result.get(
                    "campaign"
                )

                if campaign:

                    if isinstance(
                        campaign,
                        dict
                    ):

                        print(
                            "📌 Campaign:",
                            campaign.get(
                                "name"
                            )
                        )

                    else:

                        print(
                            "📌 Campaign:",
                            campaign
                        )

            else:

                print(
                    "✅ Agent Cycle Completed"
                )

        except Exception as e:

            print(
                "❌ Agent Scheduler Error:",
                type(e).__name__,
                str(e)
            )

        if not scheduler_running:

            break

        print(
            f"⏳ Next cycle in "
            f"{scheduler_interval} seconds..."
        )

        try:

            await asyncio.sleep(
                scheduler_interval
            )

        except asyncio.CancelledError:

            break

    scheduler_running = False

    print("")
    print("🛑 AGENT SCHEDULER STOPPED")


# =========================================================
# START SCHEDULER
# =========================================================

@router.post("/scheduler/start")
async def start_agent_scheduler():

    global scheduler_task
    global scheduler_running

    if scheduler_running:

        return {

            "message":
                "Agent scheduler is already running",

            "running":
                True,

            "interval_seconds":
                scheduler_interval,

            "interval_minutes":
                scheduler_interval / 60

        }

    scheduler_running = True

    print("")
    print(
        "🚀 Starting Agent Scheduler..."
    )

    scheduler_task = asyncio.create_task(
        agent_scheduler_loop()
    )

    return {

        "message":
            "Agent scheduler started",

        "running":
            True,

        "interval_seconds":
            scheduler_interval,

        "interval_minutes":
            scheduler_interval / 60,

        "language":
            DEFAULT_LANGUAGE

    }


# =========================================================
# STOP SCHEDULER
# =========================================================

@router.post("/scheduler/stop")
async def stop_agent_scheduler():

    global scheduler_task
    global scheduler_running

    if not scheduler_running:

        return {

            "message":
                "Agent scheduler is not running",

            "running":
                False

        }

    print(
        "🛑 Stopping Agent Scheduler..."
    )

    scheduler_running = False

    if scheduler_task:

        scheduler_task.cancel()

        scheduler_task = None

    return {

        "message":
            "Agent scheduler stopped",

        "running":
            False

    }


# =========================================================
# SCHEDULER STATUS
# =========================================================

@router.get("/scheduler/status")
def agent_scheduler_status():

    return {

        "running":
            scheduler_running,

        "interval_seconds":
            scheduler_interval,

        "interval_minutes":
            scheduler_interval / 60,

        "language":
            DEFAULT_LANGUAGE

    }


# =========================================================
# PUBLISH CONTENT TO TELEGRAM
# =========================================================

@router.post("/publish-telegram/{content_id}")
def publish_content_to_telegram(
    content_id: int
):

    db = SessionLocal()

    try:

        content = (
            db.query(Content)
            .filter(
                Content.id == content_id
            )
            .first()
        )

        if not content:

            raise HTTPException(
                status_code=404,
                detail="Content not found"
            )

        if content.status != "approved":

            raise HTTPException(
                status_code=400,
                detail=(
                    "Content must be approved "
                    "before sending to Telegram"
                )
            )

        # ---------------------------------------------
        # SEND TO TELEGRAM
        # ---------------------------------------------

        telegram_result = (
            send_telegram_message(
                content.body
            )
        )

        # ---------------------------------------------
        # CREATE TRACKING
        # ---------------------------------------------

        tracking_code = (
            uuid.uuid4().hex[:8]
        )

        tracking = Tracking(
            content_id=content.id,
            tracking_code=tracking_code
        )

        db.add(tracking)

        # ---------------------------------------------
        # UPDATE CONTENT STATUS
        # ---------------------------------------------

        content.status = "published"

        content.published_at = datetime.now(timezone.utc)

        db.commit()

        db.refresh(content)
        db.refresh(tracking)

        return {

            "message":
                "Content published to Telegram successfully",

            "language":
                DEFAULT_LANGUAGE,

            "content": {

                "id":
                    content.id,

                "campaign_id":
                    content.campaign_id,

                "platform":
                    content.platform,

                "title":
                    content.title,

                "body":
                    content.body,

                "status":
                    content.status

            },

            "telegram": {

                "success":
                    True,

                "message_id":
                    telegram_result
                    .get("result", {})
                    .get("message_id")

            },

            "tracking": {

                "id":
                    tracking.id,

                "tracking_code":
                    tracking.tracking_code,

                "url":
                    f"/tracking/"
                    f"{tracking.tracking_code}"

            }

        }

    except HTTPException:

        raise

    except Exception as e:

        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=(
                f"Telegram publish error: "
                f"{type(e).__name__}: "
                f"{str(e)}"
            )
        )

    finally:

        db.close()
