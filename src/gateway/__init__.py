"""Gateway layer for inbound chat channels and routing."""

from src.gateway.callback_service import CardCallbackService
from src.gateway.card_actions import TaskCardAction, parse_task_card_action
from src.gateway.card_renderer import render_task_draft_card
from src.gateway.dispatcher import Dispatcher, RouteDecision, RouteKind
from src.gateway.inbound_service import InboundGatewayService, InboundResult
from src.gateway.outbound import InMemoryOutboundNotifier, OutboundMessage, OutboundNotifier
from src.gateway.wecom_adapter import AdaptedInboundMessage, adapt_wecom_payload

__all__ = [
    "CardCallbackService",
    "TaskCardAction",
    "parse_task_card_action",
    "render_task_draft_card",
    "Dispatcher",
    "RouteDecision",
    "RouteKind",
    "InboundGatewayService",
    "InboundResult",
    "OutboundMessage",
    "OutboundNotifier",
    "InMemoryOutboundNotifier",
    "AdaptedInboundMessage",
    "adapt_wecom_payload",
]
