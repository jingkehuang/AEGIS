# pyright: reportImportCycles = false
# pyright: reportMissingTypeStubs = false
# pyright: reportUnknownMemberType = false
from __future__ import annotations

import sys

import agent.brain
from agent.agent_states import AgentStates
from agent.log_levels import LogLevels
from aegis.common import AgentID, Location
from aegis.common.commands.agent_commands import CONNECT
from aegis.common.commands.command import Command
from aegis.common.network.aegis_socket import AegisSocket
from aegis.common.network.aegis_socket_exception import AegisSocketException
from aegis.common.parsers.aegis_parser import AegisParser
from aegis.common.parsers.aegis_parser_exception import AegisParserException


class BaseAgent:
    """Represents a base agent that connects to and interacts with AEGIS."""

    AGENT_PORT = 6001
    _agent = None
    _log_level: LogLevels = LogLevels.Nothing
    _log_test: bool = False

    def __init__(self) -> None:
        """Initializes a BaseAgent instance."""
        self._round = 0
        self._agent_state = AgentStates.CONNECTING
        self._id = AgentID(-1, -1)
        self._location = Location(-1, -1)
        self._brain: agent.brain.Brain | None = None
        self._energy_level = -1
        self._aegis_socket = None

    @staticmethod
    def get_base_agent() -> BaseAgent:
        """Returns the base agent."""
        if BaseAgent._agent is None:
            BaseAgent._agent = BaseAgent()
        return BaseAgent._agent

    def set_agent_state(self, agent_state: AgentStates) -> None:
        """
        Sets the state of the base agent.

        Args:
            agent_state: The new state for the agent.
        """
        self._agent_state = agent_state
        self.log(LogLevels.Nothing, f"New State: {self._agent_state}")

    def get_agent_state(self) -> AgentStates:
        """Returns the state of the base agent."""
        return self._agent_state

    def get_round_number(self) -> int:
        """Returns the current round number of the simulation."""
        return self._round

    def get_agent_id(self) -> AgentID:
        """Returns the ID of the base agent."""
        return self._id

    def set_agent_id(self, id: AgentID) -> None:
        """
        Sets the id of the base agent.

        Args:
            id: The new ID for the base agent.
        """
        self._id = id
        self.log(LogLevels.Always, f"New ID: {self._id}")

    def get_location(self) -> Location:
        """Returns the location of the base agent."""
        return self._location

    def set_location(self, location: Location) -> None:
        """
        Sets the location of the base agent.

        Args:
            location: The new location for the base agent.
        """
        self._location = location
        self.log(LogLevels.Always, f"New Location: {self._location}")

    def get_energy_level(self) -> int:
        """Returns the energy level of the base agent."""
        return self._energy_level

    def set_energy_level(self, energy_level: int) -> None:
        """
        Sets the energy level of the base agent.

        Args:
            energy_level: The new energy level for the base agent.
        """
        self._energy_level = energy_level
        self.log(LogLevels.Always, f"New Energy: {self._energy_level}")

    def get_brain(self) -> agent.brain.Brain | None:
        """Returns the Brain instance of the base agent."""
        return self._brain

    def set_brain(self, brain: agent.brain.Brain) -> None:
        """
        Sets the Brain instance of the base agent.

        Args:
            brain: The new brain for the base agent.
        """
        self._brain = brain
        self.log(LogLevels.Always, "New Brain")

    def start_test(self, brain: agent.brain.Brain) -> None:
        """
        Starts the agent in test mode.

        Args:
            brain: The brain for the base agent.
        """
        self.start("localhost", "test", brain)

    def start_with_group_name(self, group_name: str, brain: agent.brain.Brain) -> None:
        """
        Starts the agent with a specified group name.

        Args:
            group_name: The group name for the base agent.
            brain: The brain for the base agent.
        """
        self.start("localhost", group_name, brain)

    def start(self, host: str, group_name: str, brain: agent.brain.Brain) -> None:
        """
        Starts the agent and connects it to AEGIS.

        Args:
            host: The hostname or IP address of the AEGIS system.
            group_name: The group name to use when connecting to AEGIS.
            brain: The brain for the base agent.
        """
        if self._agent_state == AgentStates.CONNECTING:
            self._brain = brain
            if self._connect_to_aegis(host, group_name):
                self._run_base_agent_states()
            else:
                self.log(LogLevels.Error, "Failed to connect to AEGIS.")
        else:
            self.log(LogLevels.Error, "Multiple calls made to start method, ( call ignored )")

    def _connect_to_aegis(self, host: str, group_name: str) -> bool:
        """
        Attempts to connect to AEGIS.

        Args:
            host: The hostname or IP address of the AEGIS system.
            group_name: The group name to use when connecting to AEGIS.
        """
        result: bool = False
        for _ in range(5):
            self.log(LogLevels.Always, "Trying to connect to AEGIS...")
            try:
                self._aegis_socket = AegisSocket()
                self._aegis_socket.connect(host, self.AGENT_PORT)
                self._aegis_socket.send_message(str(CONNECT(group_name)))
                message = self._aegis_socket.read_message()
                if message is not None and self._brain is not None:
                    self._brain.handle_aegis_command(AegisParser.parse_aegis_command(message))
                if self.get_agent_state() == AgentStates.CONNECTED:
                    result = True
            except AegisParserException as e:
                print(f"Can't parse/find WorldInfoFile.out -> {e}")
                sys.exit(1)
            except AegisSocketException as e:
                print(f"Can't connect to AEGIS -> {e}")
                sys.exit(1)
            if result:
                break
            else:
                self.log(LogLevels.Always, "Failed to connect")
        if result:
            self.log(LogLevels.Always, "Connected")
        _ = sys.stdout.flush()
        return result

    def _run_base_agent_states(self) -> None:
        """Continuously processes messages from the AEGIS system and handles agent states."""
        end: bool = False
        while not end:
            try:
                aegis_socket = self._aegis_socket
                if aegis_socket is not None:
                    message = aegis_socket.read_message()
                    try:
                        if message is not None:
                            aegis_command = AegisParser.parse_aegis_command(message)
                            if self._brain is not None:
                                self._brain.handle_aegis_command(aegis_command)
                                agent_state = self._agent_state
                                if agent_state == AgentStates.THINK:
                                    self._round += 1
                                    self._brain.think()
                                elif agent_state == AgentStates.SHUTTING_DOWN:
                                    end = True
                    except AegisParserException as e:
                        self.log(
                            LogLevels.Always,
                            f"Got AegisParserException '{e}'",
                        )
            except AegisSocketException as e:
                self.log(LogLevels.Always, f"Got AegisSocketException '{e}', shutting down.")
                end = True
            sys.stdout.flush()

        if self._aegis_socket is not None:
            self._aegis_socket.disconnect()

    def send(self, agent_action: Command) -> None:
        """
        Sends an action command to the AEGIS system.

        Args:
            agent_action: The action command to send.
        """
        if self._aegis_socket is not None:
            try:
                self._aegis_socket.send_message(str(agent_action))
            except AegisSocketException:
                self.log(LogLevels.Always, f"Failed to send {agent_action}")

    @staticmethod
    def get_log_level() -> LogLevels:
        """Returns the current log level."""
        return BaseAgent._log_level

    @staticmethod
    def set_log_level(level: LogLevels) -> None:
        """
        Sets the current log level.

        Args:
            level: The log level to set.
        """
        BaseAgent._log_level = level

    @staticmethod
    def get_log_test_info() -> bool:
        """Returns whether test logging is enabled."""
        return BaseAgent._log_test

    @staticmethod
    def set_log_test_info(log_test: bool) -> None:
        """
        Sets the test logging.

        Args:
            log_test: Enable or disable test logging.
        """
        BaseAgent._log_test = log_test

    @classmethod
    def log(cls, lev: LogLevels, message: str) -> None:
        """
        Logs a message based on the specified logging level.

        Args:
            lev: The logging level for the message.
            message: The message to log.
        """
        agent_id = cls.get_base_agent()._id
        id_str = f"[Agent#({agent_id.id}:{agent_id.gid})]@{cls.get_base_agent()._round}"

        if lev == LogLevels.Test and BaseAgent._log_test:
            print(f"{id_str}: {lev} : {message}")
        elif lev == LogLevels.Always:
            print(f"{id_str}: {message}")
        elif lev == LogLevels.Warning:
            print(f"{id_str}: WARNING {message}")
        elif lev == LogLevels.Error:
            print(f"{id_str}: ERROR {message}")
        elif BaseAgent._log_level != LogLevels.Nothing or lev == LogLevels.All:
            if lev == BaseAgent._log_level or BaseAgent._log_level == LogLevels.All:
                print(f"{id_str}: {lev} : {message}")
