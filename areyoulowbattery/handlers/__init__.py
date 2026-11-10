from typing import Dict, Type
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.handlers.compx import CompXHandler
from areyoulowbattery.handlers.actions import ActionsHandler
from areyoulowbattery.handlers.nordic import NordicHandler
from areyoulowbattery.handlers.hidpp import LogitechHidppHandler

HANDLER_REGISTRY: Dict[str, Type[BaseProtocolHandler]] = {
    "compx_v1": CompXHandler,
    "actions_v1": ActionsHandler,
    "nordic_v1": NordicHandler,
    "hidpp_v2": LogitechHidppHandler,
}

def get_handler(protocol: str) -> BaseProtocolHandler:
    handler_class = HANDLER_REGISTRY.get(protocol)
    if not handler_class:
        raise ValueError(f"Unknown protocol: {protocol}")
    return handler_class()
