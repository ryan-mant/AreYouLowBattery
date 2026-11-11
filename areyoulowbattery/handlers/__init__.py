from typing import Dict, Type
from areyoulowbattery.handlers.base import BaseProtocolHandler
from areyoulowbattery.handlers.compx import CompXHandler
from areyoulowbattery.handlers.actions import ActionsHandler
from areyoulowbattery.handlers.nordic import NordicHandler
from areyoulowbattery.handlers.hidpp import LogitechHidppHandler
from areyoulowbattery.handlers.razer import RazerHandler
from areyoulowbattery.handlers.generic_hid import GenericHidHandler
from areyoulowbattery.handlers.steelseries import SteelSeriesHandler
from areyoulowbattery.handlers.corsair import CorsairHandler
from areyoulowbattery.handlers.hyperx import HyperXHandler

HANDLER_REGISTRY: Dict[str, Type[BaseProtocolHandler]] = {
    "compx_v1": CompXHandler,
    "actions_v1": ActionsHandler,
    "nordic_v1": NordicHandler,
    "hidpp_v2": LogitechHidppHandler,
    "razer_v1": RazerHandler,
    "steelseries_v1": SteelSeriesHandler,
    "corsair_v1": CorsairHandler,
    "hyperx_v1": HyperXHandler,
    "generic_hid": GenericHidHandler,
}


def get_handler(protocol: str) -> BaseProtocolHandler:
    handler_class = HANDLER_REGISTRY.get(protocol)
    if not handler_class:
        raise ValueError(f"Unknown protocol: {protocol}")
    return handler_class()
