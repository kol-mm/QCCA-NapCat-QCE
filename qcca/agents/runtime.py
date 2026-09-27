import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

import config_service as config

DEFAULT_SANDBOX = config.DEFAULT_SANDBOX


@dataclass
class AgentContext:
    uid: str
    workspace: str
    session: str
    agent: str
    sandbox: str
    persistence: str
    new_user: bool = False
    session_id: str | None = None


def _read_config(config_path: str) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as file:
        content = file.read().strip()
    config_data = json.loads(content) if content else {}
    if config.migrate_user_config(config_data):
        config.write_user_config(config_path, config_data)
    return config_data


def _load_config() -> tuple[str, dict[str, Any]]:
    config_path = config.config_dir_file()
    return config_path, _read_config(config_path)


def _new_session() -> str:
    return uuid.uuid4().hex[:12]


def _sandbox(workspace_data: dict[str, Any], requested: str | None = None) -> str:
    return requested or workspace_data.get("sandbox") or DEFAULT_SANDBOX


def _resolve_target(config_data: dict[str, Any], uid: str, workspace: str | None,
                    session: str | None, sandbox: str | None,
                    requested_agent: str | None = None) -> AgentContext:
    default_agent = config.get_default_agent()
    user = config_data.get(uid)
    if not user:
        target_workspace = workspace or os.path.expanduser(
            rf"~\.qq-chat-exporter\qcca\workspace\{int(time.time() * 1000)}"
        )
        os.makedirs(target_workspace, exist_ok=True)
        return AgentContext(
            uid, target_workspace, session or _new_session(), requested_agent or default_agent,
            sandbox or DEFAULT_SANDBOX, "add", True, None
        )

    workspaces = user["workspaces"]
    recent_workspace, recent_agent = config.get_user_recent_session(user)
    recent_agent = recent_agent or config.DEFAULT_AGENT
    # Recover legacy or manually-edited configs whose recent pointer is empty
    # by selecting the first workspace/session that can actually run.
    if not recent_workspace:
        for workspace_name, workspace_data in workspaces.items():
            sessions = workspace_data.get("sessions", {}) if isinstance(workspace_data, dict) else {}
            if isinstance(sessions, dict) and sessions:
                recent_workspace = workspace_name
                target_session = next(iter(sessions))
                recent_agent = config.session_agent(sessions[target_session])
                user["recent_workspace_and_session"] = {workspace_name: target_session}
                break
    if not recent_workspace:
        raise ValueError("最近工作空间或会话配置无效")

    recent_data = workspaces[recent_workspace]
    recent_sandbox = _sandbox(recent_data)
    recent_data["sandbox"] = recent_sandbox

    if not session:
        if workspace == recent_workspace or not workspace:
            target_session = user["recent_workspace_and_session"].get(recent_workspace)
            selected_sandbox = sandbox or recent_sandbox
            recent_data["sandbox"] = selected_sandbox
            session_data = recent_data.get("sessions", {}).get(target_session)
            return AgentContext(
                uid, recent_workspace, target_session, requested_agent or recent_agent,
                selected_sandbox, "recent", False,
                config.session_id(session_data),
            )

        if workspace in workspaces:
            workspace_data = workspaces[workspace]
            selected_sandbox = _sandbox(workspace_data, sandbox)
            workspace_data["sandbox"] = selected_sandbox
            return AgentContext(uid, workspace, _new_session(), requested_agent or default_agent, selected_sandbox, "add")

        return AgentContext(uid, workspace, _new_session(), requested_agent or default_agent, sandbox or DEFAULT_SANDBOX, "add")

    if workspace == recent_workspace or not workspace:
        if session in recent_data["sessions"]:
            selected_sandbox = sandbox or recent_sandbox
            recent_data["sandbox"] = selected_sandbox
            return AgentContext(
                uid, recent_workspace, session,
                requested_agent or config.session_agent(recent_data["sessions"][session]),
                selected_sandbox, "update", False,
                config.session_id(recent_data["sessions"][session]),
            )
        selected_sandbox = sandbox or recent_sandbox
        recent_data["sandbox"] = selected_sandbox
        return AgentContext(uid, recent_workspace, session, requested_agent or default_agent, selected_sandbox, "add")

    if workspace in workspaces:
        workspace_data = workspaces[workspace]
        selected_sandbox = _sandbox(workspace_data, sandbox)
        workspace_data["sandbox"] = selected_sandbox
        if session in workspace_data["sessions"]:
            agent = config.session_agent(workspace_data["sessions"][session])
            return AgentContext(
                uid, workspace, session, requested_agent or agent, selected_sandbox, "update", False,
                config.session_id(workspace_data["sessions"][session]),
            )
        return AgentContext(uid, workspace, session, requested_agent or default_agent, selected_sandbox, "add")

    return AgentContext(
        uid, workspace, session or _new_session(), requested_agent or default_agent,
        sandbox or DEFAULT_SANDBOX, "add"
    )


