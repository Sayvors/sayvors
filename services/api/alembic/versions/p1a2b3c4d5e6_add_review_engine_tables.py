"""add response_strategies and review_response_logs

Revision ID: p1a2b3c4d5e6
Revises: ee912c4e504d
Create Date: 2026-09-12
"""
import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision = "p1a2b3c4d5e6"
down_revision = "ee912c4e504d"
branch_labels = None
depends_on = None

STRATEGIES = [
    {
        "id": "acknowledge_feedback",
        "name": "Acknowledge Feedback",
        "description": "Recognize what the customer actually said. Reference the specific subject of the review.",
        "category": "engagement",
        "conditions": json.dumps({"sentiments": ["neutral", "positive", "negative", "very_negative", "very_positive"], "min_length": 10}),
        "instructions": json.dumps(["Reference the specific subject of the review, not a generic 'your feedback'.", "Show that the review was read and understood."]),
        "compatible_strategies": json.dumps(["show_appreciation", "apologize_for_issue", "address_specific_issue", "keep_response_minimal"]),
        "priority": 90,
    },
    {
        "id": "apologize_for_issue",
        "name": "Apologize for Issue",
        "description": "Acknowledge the problem and apologize naturally when the customer reports a negative experience.",
        "category": "recovery",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative"], "issue_types": ["product_quality", "product_dissatisfaction", "service_quality", "delivery", "wait_time", "cleanliness", "staff_behavior", "billing", "technical_issue", "general_complaint"]}),
        "instructions": json.dumps(["Acknowledge the specific problem mentioned.", "Apologize naturally without excessive repetition.", "Do not argue with the customer.", "Avoid generic apologies that don't address the issue.", "Do not make unsupported promises about fixes."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "address_specific_issue", "reassure_customer", "invite_private_conversation"]),
        "priority": 80,
    },
    {
        "id": "show_appreciation",
        "name": "Show Appreciation",
        "description": "Thank the reviewer for positive reviews, constructive feedback, or detailed reviews.",
        "category": "engagement",
        "conditions": json.dumps({"sentiments": ["positive", "very_positive"]}),
        "instructions": json.dumps(["Thank the reviewer warmly but proportionally.", "If the review is detailed, acknowledge something specific.", "Do not be overly effusive for a simple 'great'."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "encourage_another_visit", "keep_response_minimal"]),
        "priority": 85,
    },
    {
        "id": "address_specific_issue",
        "name": "Address Specific Issue",
        "description": "Directly address the primary issue mentioned in the review rather than giving a generic response.",
        "category": "engagement",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative", "neutral"], "has_text": True}),
        "instructions": json.dumps(["Identify the primary issue from the review.", "Discuss the specific issue in the response.", "Do not deflect or redirect to unrelated topics."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "apologize_for_issue", "reassure_customer"]),
        "priority": 75,
    },
    {
        "id": "reassure_customer",
        "name": "Reassure Customer",
        "description": "Provide reasonable reassurance without making unsupported claims about fixes or changes.",
        "category": "recovery",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative"], "issue_types": ["product_quality", "service_quality", "staff_behavior", "cleanliness", "technical_issue"]}),
        "instructions": json.dumps(["Express that the feedback is taken seriously.", "Do not claim the issue has been fixed unless there is evidence.", "Keep reassurance proportional to the complaint."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "apologize_for_issue", "invite_private_conversation"]),
        "priority": 60,
    },
    {
        "id": "recommend_related_product",
        "name": "Recommend Related Product",
        "description": "Recommend another product or service when genuinely relevant to the customer's complaint.",
        "category": "growth",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative", "neutral"], "has_product_reference": True}),
        "instructions": json.dumps(["Only recommend products that actually exist in the business catalog.", "Frame the recommendation as a genuine alternative, not a sales pitch.", "Connect the recommendation to what the customer didn't like."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "mention_relevant_offer", "encourage_another_visit"]),
        "priority": 40,
    },
    {
        "id": "mention_relevant_offer",
        "name": "Mention Relevant Offer",
        "description": "Retrieve and mention an existing active promotion when appropriate. Must never invent offers.",
        "category": "growth",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative", "neutral"]}),
        "instructions": json.dumps(["Retrieve relevant active offers from the business before responding.", "Only mention offers that actually exist and are publicly mentionable.", "Integrate the offer naturally into the response.", "If no relevant offer exists, do NOT mention any offer.", "Never invent a discount, coupon, or promotion."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "apologize_for_issue", "encourage_another_visit", "recommend_related_product"]),
        "priority": 35,
    },
    {
        "id": "encourage_another_visit",
        "name": "Encourage Another Visit",
        "description": "Invite the customer to give the business another opportunity when appropriate.",
        "category": "recovery",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative"], "min_rating": 1, "max_rating": 3}),
        "instructions": json.dumps(["Frame the invitation as genuine, not aggressive or salesy.", "Do not pressure the customer.", "Keep it brief and proportional."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "apologize_for_issue", "mention_relevant_offer"]),
        "priority": 45,
    },
    {
        "id": "invite_private_conversation",
        "name": "Invite Private Conversation",
        "description": "Direct the customer to a private channel when the review contains sensitive or complex issues.",
        "category": "recovery",
        "conditions": json.dumps({"sentiments": ["negative", "very_negative"], "intent_keywords": ["refund", "money back", "stolen", "scam", "lawsuit", "lawyer", "card", "charged", "wrong order", "account"]}),
        "instructions": json.dumps(["Acknowledge the concern briefly.", "Invite them to contact the business privately.", "Do not share any personal or account information publicly.", "Do not mention specific phone numbers or emails."]),
        "compatible_strategies": json.dumps(["acknowledge_feedback", "apologize_for_issue"]),
        "priority": 70,
    },
    {
        "id": "keep_response_minimal",
        "name": "Keep Response Minimal",
        "description": "For simple reviews, keep the response short and proportional. No unnecessary promotions or length.",
        "category": "style",
        "conditions": json.dumps({"sentiments": ["positive", "very_positive", "neutral"], "max_review_length": 30}),
        "instructions": json.dumps(["Keep the response to 1-2 sentences.", "Do not add promotions, recommendations, or lengthy explanations.", "Match the effort of the review."]),
        "compatible_strategies": json.dumps(["show_appreciation", "acknowledge_feedback"]),
        "priority": 65,
    },
]


