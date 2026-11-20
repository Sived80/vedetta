"""The body of a modifying request: a JSON dictionary or a 400, in one place (a body that was a list, a string or not JSON used to give a 500 with a traceback in the log)."""
from fastapi import HTTPException, Request

from .. import i18n


async def json_dict(request: Request, message_key: str = "error.invalid_body") -> dict:
    """The JSON object of the request; 400 with a translated message when the body is not valid JSON or not an object."""
    i18n.use_request(request)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, i18n.t(message_key))
    return body


def list_field(body: dict, key: str, item_type: type) -> list:
    """body[key], an empty list when absent, when it is a list of item_type; otherwise the same translated 400 (a number or a list of lists used
    to give a 500 with a traceback, deep inside the route)."""
    value = body.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, item_type) for v in value):
        raise HTTPException(400, i18n.t("error.invalid_body"))
    return value
