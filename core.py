from dotenv import dotenv_values

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5.5s [%(name) 25.25s:%(lineno)-4.4d] %(message)s"
)

log = logging.getLogger(__name__)

config = dotenv_values(".env")
