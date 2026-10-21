from typing import Dict, Type
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.handlers.compx import CompXHandler
from areyoulowbattery.handlers.actions import ActionsHandler

HANDLER_REGISTRY: Dict[str, Type[BaseProtocolHandler]] = {
    "compx_v1": CompXHandler,
    "actions_v1": ActionsHandler,
}

def get_handler(protocol: str) -> BaseProtocolHandler:
    handler_class = HANDLER_REGISTRY.get(protocol)
    if not handler_class:
        raise ValueError(f"Unknown protocol: {protocol}")
    return handler_class()
