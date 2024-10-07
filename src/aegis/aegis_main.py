import base64
import gzip
import json
import sys
import time
from datetime import datetime

from aegis.agent_control.agent_handler import AgentHandler
from aegis.agent_control.network.agent_crashed_exception import AgentCrashedException
from aegis.assist.config_settings import ConfigSettings
from aegis.assist.parameters import Parameters
from aegis.assist.replay_file_writer import ReplayFileWriter
from aegis.assist.state import State
from aegis.command_line_reader.command_line_reader import CommandLineReader
from aegis.command_line_reader.option import Option
from aegis.common import (
    AgentID,
    AgentIDList,
    Constants,
    Direction,
    LifeSignals,
    Utility,
)
from aegis.common.commands.agent_command import AgentCommand
from aegis.common.commands.agent_commands import (
    END_TURN,
    MOVE,
    OBSERVE,
    SAVE_SURV,
    SEND_MESSAGE,
    SLEEP,
    TEAM_DIG,
    AGENT_UNKNOWN,
)
from aegis.common.commands.aegis_commands import (
    CONNECT_OK,
    DEATH_CARD,
    DISCONNECT,
    FWD_MESSAGE,
    MOVE_RESULT,
    OBSERVE_RESULT,
    ROUND_END,
    ROUND_START,
    SAVE_SURV_RESULT,
    SLEEP_RESULT,
    TEAM_DIG_RESULT,
)
from aegis.common.network.aegis_socket_exception import AegisSocketException
from aegis.common.world.grid import Grid
from aegis.common.world.info.grid_info import GridInfo
from aegis.common.world.objects import Rubble, Survivor, SurvivorGroup, WorldObject
from aegis.parsers.config_parser import ConfigParser
from aegis.parsers.world_file_parser import WorldFileParser
from aegis.server_websocket import WebSocketServer
from aegis.world.aegis_world import AegisWorld