def _persist(config_data: dict[str, Any], config_path: str, target: AgentContext,
             agent: str) -> bool:
    if target.persistence == "recent":
        session_data = config_data[target.uid]["workspaces"][target.workspace]["sessions"][target.session]
        session_data["id"] = config.session_id(session_data) or str(uuid.uuid4())
        session_data["agent"] = agent
        config.write_user_config(config_path, config_data)
        return True

    if target.persistence == "update":
        session_data = config_data[target.uid]["workspaces"][target.workspace]["sessions"][target.session]
        session_data["agent"] = agent
        return config.set_user_recent_session(
            config_data, config_path, target.uid, target.workspace, target.session
        )

    return config.add_user_data(
        config_data,
        config_path,
        target.uid,
        target.workspace,
        target.session,
        agent,
        target.sandbox,
    )


def agent_qcca(agent_control: Callable) -> Callable:
    """Add QCCA configuration and session handling to an Agent function."""

    @wraps(agent_control)
    def agent_run(uid: str, context: str, workspace: str | None = None,
                  session: str | None = None, sandbox: str | None = None,
                  agent: str | None = None):
        try:
            config_path, config_data = _load_config()
            target = _resolve_target(config_data, uid, workspace, session, sandbox, agent)
            shared_memory = config.build_memory_context(target.session_id)
            prompt = context
            if shared_memory:
                prompt = f"{shared_memory}\n\n当前请求：\n{context}"
            answer, _native_session = agent_control(
                prompt, target.workspace, None, target.sandbox
            )
            # An explicit registry selection is authoritative.  Fall back to
            # the callable name only for direct legacy calls without `agent`.
            agent_name = agent if isinstance(agent, str) and agent.strip() else getattr(agent_control, "agent_type", None)
            if not isinstance(agent_name, str) or not agent_name.strip():
                agent_name = getattr(agent_control, "__name__", "agent").removesuffix("_control")
            agent_name = agent_name.strip().lower()
            # The Agent may have run for minutes while other senders' calls
            # saved their own changes.  Re-read the file under the lock and
            # carry over only this sender's entry so no update is lost.
            with config.user_config_file_lock():
                latest = _read_config(config_path)
                if target.uid in config_data:
                    latest[target.uid] = config_data[target.uid]
                persisted = _persist(latest, config_path, target, agent_name)
            if target.new_user and not persisted:
                return "创建新用户失败\n" + answer.strip()
            prefix = "创建新用户成功," if target.new_user else ""
            return f"{prefix}工作空间:{target.workspace},会话:{target.session}\n{answer.strip()}"
        except (FileNotFoundError, PermissionError, OSError, KeyError,
                TypeError, json.JSONDecodeError, RuntimeError, TimeoutError,
                ValueError) as exc:
            print(exc)
            if isinstance(exc, (FileNotFoundError, PermissionError, OSError, json.JSONDecodeError)):
                return f"抱歉出现了一些错误:{exc}"
            return f"出现错误{exc}"

    return agent_run
