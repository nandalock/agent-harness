"""Portable task context sanitizing and recovery instructions."""
import json

CONTINUE_TASK = (
    "请继续上次未完成的任务，依据已有结果决定下一步。"
    "结果未知的工具先核实实际状态，不要重复已经确认完成的操作。"
)


def saved_task_context(context):
    """Keep JSON task inputs while excluding credential fields from durable logs."""
    if context is None:
        return None
    sensitive = {"api_key", "authorization", "password", "secret", "credentials", "access_token", "refresh_token"}

    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items() if key.lower() not in sensitive}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(json.loads(json.dumps(context, ensure_ascii=False, allow_nan=False)))
