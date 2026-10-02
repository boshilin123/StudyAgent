"""Classify provider rejections without exposing their raw request or error body."""

from openai import BadRequestError


def tutoring_request_rejection(error: BadRequestError) -> tuple[str, str]:
    body = error.body
    message = ""
    if isinstance(body, dict):
        detail = body.get("error", body)
        if isinstance(detail, dict):
            message = str(detail.get("message", ""))[:2000].casefold()
    if "thinking mode" in message and "tool_choice" in message:
        return (
            "TUTOR_MODEL_CONFIGURATION_INVALID",
            "当前模型思考模式与强制结构化工具选择不兼容，请调整辅导模型配置",
        )
    if "tool" in message and "support" in message and "tool_choice" not in message:
        return "TUTOR_MODEL_UNSUPPORTED", "模型拒绝辅导所需的工具调用能力"
    return "TUTOR_PROVIDER_REQUEST_REJECTED", "模型服务拒绝辅导请求，请核对兼容参数与模型配置"
