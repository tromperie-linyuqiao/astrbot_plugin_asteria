"""Use the public API; fall back only on older AstrBot's Quart runtime."""

try:
    from astrbot.api.web import error_response, json_response, request

    async def body_json():
        return await request.json(default={})

    def query_args():
        return request.query
except ImportError:
    from quart import jsonify, request

    async def body_json():
        return await request.get_json(silent=True) or {}

    def query_args():
        return request.args

    def json_response(data, *, status_code=200):
        return jsonify(data), status_code

    def error_response(message, *, status_code=400):
        return jsonify({"status": "error", "message": message}), status_code