class Aegis:
    def __init__(self) -> None:
        self._parameters = Parameters()
        self._state = State.NONE
        self._started_idling = -1
        self._end = False
        self._agent_handler = AgentHandler()
        self._agent_commands: list[AgentCommand] = []
        self._command_records: list[str] = []
        self._TEAM_DIG_list: list[TEAM_DIG] = []
        self._SAVE_SURV_list: list[SAVE_SURV] = []
        self._MOVE_list: list[MOVE] = []
        self._SLEEP_list: list[SLEEP] = []
        self._OBSERVE_list: list[OBSERVE] = []
        self._TEAM_DIG_RESULT_list = AgentIDList()
        self._SAVE_SURV_RESULT_list = AgentIDList()
        self._MOVE_RESULT_list = AgentIDList()
        self._SLEEP_RESULT_list = AgentIDList()
        self._OBSERVE_RESULT_list: list[OBSERVE] = []
        self._crashed_agents = AgentIDList()
        self._aegis_world = AegisWorld()
        self._ws_server = WebSocketServer()

    def read_command_line(self, args: list[str]) -> bool:
        try:
            command_line_reader = CommandLineReader()

            options = [
                ("NoKViewer", CommandLineReader.INT, False),
                ("ProcFile", CommandLineReader.STRING, False),
                ("WorldFile", CommandLineReader.STRING, True),
                ("NumRound", CommandLineReader.INT, True),
                ("WaitForClient", CommandLineReader.BOOL, False),
            ]

            for name, value_type, is_required in options:
                option = Option()
                option.name = name
                option.value_type = value_type
                option.is_required = is_required
                command_line_reader.add_option(option)

            command_line_reader.set_error_output(self._init_error_output())
            if not command_line_reader.read_cmd_line_args(args):
                return False

            for name, value_type, _ in options:
                option = command_line_reader.get_option(name)
                if option and option.is_set and option.value:
                    if name == "NoKViewer":
                        self._parameters.number_of_agents = 1
                    elif name == "ProcFile":
                        self._parameters.replay_filename = str(option.value)
                    elif name == "WorldFile":
                        self._parameters.world_filename = str(option.value)
                    elif name == "NumRound":
                        self._parameters.number_of_rounds = int(option.value)
                    elif name == "WaitForClient":
                        self._ws_server.set_wait_for_client(bool(option.value))

            return True
        except Exception:
            return False

    def _init_error_output(self) -> str:
        s = ""
        s += "Aegis  : Incorrect arguments.\n"
        s += "Option List:\n"
        s += "\t-NoKViewer <#>       = Starts up AEGIS with no viewer and waits\n"
        s += "\t                          for the indicated number of agents to connect.\n"
        s += "\t                          Not required, default yes.\n"
        s += "\t-ProcFile <file>     = Set the name of the file to save the protocol\n"
        s += "\t                          file to.\n"
        s += "\t                          Not required, default replay.txt.\n"
        s += "\t-WorldFile <filename>  = Indicates the file AEGIS should use to\n"
        s += "\t                          build the world from upon startup.\n"
        s += "\t-NumRound <#>        = Set number of rounds in simulation."
        s += "\t-WaitForClient <bool> = Set to true to wait for client to connect."
        return s

    def start_up(self) -> bool:
        try:
            self._agent_handler.set_agent_handler_port(Constants.AGENT_PORT)
            if not ReplayFileWriter.open_replay_file(
                self._parameters.replay_filename, self._parameters.world_filename
            ):
                print(
                    f"Aegis  : Could not open protocol file: {self._parameters.replay_filename}",
                    file=sys.stderr,
                )
                return False
            print(f"Aegis  : Protocol file is: {self._parameters.replay_filename}")
        except AegisSocketException:
            print("Aegis  : Could not open agent port.", file=sys.stderr)
            return False
        except Exception:
            print(
                f"Aegis  : Could not open protocol file: {self._parameters.replay_filename}",
                file=sys.stderr,
            )
            return False

        try:
            config_settings = ConfigParser.parse_config_file(
                "sys_files/aegis_config.json"
            )
            if config_settings is None:
                print(
                    'aegis  : Unable to parse config file from "sys_files/aegis_config.json"',
                    file=sys.stderr,
                )
                return False

            self._parameters.config_settings = config_settings
            self._agent_handler.send_messages_to_all_groups = (
                self._parameters.config_settings.send_messages_to_all_groups
            )
        except Exception:
            print(
                'Aegis  : Unable to parse config file from "sys_files/aegis_config.json"',
                file=sys.stderr,
            )
            return False

        try:
            _aegis_world_file = WorldFileParser.parse_world_file(
                self._parameters.world_filename
            )
            if _aegis_world_file is None:
                print(
                    f'Aegis  : Unable to parse world file from "{self._parameters.world_filename}"',
                    file=sys.stderr,
                )
                return False
        except Exception:
            print(
                f'Aegis  : Unable to parse world file from "{self._parameters.world_filename}"',
                file=sys.stderr,
            )
            return False

        self._state = State.IDLE
        self._started_idling = 0
        return True

    def build_world(self) -> bool:
        return self._aegis_world.build_world_from_file(
            self._parameters.world_filename, self._ws_server
        )

    def shutdown(self) -> None:
        try:
            self._agent_handler.print_group_survivor_saves()
            self._agent_handler.send_message_to_all(DISCONNECT())
            self._agent_handler.shutdown()

            ReplayFileWriter.write_string(
                f"MSG;System Run ended on: {datetime.now()}\n"
            )
            ReplayFileWriter.write_string("MSG;Kernel Shutting Down;\n")
            ReplayFileWriter.close_replay_file()
        except AgentCrashedException:
            pass

    def connect_all_agents(self) -> None:
        connected: bool = False
        count: int = 0
        for _ in range(self._parameters.number_of_agents):
            for _ in range(5):
                connected = self._connect_agent(
                    self._parameters.milliseconds_to_wait_for_agent_connect
                )
                if connected:
                    count += 1
                    break
        print(
            f"Aegis  : {count} out of {self._parameters.number_of_agents} agents connected to AEGIS."
        )
        self._state = State.RUN_SIMULATION

    def _connect_agent(self, timeout: int) -> bool:
        agent_id = self._agent_handler.connect_to_agent(timeout)
        if agent_id is None:
            return False

        try:
            self._aegis_world.add_agent_by_id(agent_id)
            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                return False

            self._agent_handler.send_message_to(
                agent_id,
                CONNECT_OK(
                    agent_id,
                    agent.get_energy_level(),
                    agent.location,
                    self._aegis_world.get_agent_world_filename(),
                ),
            )
            ReplayFileWriter.write_string(
                f"ADD_AGT; Info(ID {agent.agent_id.id}, GID {agent.agent_id.gid}, Eng {agent.get_energy_level()}):Loc(X {agent.location.x}, Y {agent.location.y});\n"
            )
            return True
        except AgentCrashedException:
            return False

    def _end_simulation(self) -> None:
        print("Aegis  : Simulation Over.")

        game_over_data = {"event_type": "SimulationComplete"}
        event = json.dumps(game_over_data).encode()
        self._compress_and_send(event)

        self._state = State.SHUT_DOWN
        self._end = True
        self._ws_server.finish()

    def run_state(self) -> None:
        match self._state:
            case State.IDLE:
                if self._started_idling == 0:
                    self._started_idling = time.time_ns() // 1_000_000
                else:
                    current_time = time.time_ns() // 1_000_000
                    diff = (current_time - self._started_idling) // 1000
                    if diff >= 300:
                        print(
                            "Aegis  : AEGIS has been idle for too long and will now shut down.",
                            file=sys.stderr,
                        )
                        self._end_simulation()
            case State.CONNECT_AGENTS:
                _ = self._connect_agent(1)
            case State.RUN_SIMULATION:
                self._run_simulation()
            case State.SHUT_DOWN:
                self._end_simulation()
            case _:
                pass

    def _run_simulation(self) -> None:
        self._ws_server.start()
        print("Aegis  : Running simulation.")

        if self._agent_handler.get_number_of_agents() == 0:
            print("Aegis  : No Agents Connected to Aegis!")
            ReplayFileWriter.write_string("MSG;No Agents Connected to the Kernel;\n")
            self._end_simulation()
            return

        ReplayFileWriter.write_string(
            f"#\nWorld File Used : {self._parameters.world_filename};\n"
        )
        ReplayFileWriter.write_string(
            f"Simulation Start: Number of Rounds {self._parameters.number_of_rounds};\n"
        )
        print(f"Running for {self._parameters.number_of_rounds} rounds\n")
        print("================================================")
        _ = sys.stdout.flush()

        after_json_world = self.get_aegis_world().convert_to_json()

        round_data = {
            "event_type": "Round",
            "round": 0,
            "after_world": after_json_world,
        }
        event = json.dumps(round_data).encode()
        self._compress_and_send(event)

        for round in range(1, self._parameters.number_of_rounds + 1):
            if self._end:
                break

            self._aegis_world.round = round

            if self._state == State.SHUT_DOWN:
                print("Aegis  : AEGIS has shutdown.")
                self._end_simulation()
                return

            if self._agent_handler.get_number_of_agents() <= 0:
                print("Aegis  : All Agents are Dead !!!")
                ReplayFileWriter.write_string("MSG;All Agents are Dead !!;\n")
                self._end_simulation()
                return

            survivors_saved = self._aegis_world.get_total_saved_survivors()
            total_survivors = self._aegis_world.get_num_survivors()

            if survivors_saved == total_survivors:
                print("Aegis  : All Survivors Saved")
                ReplayFileWriter.write_string("MSG;All Survivors Saved !!;\n")
                self._end_simulation()
                return

            ReplayFileWriter.write_string(f"RS;{round};\n")

            self._run_agent_round()
            for command in self._agent_commands:
                self._handle_agent_command(command)
            self._agent_commands.clear()

            agent_commands_message = "Agent_Cmds;{"
            if len(self._command_records) == 0:
                agent_commands_message += "None"
            else:
                agent_commands_message += "$".join(
                    f"[{record}]" for record in self._command_records
                )
            self._command_records.clear()
            agent_commands_message += "}\n"
            ReplayFileWriter.write_string(agent_commands_message)

            self._process_commands()
            self._create_results()
            self._run_simulators()
            self._grim_reaper()
            self._agent_handler.empty_forward_messages()
            ReplayFileWriter.write_string("RE;\n")
            after_json_world = self.get_aegis_world().convert_to_json()

            round_data = {
                "event_type": "Round",
                "round": round,
                "after_world": after_json_world,
            }
            event = json.dumps(round_data).encode()
            self._compress_and_send(event)

        ReplayFileWriter.write_string("Simulation_Over;\n")
        self._end_simulation()

    def _run_agent_round(self) -> None:
        self._agent_handler.reset_current_agent()
        num_of_agents = self._agent_handler.get_number_of_agents()

        for _ in range(num_of_agents):
            try:
                self._agent_handler.send_forward_messages_to_current()
                self._agent_handler.send_result_of_command_to_current()
                self._agent_handler.send_message_to_current(ROUND_START())

                command = self._get_agent_command_of_current()
                if command is not None:
                    self._agent_commands.append(command)
                else:
                    if self._parameters.config_settings is not None:
                        current_agent = self._agent_handler.get_current_agent()
                        if (
                            self._parameters.config_settings.handling_messages
                            == ConfigSettings.SEND_MESSAGES_AND_PERFORM_ACTION
                        ):
                            print(
                                f"Agent {current_agent.agent_id} sent no action (non-send) command this round."
                            )
                        else:
                            print(
                                f"Agent {current_agent.agent_id} sent no command this round."
                            )

                self._agent_handler.send_message_to_current(ROUND_END())
                self._agent_handler.move_to_next_agent()
            except AgentCrashedException:
                crashed_agent_id = self._agent_handler.get_current_agent().agent_id
                self._crashed_agents.add(crashed_agent_id)
            _ = sys.stdout.flush()

    def _get_agent_command_of_current(self) -> AgentCommand | None:
        timeout: int = self._parameters.milliseconds_to_wait_for_agent_command
        initial_time_ms: int = time.time_ns() // 1_000_000
        last_command: AgentCommand | None = None

        while True:
            elapsed_time_ms: int = time.time_ns() // 1_000_000 - initial_time_ms
            if elapsed_time_ms > timeout:
                break

            remaining_time_ms: int = max(0, timeout - elapsed_time_ms)
            if remaining_time_ms == 0:
                break

            try:
                temp_command = self._agent_handler.get_agent_command_of_current(
                    remaining_time_ms
                )
            except AgentCrashedException:
                crashed_agent_id = self._agent_handler.get_current_agent().agent_id
                self._crashed_agents.add(crashed_agent_id)
                print(f"Agent {crashed_agent_id} has crashed.")
                return None

            if temp_command is None:
                continue

            if isinstance(temp_command, END_TURN) or isinstance(
                temp_command, AGENT_UNKNOWN
            ):
                break

            if isinstance(temp_command, SEND_MESSAGE):
                if self._parameters.config_settings is not None:
                    if (
                        self._parameters.config_settings.handling_messages
                        == ConfigSettings.SEND_MESSAGES_AND_PERFORM_ACTION
                    ):
                        self._handle_agent_command(temp_command)
                    else:
                        last_command = temp_command
            else:
                last_command = temp_command

        return last_command

    def _handle_agent_command(self, command: AgentCommand) -> None:
        self._command_records.append(command.proc_string())

        agent = self._aegis_world.get_agent(command.get_agent_id())
        if agent is not None:
            agent.command_sent = str(command)

        if isinstance(command, TEAM_DIG):
            self._TEAM_DIG_list.append(command)
        elif isinstance(command, SAVE_SURV):
            self._SAVE_SURV_list.append(command)
        elif isinstance(command, MOVE):
            self._MOVE_list.append(command)
        elif isinstance(command, SLEEP):
            self._SLEEP_list.append(command)
        elif isinstance(command, OBSERVE):
            self._OBSERVE_list.append(command)
        elif isinstance(command, SEND_MESSAGE):
            send_message: SEND_MESSAGE = command
            fwd_message = FWD_MESSAGE(
                send_message.get_agent_id(),
                send_message.agent_id_list,
                send_message.message,
            )
            if send_message.agent_id_list.is_empty():
                if self._parameters.config_settings is not None:
                    if self._parameters.config_settings.send_messages_to_all_groups:
                        self._agent_handler.forward_message_to_all(fwd_message)
                    else:
                        self._agent_handler.forward_message_to_group(
                            send_message.get_agent_id().gid, fwd_message
                        )
            else:
                self._agent_handler.forward_message(fwd_message)

    def _process_commands(self) -> None:
        self._process_TEAM_DIG()
        self._process_SAVE_SURV()
        self._process_MOVE()
        self._process_SLEEP()
        self._process_OBSERVE()

    def _process_TEAM_DIG(self) -> None:
        temp_agent_list: AgentIDList = AgentIDList()
        for team_dig in self._TEAM_DIG_list:
            temp_agent_list.add(team_dig.get_agent_id())
        self._TEAM_DIG_list.clear()

        temp_grid_agent_list = AgentIDList()
        while temp_agent_list.size() > 0:
            temp_grid_agent_list.clear()
            agent_id = temp_agent_list.remove_at(0)
            temp_grid_agent_list.add(agent_id)

            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                continue

            grid = self._aegis_world.get_grid_at(agent.location)

            if grid is None:
                continue

            for grid_agent in grid.agent_id_list:
                if grid_agent in temp_agent_list:
                    temp_grid_agent_list.add(grid_agent)
                    temp_agent_list.remove(grid_agent)

            top_layer = grid.get_top_layer()
            if top_layer is None:
                self._remove_energy_from_agents(
                    temp_grid_agent_list, self._parameters.TEAM_DIG_ENERGY_COST
                )
                continue

            if isinstance(top_layer, Rubble):
                if top_layer.remove_agents <= temp_grid_agent_list.size():
                    self._aegis_world.remove_layer_from_grid(grid.location)
                    self._remove_energy_from_agents(
                        temp_grid_agent_list, top_layer.remove_energy
                    )
                else:
                    self._remove_energy_from_agents(
                        temp_grid_agent_list, self._parameters.TEAM_DIG_ENERGY_COST
                    )

        temp_agent_list.clear()

    def _remove_energy_from_agents(
        self, agent_list: AgentIDList, energy_cost: int
    ) -> None:
        for agent_id in agent_list:
            agent = self._aegis_world.get_agent(agent_id)
            if agent is not None:
                agent.remove_energy(energy_cost)
                self._TEAM_DIG_RESULT_list.add(agent_id)

    def _process_SAVE_SURV(self) -> None:
        temp_agent_list = AgentIDList()
        for save_surv in self._SAVE_SURV_list:
            temp_agent_list.add(save_surv.get_agent_id())

        self._SAVE_SURV_list.clear()
        temp_grid_agent_list: list[AgentID] = []

        while temp_agent_list.size() > 0:
            temp_grid_agent_list.clear()
            gid_counter: list[int] = [0] * 10

            agent_id = temp_agent_list.remove_at(0)
            temp_grid_agent_list.append(agent_id)
            gid_counter[agent_id.gid] += 1

            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                continue

            grid = self._aegis_world.get_grid_at(agent.location)

            if grid is None:
                continue

            for grid_agent in grid.agent_id_list:
                if grid_agent in temp_agent_list:
                    temp_grid_agent_list.append(grid_agent)
                    temp_agent_list.remove(grid_agent)
                    gid_counter[grid_agent.gid] += 1

            top_layer = grid.get_top_layer()
            if top_layer is None:
                for agent_on_grid in temp_grid_agent_list:
                    agent = self._aegis_world.get_agent(agent_on_grid)
                    if agent is not None:
                        agent.remove_energy(self._parameters.SAVE_SURV_ENERGY_COST)
                        self._SAVE_SURV_RESULT_list.add(agent_on_grid)
            else:
                self._handle_top_layer(
                    top_layer, grid, temp_grid_agent_list, gid_counter
                )

        temp_agent_list.clear()

    def _process_MOVE(self) -> None:
        for move in self._MOVE_list:
            agent = self._aegis_world.get_agent(move.get_agent_id())
            if agent is None:
                continue

            dest_location = agent.location.add(move.direction)
            dest_grid = self._aegis_world.get_grid_at(dest_location)

            if move.direction != Direction.CENTER and dest_grid:
                agent.remove_energy(dest_grid.move_cost)
                self._aegis_world.move_agent(agent.agent_id, dest_location)
                agent.orientation = move.direction
                agent.add_step_taken()
            else:
                agent.remove_energy(self._parameters.MOVE_ENERGY_COST)
            self._MOVE_RESULT_list.add(move.get_agent_id())
        self._MOVE_list.clear()

    def _process_SLEEP(self) -> None:
        for sleep in self._SLEEP_list:
            agent = self._aegis_world.get_agent(sleep.get_agent_id())
            if agent is None:
                continue

            agent_grid = self._aegis_world.get_grid_at(agent.location)
            config_settings = self._parameters.config_settings

            if (config_settings and config_settings.sleep_everywhere) or (
                agent_grid and agent_grid.is_charging_grid()
            ):
                if (
                    agent.get_energy_level() + Constants.NORMAL_CHARGE
                    > Constants.DEFAULT_MAX_ENERGY_LEVEL
                ):
                    agent.set_energy_level(Constants.DEFAULT_MAX_ENERGY_LEVEL)
                else:
                    agent.add_energy(Constants.NORMAL_CHARGE)
            self._SLEEP_RESULT_list.add(sleep.get_agent_id())
        self._SLEEP_list.clear()

    def _process_OBSERVE(self) -> None:
        for observe in self._OBSERVE_list:
            agent = self._aegis_world.get_agent(observe.get_agent_id())
            if agent is None:
                continue

            agent.remove_energy(self._parameters.OBSERVE_ENERGY_COST)
            self._OBSERVE_RESULT_list.append(observe)
        self._OBSERVE_list.clear()

    def _create_results(self) -> None:
        for agent_id in self._TEAM_DIG_RESULT_list:
            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                continue

            surround_info = self._aegis_world.get_surround_info(agent.location)
            if surround_info is None:
                continue

            team_dig_result = TEAM_DIG_RESULT(agent.get_energy_level(), surround_info)
            self._agent_handler.set_result_of_command(agent.agent_id, team_dig_result)
        self._TEAM_DIG_RESULT_list.clear()

        for agent_id in self._SAVE_SURV_RESULT_list:
            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                continue

            surround_info = self._aegis_world.get_surround_info(agent.location)
            if surround_info is None:
                continue

            save_surv_result = SAVE_SURV_RESULT(agent.get_energy_level(), surround_info)
            self._agent_handler.set_result_of_command(agent.agent_id, save_surv_result)

        self._SAVE_SURV_RESULT_list.clear()

        for agent_id in self._MOVE_RESULT_list:
            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                continue

            surround_info = self._aegis_world.get_surround_info(agent.location)
            if surround_info is None:
                continue

            move_result = MOVE_RESULT(agent.get_energy_level(), surround_info)
            self._agent_handler.set_result_of_command(agent.agent_id, move_result)
        self._MOVE_RESULT_list.clear()

        for agent_id in self._SLEEP_RESULT_list:
            agent = self._aegis_world.get_agent(agent_id)
            if agent is None:
                continue

            success = False
            agent_grid = self._aegis_world.get_grid_at(agent.location)
            config_settings = self._parameters.config_settings

            if (config_settings and config_settings.sleep_everywhere) or (
                agent_grid and agent_grid.is_charging_grid()
            ):
                success = True
            sleep_result = SLEEP_RESULT(success, agent.get_energy_level())
            self._agent_handler.set_result_of_command(agent.agent_id, sleep_result)
        self._SLEEP_RESULT_list.clear()

        for observe in self._OBSERVE_RESULT_list:
            agent = self._aegis_world.get_agent(observe.get_agent_id())
            if agent is None:
                continue

            grid_info = GridInfo()
            life_signals = LifeSignals()
            grid = self._aegis_world.get_grid_at(observe.location)

            if grid is not None:
                grid_info = grid.get_grid_info()
                life_signals = grid.get_generated_life_signals()
            observe_result = OBSERVE_RESULT(
                agent.get_energy_level(), grid_info, life_signals
            )

            self._agent_handler.set_result_of_command(agent.agent_id, observe_result)
        self._OBSERVE_RESULT_list.clear()

    def _run_simulators(self) -> None:
        ReplayFileWriter.write_string(self._aegis_world.run_simulators())

    def _grim_reaper(self) -> None:
        dead_agents = self._aegis_world.grim_reaper()
        dead_agents.add_all(self._crashed_agents)
        self._crashed_agents.clear()

        dead_agents_message = "Dead_Agents; { "
        if not dead_agents:
            dead_agents_message += "NONE"
        else:
            for agent_id in dead_agents:
                agent = self._aegis_world.get_agent(agent_id)
                dead_agents_message += f"{agent_id.proc_string()},"
                self._aegis_world.remove_agent(agent)
                try:
                    self._agent_handler.send_message_to(agent_id, DEATH_CARD())
                    self._agent_handler.remove_agent(agent_id)
                except AgentCrashedException:
                    pass
        dead_agents_message += " };\n"
        ReplayFileWriter.write_string(dead_agents_message)

    def get_aegis_world(self) -> AegisWorld:
        return self._aegis_world

    def _handle_top_layer(
        self,
        top_layer: WorldObject,
        grid: Grid,
        temp_grid_agent_list: list[AgentID],
        gid_counter: list[int],
    ) -> None:
        if isinstance(top_layer, (Survivor, SurvivorGroup)):
            self._aegis_world.remove_layer_from_grid(grid.location)
            alive_count, dead_count = self._calculate_survivor_stats(top_layer)
            self._assign_points(
                temp_grid_agent_list, alive_count, dead_count, gid_counter
            )

        else:
            for agent_id in temp_grid_agent_list:
                agent = self._aegis_world.get_agent(agent_id)
                if agent is not None:
                    agent.remove_energy(self._parameters.SAVE_SURV_ENERGY_COST)
                    self._SAVE_SURV_RESULT_list.add(agent_id)

    def _calculate_survivor_stats(
        self, survivor: Survivor | SurvivorGroup
    ) -> tuple[int, int]:
        alive_count = 0
        dead_count = 0

        if isinstance(survivor, SurvivorGroup):
            self._aegis_world.remove_survivor_group(survivor)
            if survivor.is_alive():
                alive_count += survivor.number_of_survivors
            else:
                dead_count += survivor.number_of_survivors
        else:
            self._aegis_world.remove_survivor(survivor)
            if survivor.is_alive():
                alive_count += 1
            else:
                dead_count += 1
        return alive_count, dead_count

    def _assign_points(
        self,
        temp_grid_agent_list: list[AgentID],
        alive_count: int,
        dead_count: int,
        gid_counter: list[int],
    ) -> None:
        if self._parameters.config_settings is None:
            return

        points_config = self._parameters.config_settings.points_for_saving_survivors
        points_tie_config = (
            self._parameters.config_settings.points_for_saving_survivors_tie
        )

        if points_config == ConfigSettings.POINTS_FOR_ALL_SAVING_GROUPS:
            for gid, count in enumerate(gid_counter):
                if count > 0:
                    if alive_count > 0:
                        state = Constants.SAVE_STATE_ALIVE
                        amount = alive_count
                    else:
                        state = Constants.SAVE_STATE_DEAD
                        amount = dead_count
                    self._agent_handler.increase_agent_group_saved(gid, amount, state)

        elif points_config == ConfigSettings.POINTS_FOR_RANDOM_SAVING_GROUPS:
            random_id = temp_grid_agent_list[
                Utility.next_int() % len(temp_grid_agent_list)
            ]
            if alive_count > 0:
                state = Constants.SAVE_STATE_ALIVE
                amount = alive_count
            else:
                state = Constants.SAVE_STATE_DEAD
                amount = dead_count
            self._agent_handler.increase_agent_group_saved(random_id.gid, amount, state)
        elif points_config == ConfigSettings.POINTS_FOR_LARGEST_SAVING_GROUPS:
            largest_group_gid = 0
            max_group_size = 0
            tie = False

            for gid, count in enumerate(gid_counter):
                if count > max_group_size:
                    largest_group_gid = gid
                    max_group_size = count

            for gid, count in enumerate(gid_counter):
                if gid != largest_group_gid and count == max_group_size:
                    tie = True
                    break

            if not tie:
                if alive_count > 0:
                    state = Constants.SAVE_STATE_ALIVE
                    amount = alive_count
                else:
                    state = Constants.SAVE_STATE_DEAD
                    amount = dead_count
                self._agent_handler.increase_agent_group_saved(
                    largest_group_gid,
                    amount,
                    state,
                )
            else:
                if points_tie_config == ConfigSettings.POINTS_TIE_RANDOM_SAVING_GROUPS:
                    self._handle_random_tie(
                        alive_count, dead_count, gid_counter, max_group_size
                    )
                elif points_tie_config == ConfigSettings.POINTS_TIE_ALL_SAVING_GROUPS:
                    self._handle_all_tie(
                        alive_count, dead_count, gid_counter, max_group_size
                    )

        for agent_on_grid_id in temp_grid_agent_list:
            agent = self._aegis_world.get_agent(agent_on_grid_id)
            if agent is not None:
                agent.remove_energy(self._parameters.SAVE_SURV_ENERGY_COST)
                self._SAVE_SURV_RESULT_list.add(agent_on_grid_id)

    def _handle_random_tie(
        self,
        alive_count: int,
        dead_count: int,
        gid_counter: list[int],
        max_group_size: int,
    ) -> None:
        while True:
            random_id = Utility.next_int() % len(gid_counter)
            if gid_counter[random_id] == max_group_size:
                if alive_count > 0:
                    state = Constants.SAVE_STATE_ALIVE
                    amount = alive_count
                else:
                    state = Constants.SAVE_STATE_DEAD
                    amount = dead_count
                self._agent_handler.increase_agent_group_saved(random_id, amount, state)
                break

    def _handle_all_tie(
        self,
        alive_count: int,
        dead_count: int,
        gid_counter: list[int],
        max_group_size: int,
    ) -> None:
        for gid, count in enumerate(gid_counter):
            if count == max_group_size:
                if alive_count > 0:
                    state = Constants.SAVE_STATE_ALIVE
                    amount = alive_count
                else:
                    state = Constants.SAVE_STATE_DEAD
                    amount = dead_count

                self._agent_handler.increase_agent_group_saved(gid, amount, state)

    def _compress_and_send(self, event: bytes) -> None:
        compressed_event = gzip.compress(event)
        encoded_event = base64.b64encode(compressed_event).decode().encode()
        self._ws_server.add_event(encoded_event)
