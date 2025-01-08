import os

from dotenv import dotenv_values

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5.5s [%(name) 25.25s:%(lineno)-4.4d] %(message)s"
)

log = logging.getLogger(__name__)

config = dotenv_values(".env")


def read_text_file(file_path) -> str:
    result = ""
    with open(file_path, 'r') as f:
        result = f.read()
    return result


def read_previous_issues() -> list:
    result = []
    path = "previous_issues"
    for file in os.listdir(path):
        # Check whether file is in text format or not
        if file.endswith(".txt"):
            file_path = f"{path}/{file}"
            result.append(read_text_file(file_path))
    return result
