"""sse: moved out of main.py (see tools/split_module.py)."""
import json


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


# Without these headers some browsers/proxies may buffer the response
# instead of delivering it a piece at a time, defeating the streaming.
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
