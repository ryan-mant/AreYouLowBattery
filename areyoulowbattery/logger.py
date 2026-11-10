import os
import sys
import logging

logger = logging.getLogger("areyoulowbattery")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(handler)
    env_debug = os.environ.get("AREYOULOWBATTERY_DEBUG", "").lower() in ("1", "true", "yes")
    logger.setLevel(logging.DEBUG if env_debug else logging.WARNING)


def setup_logging(debug: bool = False):
    if debug:
        logger.setLevel(logging.DEBUG)
