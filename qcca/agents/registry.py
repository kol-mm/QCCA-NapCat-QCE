from typing import Callable


class AgentRegistry:
    """Registry for selecting an Agent implementation by name."""

    def __init__(self) -> None:
        self.agent_dict: dict[str, Callable] = {}

    def register(self, func: Callable, agent_name: str) -> None:
        self.agent_dict[agent_name] = func

    def unregister(self, agent_name: str) -> bool:
        if agent_name not in self.agent_dict:
            return False
        del self.agent_dict[agent_name]
        return True

    def get_agent(self, agent_name: str) -> Callable | None:
        return self.agent_dict.get(agent_name)
