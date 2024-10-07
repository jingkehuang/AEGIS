import socket

from aegis.agent_control.agent_control import AgentControl
from aegis.agent_control.agent_group import AgentGroup
from aegis.agent_control.network.agent_crashed_exception import AgentCrashedException
from aegis.agent_control.network.agent_socket import AgentSocket
from aegis.agent_control.network.agent_socket_exception import AgentSocketException
from aegis.common.agent_id import AgentID
from aegis.common.commands.agent_command import AgentCommand
from aegis.common.commands.agent_commands import AGENT_UNKNOWN, CONNECT
from aegis.common.commands.aegis_command import AegisCommand
from aegis.common.commands.aegis_commands import (
    CMD_RESULT_END,
    CMD_RESULT_START,
    FWD_MESSAGE,
    MESSAGES_END,
    MESSAGES_START,
    SAVE_SURV_RESULT,
)
from aegis.common.constants import Constants
from aegis.common.network.aegis_socket_exception import AegisSocketException
from aegis.common.parsers.aegis_parser import AegisParser
from aegis.common.parsers.aegis_parser_exception import AegisParserException


class AgentHandler:
    def __init__(self) -> None:
        self.GID_counter: int = 1
        self.agent_list: list[AgentControl] = []
        self.current_agent: int = 0
        self.agent_group_list: list[AgentGroup] = []
        self.current_mailbox: int = 1
        self.forward_message_list: list[FWD_MESSAGE] = []
        self.send_messages_to_all_groups: bool = False
        self.server_socket: socket.socket | None = None

    def set_agent_handler_port(self, port: int) -> None:
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("", port))
            self.server_socket.listen(5)
        except Exception:
            print(f"Aegis  : Can't create server socket at port: {port}")
            raise AegisSocketException()

    def shutdown(self) -> None:
        for agent in self.agent_list:
            if agent.agent_socket:
                agent.agent_socket.disconnect()
        self._reset_all()

    def _reset_all(self):
        self.GID_counter = 1
        self.agent_list.clear()
        self.current_mailbox = 1
        self.agent_group_list.clear()
        self.forward_message_list.clear()
        self.send_messages_to_all_groups = False
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None

    def connect_to_agent(self, timeout: int) -> AgentID | None:
        if self.server_socket is None:
            return None
        server_socket = self.server_socket
        try:
            server_socket.settimeout(timeout)
            agent_socket = AgentSocket()
            agent_socket.connect(server_socket)
            message = agent_socket.read_message(timeout=timeout)

            if message is None:
                agent_socket.disconnect()
                return None

            command = AegisParser.parse_agent_command(message)
            if not isinstance(command, CONNECT):
                agent_socket.disconnect()
                return None

            agent_connect = command
            group = self.get_group(agent_connect.group_name)
            if group is None:
                gid = self.add_group(agent_connect.group_name).GID
            else:
                gid = group.GID

            group = self.get_group(agent_connect.group_name)
            if group is None:
                return None

            id = group.id_counter
            agent_control = AgentControl(AgentID(id, group.GID))
            group.id_counter += 1

            agent_control.agent_socket = agent_socket
            group.agent_list.append(agent_control)
            self.agent_list.append(agent_control)
            return AgentID(id, gid)
        except AgentSocketException | AegisParserException | AgentCrashedException:
            return None

    def add_group(self, group_name: str) -> AgentGroup:
        group = AgentGroup(self.GID_counter, group_name)
        self.GID_counter += 1
        self.agent_group_list.append(group)
        return group

    def get_group(self, name: str) -> AgentGroup | None:
        for group in self.agent_group_list:
            if group.name == name:
                return group
        return None

    def get_agent_group(self, gid: int) -> AgentGroup | None:
        for group in self.agent_group_list:
            if group.GID == gid:
                return group
        return None

    def get_agent(self, agent_id: AgentID) -> AgentControl | None:
        for agent in self.agent_list:
            if agent.agent_id == agent_id:
                return agent
        return None

    def get_current_agent(self) -> AgentControl:
        return self.agent_list[self.current_agent]

    def reset_current_agent(self) -> None:
        self.current_agent = 0

    def move_to_next_agent(self) -> None:
        self.current_agent = (self.current_agent + 1) % len(self.agent_list)

    def remove_agent(self, agent_id: AgentID) -> None:
        agent = self.get_agent(agent_id)
        if agent is None:
            return

        self.agent_list.remove(agent)
        group: AgentGroup | None = self.get_agent_group(agent_id.gid)
        if group is None:
            return

        group.agent_list.remove(agent)

    def get_number_of_agents(self) -> int:
        return len(self.agent_list)

    def send_message_to_current(self, command: AegisCommand) -> None:
        agent = self.get_current_agent()
        self.send_message_to(agent.agent_id, command)

    def send_message_to(self, agent_id: AgentID, command: AegisCommand) -> None:
        agent: AgentControl | None = self.get_agent(agent_id)
        if agent is None:
            return
        try:
            if agent.agent_socket is not None:
                agent.agent_socket.send_message(str(command))
        except AgentCrashedException as e:
            print(
                f'Aegis  : Exception "{e}" sending message " {command} " to agent {agent_id} !'
            )
            raise e
        except Exception as e:
            print(
                f'Aegis  : Exception "{e}" sending message " {command} " to agent {agent_id} !'
            )

    def send_message_to_all(self, command: AegisCommand) -> None:
        for agent in self.agent_list:
            self.send_message_to(agent.agent_id, command)

    def get_agent_command_of_current(self, timeout: int) -> AgentCommand | None:
        try:
            agent = self.get_current_agent()
            if agent.agent_socket is None:
                return None

            s = agent.agent_socket.read_message(timeout=timeout)
            if not s:
                return None
            command = AegisParser.parse_agent_command(s)
        except AgentSocketException:
            print(
                f"Aegis  : Exception reading message from agent {self.get_current_agent().agent_id} !"
            )
            command = AGENT_UNKNOWN()
        except AegisParserException:
            print(
                f"Aegis  : Exception parsing message from agent {self.get_current_agent().agent_id} !"
            )
            command = AGENT_UNKNOWN()
        except AgentCrashedException as e:
            print(
                f"Aegis  : Agent reset the socket connection (possible crash of agent?) {self.get_current_agent().agent_id} !"
            )
            raise e
        command.set_agent_id(self.get_current_agent().agent_id)
        return command

    def set_result_of_command(self, agent_id: AgentID, command: AegisCommand) -> None:
        agent = self.get_agent(agent_id)
        if agent is None:
            return
        agent.result_of_command = command

    def send_result_of_command_to_current(self) -> None:
        agent = self.get_current_agent()
        if agent.result_of_command is not None:
            self.send_message_to(agent.agent_id, CMD_RESULT_START(1))
            self.send_message_to(agent.agent_id, agent.result_of_command)
            self.send_message_to(agent.agent_id, CMD_RESULT_END())
            agent.result_of_command = None
        else:
            self.send_message_to(agent.agent_id, CMD_RESULT_START(0))
            self.send_message_to(agent.agent_id, CMD_RESULT_END())

    def forward_message_to_all(self, fwd_message: FWD_MESSAGE) -> None:
        fwd_message.set_number_left_to_read(len(self.agent_list))

        for agent in self.agent_list:
            self._add_message_to_mailbox(agent, fwd_message)
        self.forward_message_list.append(fwd_message)

    def forward_message_to_group(self, gid: int, fwd_message: FWD_MESSAGE) -> None:
        group = self.get_agent_group(gid)
        if group is None:
            return

        fwd_message.set_number_left_to_read(len(group.agent_list))

        for agent in group.agent_list:
            self._add_message_to_mailbox(agent, fwd_message)
        self.forward_message_list.append(fwd_message)

    def forward_message(self, fwd_message: FWD_MESSAGE) -> None:
        fwd_message.set_number_left_to_read(0)
        for agent_id in fwd_message.agent_id_list:
            if agent_id.id == 0:
                if self.send_messages_to_all_groups:
                    self.forward_message_to_group(agent_id.gid, fwd_message)
                else:
                    if agent_id.gid == fwd_message.from_agent_id.gid:
                        self.forward_message_to_group(agent_id.gid, fwd_message)
            else:
                if self.send_messages_to_all_groups:
                    should_message_be_forwarded = True
                else:
                    should_message_be_forwarded = (
                        agent_id.gid == fwd_message.from_agent_id.gid
                    )
                if should_message_be_forwarded:
                    agent = self.get_agent(agent_id)
                    if agent is None:
                        continue

                    fwd_message.increase_number_left_to_read(1)
                    self._add_message_to_mailbox(agent, fwd_message)
        self.forward_message_list.append(fwd_message)

    def send_forward_messages_to_current(self) -> None:
        agent = self.get_current_agent()
        mailbox = agent.mailbox1 if self.current_mailbox == 1 else agent.mailbox2

        self.send_message_to(agent.agent_id, MESSAGES_START(len(mailbox)))
        for fwd_message in mailbox:
            fwd_message.decrease_number_left_to_read()
            self.send_message_to(agent.agent_id, fwd_message)

        self.send_message_to(agent.agent_id, MESSAGES_END())
        mailbox.clear()

    def _add_message_to_mailbox(
        self, agent: AgentControl, fwd_message: FWD_MESSAGE
    ) -> None:
        if self.current_mailbox == 1:
            agent.mailbox2.append(fwd_message)
        elif self.current_mailbox == 2:
            agent.mailbox1.append(fwd_message)

    def remove_all_forward_messages(self) -> None:
        self.forward_message_list.clear()

    def empty_forward_messages(self) -> None:
        self.forward_message_list = [
            msg
            for msg in self.forward_message_list
            if msg.get_number_left_to_read() > 0
        ]

        self.current_mailbox = 2 if self.current_mailbox == 1 else 1

    def increase_agent_group_saved(
        self, gid: int, number_saved: int, save_state: int
    ) -> None:
        state_message = "alive" if save_state == Constants.SAVE_STATE_ALIVE else "dead"
        print(f"Aegis  : Group {gid} saved {number_saved} survivors {state_message}.")
        agent_group = self.get_agent_group(gid)
        if agent_group is None:
            return

        agent_group.number_saved += number_saved
        if save_state == Constants.SAVE_STATE_ALIVE:
            agent_group.number_saved_alive += number_saved
        elif save_state == Constants.SAVE_STATE_DEAD:
            agent_group.number_saved_dead += number_saved

    def print_group_survivor_saves(self) -> None:
        print("=================================================")
        print("Results for each Group")
        print("(Number Saved, Number Alive, Number Dead)")
        print("=================================================")
        for group in self.agent_group_list:
            print(
                f"( GID {group.GID} ) NAME {group.name} = ( {group.number_saved} , {group.number_saved_alive} , {group.number_saved_dead} );"
            )
