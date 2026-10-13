"""The add-on option `log_level` (debug, info, warning, error) reaches the service as VEDETTA_LOG_LEVEL. It used to go only to uvicorn: the service's own log stayed at INFO whatever the user chose.
Now the level of the service's log follows the option; an unknown or missing value keeps INFO."""
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog  # noqa: E402

for text, expected in (("debug", logging.DEBUG), ("info", logging.INFO), ("warning", logging.WARNING), ("error", logging.ERROR),
                       ("DEBUG", logging.DEBUG), (" Warning ", logging.WARNING), ("", logging.INFO), (None, logging.INFO), ("verbose", logging.INFO), ("10", logging.INFO)):
    assert applog.level_from(text) == expected, (text, applog.level_from(text))

os.environ["VEDETTA_LOG_LEVEL"] = "warning"
applog.apply_level()
assert applog.logger.level == logging.WARNING
del os.environ["VEDETTA_LOG_LEVEL"]
applog.apply_level()
assert applog.logger.level == logging.INFO
print("TUTTO OK")