def upgrade() -> None:
    op.create_table(
        "response_strategies",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False, index=True),
        sa.Column("conditions", sa.JSON(), nullable=True),
        sa.Column("instructions", sa.JSON(), nullable=True),
        sa.Column("compatible_strategies", sa.JSON(), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="50"),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("channel_restrictions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "review_response_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("channel_id", sa.String(36), nullable=True, index=True),
        sa.Column("review_id", sa.String(120), nullable=True),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("reviewer_name", sa.String(200), nullable=True),
        sa.Column("channel", sa.String(32), nullable=True),
        sa.Column("analysis", sa.JSON(), nullable=True),
        sa.Column("selected_strategies", sa.JSON(), nullable=True),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("retrieved_offers", sa.JSON(), nullable=True),
        sa.Column("generated_response", sa.Text(), nullable=True),
        sa.Column("validation_result", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), server_default="generated"),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("token_input", sa.Integer(), nullable=True),
        sa.Column("token_output", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Seed 10 core strategies
    op.execute("DELETE FROM response_strategies")
    for s in STRATEGIES:
        # Use text() with explicit cast — bindparams need separate param names
        stmt = text(
            "INSERT INTO response_strategies (id, name, description, category, conditions, instructions, compatible_strategies, priority, enabled) "
            "VALUES (:sid, :sname, :sdesc, :sCat, cast(:conds as json), cast(:instr as json), cast(:compat as json), :spri, true)"
        )
        op.execute(stmt.bindparams(
            sid=s["id"], sname=s["name"], sdesc=s["description"], sCat=s["category"],
            conds=s["conditions"], instr=s["instructions"], compat=s["compatible_strategies"],
            spri=s["priority"],
        ))


def downgrade() -> None:
    op.drop_table("review_response_logs")
    op.drop_table("response_strategies")
