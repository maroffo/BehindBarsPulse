from dotenv import dotenv_values

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(filename)s:%(funcName)s:%(lineno)d] %(message)s"
)

log = logging.getLogger(__name__)

config = dotenv_values(".env")
