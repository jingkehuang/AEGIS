import json
import os
import re
from collections.abc import Iterator
from typing import TextIO

from aegis.common import (
    AgentID,
    AgentIDList,
    Direction,
    GridType,
    LifeSignals,
    Location,
)
from aegis.common.commands.aegis_command import AegisCommand
from aegis.common.commands.aegis_commands import (
    AEGIS_UNKNOWN,
    CMD_RESULT_END,
    CMD_RESULT_START,
    CONNECT_OK,
    DEATH_CARD,
    DISCONNECT,
    FWD_MESSAGE,
    MESSAGES_END,
    MESSAGES_START,
    MOVE_RESULT,
    OBSERVE_RESULT,
    ROUND_END,
    ROUND_START,
    SAVE_SURV_RESULT,
    SLEEP_RESULT,
    TEAM_DIG_RESULT,
)
from aegis.common.commands.agent_command import AgentCommand
from aegis.common.commands.agent_commands import (
    AGENT_UNKNOWN,
    CONNECT,
    END_TURN,
    MOVE,
    OBSERVE,
    SAVE_SURV,
    SEND_MESSAGE,
    SLEEP,
    TEAM_DIG,
)
from aegis.common.commands.command import Command
from aegis.common.parsers.aegis_parser_exception import AegisParserException
from aegis.common.world.grid import Grid
from aegis.common.world.info import (
    GridInfo,
    NoLayersInfo,
    RubbleInfo,
    SurroundInfo,
    SurvivorGroupInfo,
    SurvivorInfo,
    WorldObjectInfo,
)

MOVE_COST_TOGGLE: bool = json.load(open("sys_files/aegis_config.json"))[
    "Enable_Move_Cost"
]


class AegisParser:
    @staticmethod
    def build_world(file_location: str) -> list[list[Grid]] | None:
        world: list[list[Grid]] | None = None
        try:
            with open(file_location) as file:
                world = AegisParser.read_world_size(file)
                for line in file:
                    grid = AegisParser.read_and_build_grid(line)
                    world[grid.location.x][grid.location.y] = grid
        except FileNotFoundError:
            if not file_location.startswith(os.getcwd()):
                raise AegisParserException(
                    "Please make sure your path to the world information file has no spaces, weird characters etc."
                )
            else:
                raise AegisParserException(
                    f"Unable to find startup world information file from {file_location}"
                )
        except Exception:
            raise AegisParserException(
                f"Unable to read in startup world information file from {file_location}"
            )
        return world

    @staticmethod
    def read_world_size(file: TextIO) -> list[list[Grid]]:
        tokens = file.readline().split()
        width = int(tokens[3])
        height = int(tokens[6])
        return [[None] * height for _ in range(width)]  # pyright: ignore[reportReturnType]

    @staticmethod
    def read_and_build_grid(line: str) -> Grid:
        pattern = r"[\[\]\(\),% ]"
        tokens = re.split(pattern, line.strip())
        tokens = [token for token in tokens if token]
        x = int(tokens[0])
        y = int(tokens[1])
        fire = tokens[2]
        killer = tokens[3]
        charging = tokens[4]
        percent_chance = int(tokens[5])
        grid = Grid(x, y)

        grid.set_normal_grid()
        grid.set_on_fire(fire[0] == "+")

        if killer[0] == "+":
            grid.set_killer()
            grid.set_killer_grid()

        if charging[0] == "+":
            grid.set_charging_grid()

        grid.percent_chance = percent_chance

        if MOVE_COST_TOGGLE:
            grid.move_cost = int(tokens[6])
        return grid

    @staticmethod
    def parse_aegis_command(string: str) -> AegisCommand:
        try:
            string = string.strip()
            tokens = iter(string.split())
            if string.startswith(Command.STR_CONNECT_OK):
                AegisParser.text(tokens, Command.STR_CONNECT_OK)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "ID")
                id = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "GID")
                gid = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "ENG_LEV")
                energy_level = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "LOC")
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "X")
                x = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "Y")
                y = AegisParser.integer(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "FILE")
                file_name = AegisParser.file(tokens)
                AegisParser.done(tokens)
                return CONNECT_OK(
                    AgentID(id, gid), energy_level, Location(x, y), file_name
                )
            elif string.startswith(Command.STR_DISCONNECT):
                AegisParser.text(tokens, Command.STR_DISCONNECT)
                AegisParser.done(tokens)
                return DISCONNECT()
            elif string.startswith(Command.STR_UNKNOWN):
                AegisParser.text(tokens, Command.STR_UNKNOWN)
                AegisParser.done(tokens)
                return AEGIS_UNKNOWN()
            elif string.startswith(Command.STR_CMD_RESULT_END):
                AegisParser.text(tokens, Command.STR_CMD_RESULT_END)
                AegisParser.done(tokens)
                return CMD_RESULT_END()
            elif string.startswith(Command.STR_CMD_RESULT_START):
                AegisParser.text(tokens, Command.STR_CMD_RESULT_START)
                AegisParser.open_round_bracket(tokens)
                results = AegisParser.integer(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return CMD_RESULT_START(results)
            elif string.startswith(Command.STR_DEATH_CARD):
                AegisParser.text(tokens, Command.STR_DEATH_CARD)
                AegisParser.done(tokens)
                return DEATH_CARD()
            elif string.startswith(Command.STR_FWD_MESSAGE):
                AegisParser.text(tokens, Command.STR_FWD_MESSAGE)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "IDFrom")
                AegisParser.open_round_bracket(tokens)
                id = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                gid = AegisParser.integer(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "MsgSize")
                msg_size = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "NUM_TO")
                number_left_to_read = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "IDS")
                AegisParser.open_round_bracket(tokens)
                agent_id_list = AegisParser.id_list(tokens, number_left_to_read)
                AegisParser.close_round_bracket(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "MSG")
                msg_index = string.index("MSG") + 4
                msg_end = msg_index + msg_size
                message = string[msg_index:msg_end]
                tokens = iter(string[msg_end + 1 :].split())
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return FWD_MESSAGE(AgentID(id, gid), agent_id_list, message)
            elif string.startswith(Command.STR_MESSAGES_END):
                AegisParser.text(tokens, Command.STR_MESSAGES_END)
                AegisParser.done(tokens)
                return MESSAGES_END()
            elif string.startswith(Command.STR_MESSAGES_START):
                AegisParser.text(tokens, Command.STR_MESSAGES_START)
                AegisParser.open_round_bracket(tokens)
                messages = AegisParser.integer(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return MESSAGES_START(messages)
            elif string.startswith(Command.STR_MOVE_RESULT):
                AegisParser.text(tokens, Command.STR_MOVE_RESULT)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "ENG_LEV")
                energy_level = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                surround_information = AegisParser.surround_info(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return MOVE_RESULT(energy_level, surround_information)
            elif string.startswith(Command.STR_OBSERVE_RESULT):
                AegisParser.text(tokens, Command.STR_OBSERVE_RESULT)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "ENG_LEV")
                energy_level = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "GRID_INFO")
                AegisParser.open_round_bracket(tokens)
                grid_info = AegisParser.grid_info(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "NUM_SIG")
                num_sig = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "LIFE_SIG")
                AegisParser.open_round_bracket(tokens)
                signals = AegisParser.life_signals(tokens, num_sig)
                AegisParser.close_round_bracket(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return OBSERVE_RESULT(energy_level, grid_info, signals)
            elif string.startswith(Command.STR_ROUND_END):
                AegisParser.text(tokens, Command.STR_ROUND_END)
                AegisParser.done(tokens)
                return ROUND_END()
            elif string.startswith(Command.STR_ROUND_START):
                AegisParser.text(tokens, Command.STR_ROUND_START)
                AegisParser.done(tokens)
                return ROUND_START()
            elif string.startswith(Command.STR_SAVE_SURV_RESULT):
                AegisParser.text(tokens, Command.STR_SAVE_SURV_RESULT)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "ENG_LEV")
                energy_level = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "SUR_INFO")
                surround_information = AegisParser.surround_info(tokens)
                AegisParser.close_round_bracket(tokens)
                return SAVE_SURV_RESULT(energy_level, surround_information)
            elif string.startswith(Command.STR_SLEEP_RESULT):
                AegisParser.text(tokens, Command.STR_SLEEP_RESULT)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "RESULT")
                success = AegisParser.boolean(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "CH_ENG")
                charge_energy = AegisParser.integer(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return SLEEP_RESULT(success, charge_energy)
            elif string.startswith(Command.STR_TEAM_DIG_RESULT):
                AegisParser.text(tokens, Command.STR_TEAM_DIG_RESULT)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "ENG_LEV")
                energy_level = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                surround_information = AegisParser.surround_info(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return TEAM_DIG_RESULT(energy_level, surround_information)
            raise AegisParserException(f"Cannot parse AEGIS Action from {string}")
        except Exception as e:
            print(f"Exception: {e}")
            return AEGIS_UNKNOWN()

    @staticmethod
    def parse_agent_command(string: str) -> AgentCommand:
        try:
            string = string.strip()
            tokens = iter(string.split())
            if string.startswith(Command.STR_CONNECT):
                AegisParser.text(tokens, Command.STR_CONNECT)
                AegisParser.open_round_bracket(tokens)
                group_name = next(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return CONNECT(group_name)
            elif string.startswith(Command.STR_END_TURN):
                AegisParser.text(tokens, Command.STR_END_TURN)
                AegisParser.done(tokens)
                return END_TURN()
            elif string.startswith(Command.STR_MOVE):
                AegisParser.text(tokens, Command.STR_MOVE)
                AegisParser.open_round_bracket(tokens)
                dir = AegisParser.direction(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return MOVE(dir)
            elif string.startswith(Command.STR_OBSERVE):
                AegisParser.text(tokens, Command.STR_OBSERVE)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "X")
                x = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "Y")
                y = AegisParser.integer(tokens)
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return OBSERVE(Location(x, y))
            elif string.startswith(Command.STR_SAVE_SURV):
                AegisParser.text(tokens, Command.STR_SAVE_SURV)
                AegisParser.done(tokens)
                return SAVE_SURV()
            elif string.startswith(Command.STR_SEND_MESSAGE):
                AegisParser.text(tokens, Command.STR_SEND_MESSAGE)
                AegisParser.open_round_bracket(tokens)
                AegisParser.text(tokens, "NumTo")
                num_to = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "MsgSize")
                msg_size = AegisParser.integer(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "ID_List")
                AegisParser.open_round_bracket(tokens)
                agent_id_list = AegisParser.id_list(tokens, num_to)
                AegisParser.close_round_bracket(tokens)
                AegisParser.comma(tokens)
                AegisParser.text(tokens, "MSG")
                msg_index = string.index("MSG") + 4
                msg_end = msg_index + msg_size
                message = string[msg_index:msg_end]
                tokens = iter(string[msg_end + 1 :].split())
                AegisParser.close_round_bracket(tokens)
                AegisParser.done(tokens)
                return SEND_MESSAGE(agent_id_list, message)
            elif string.startswith(Command.STR_SLEEP):
                AegisParser.text(tokens, Command.STR_SLEEP)
                AegisParser.done(tokens)
                return SLEEP()
            elif string.startswith(Command.STR_TEAM_DIG):
                AegisParser.text(tokens, Command.STR_TEAM_DIG)
                AegisParser.done(tokens)
                return TEAM_DIG()
            
            # raise AegisParserException(
            #     f"Cannot parse Agent to Kernel Command from {string}"
            # )
            
            else:
                print(f"Cannot parse Agent to Kernel Command from {string} | Did your agent throw an exception?")
                return AGENT_UNKNOWN()
        except Exception as e:
            print(e)
            return AGENT_UNKNOWN()

    @staticmethod
    def text(tokens: Iterator[str], string: str) -> None:
        token = next(tokens)
        if token != string:
            raise AegisParserException(f"Expected: {string}, found: {token} ")

    @staticmethod
    def integer(tokens: Iterator[str]) -> int:
        token = next(tokens)
        try:
            return int(token)
        except Exception:
            raise AegisParserException(f"Expected <int>, found {token}")

    @staticmethod
    def boolean(tokens: Iterator[str]) -> bool:
        token = next(tokens)
        try:
            return bool(token)
        except Exception:
            raise AegisParserException(f"Expected <bool>, found {token}")

    @staticmethod
    def file(tokens: Iterator[str]) -> str:
        file = ""
        while True:
            token = next(tokens)
            if token == ")":
                return file
            file += token

    @staticmethod
    def direction(tokens: Iterator[str]) -> Direction:
        token = next(tokens)
        try:
            return Direction[token.upper()]
        except Exception:
            raise AegisParserException(f"Expected: <Direction>, found: {token} ")

    @staticmethod
    def id_list(tokens: Iterator[str], number_left_to_read: int) -> AgentIDList:
        id_list = AgentIDList()
        for i in range(number_left_to_read):
            AegisParser.open_square_bracket(tokens)
            AegisParser.text(tokens, "ID")
            id = AegisParser.integer(tokens)
            AegisParser.comma(tokens)
            AegisParser.text(tokens, "GID")
            gid = AegisParser.integer(tokens)
            AegisParser.close_square_bracket(tokens)
            id_list.add(AgentID(id, gid))
            if i < number_left_to_read - 1:
                AegisParser.comma(tokens)
        return id_list

    @staticmethod
    def life_signals(tokens: Iterator[str], num_sig: int) -> LifeSignals:
        signals: list[int] = []
        for i in range(num_sig):
            signal = AegisParser.integer(tokens)
            signals.append(signal)
            if i < num_sig - 1:
                AegisParser.comma(tokens)
        return LifeSignals(signals)

    @staticmethod
    def surround_info(tokens: Iterator[str]) -> SurroundInfo:
        info = SurroundInfo()
        AegisParser.text(tokens, "CURR_GRID")
        AegisParser.open_round_bracket(tokens)
        info.set_current_info(AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "NUM_SIG")
        num_sig = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "LIFE_SIG")
        AegisParser.open_round_bracket(tokens)
        info.life_signals = AegisParser.life_signals(tokens, num_sig)
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.NORTH_WEST))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.NORTH_WEST, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.NORTH))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.NORTH, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.NORTH_EAST))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.NORTH_EAST, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.EAST))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.EAST, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.SOUTH_EAST))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.SOUTH_EAST, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.SOUTH))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.SOUTH, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.SOUTH_WEST))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.SOUTH_WEST, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, str(Direction.WEST))
        AegisParser.open_round_bracket(tokens)
        info.set_surround_info(Direction.WEST, AegisParser.grid_info(tokens))
        AegisParser.close_round_bracket(tokens)
        return info

    @staticmethod
    def grid_info(tokens: Iterator[str]) -> GridInfo:
        grid_type = next(tokens)

        if grid_type not in [
            "CHARGING_GRID",
            "FIRE_GRID",
            "KILLER_GRID",
            "NO_GRID",
            "NORMAL_GRID",
        ]:
            raise AegisParserException(f"Expected <grid_type>, found {grid_type}")

        if grid_type == "NO_GRID":
            return GridInfo()

        normal_grid = grid_type == "NORMAL_GRID"

        AegisParser.open_round_bracket(tokens)
        AegisParser.text(tokens, "X")
        x = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "Y")
        y = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "ON_FIRE")
        on_fire = AegisParser.boolean(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "MV_COST")
        move_cost = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "NUM_AGT")
        num_agt = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "ID_LIST")
        AegisParser.open_round_bracket(tokens)
        agent_id_list = AegisParser.id_list(tokens, num_agt)
        AegisParser.close_round_bracket(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "TOP_LAYER")
        AegisParser.open_round_bracket(tokens)
        top_layer_info = AegisParser.object_info(tokens)
        AegisParser.close_round_bracket(tokens)
        AegisParser.close_round_bracket(tokens)
        grid_type = GridType.NORMAL_GRID if normal_grid else GridType.CHARGING_GRID
        return GridInfo(
            grid_type, Location(x, y), on_fire, move_cost, agent_id_list, top_layer_info
        )

    @staticmethod
    def object_info(tokens: Iterator[str]) -> WorldObjectInfo:
        object_type = next(tokens)
        if object_type == "RUBBLE":
            return AegisParser.rubble_info(tokens)
        elif object_type == "SURVIVOR":
            return AegisParser.survivor_info(tokens)
        elif object_type == "SURVIVOR_GROUP":
            return AegisParser.survivor_group_info(tokens)
        elif object_type == "NO_LAYERS":
            return NoLayersInfo()
        else:
            raise AegisParserException(f"Expected <object>, found {object_type}")

    @staticmethod
    def rubble_info(tokens: Iterator[str]) -> RubbleInfo:
        AegisParser.open_round_bracket(tokens)
        AegisParser.text(tokens, "ID")
        id = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "NUM_TO_RM")
        remove_agents = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "RM_ENG")
        remove_energy = AegisParser.integer(tokens)
        AegisParser.close_round_bracket(tokens)
        return RubbleInfo(id, remove_energy, remove_agents)

    @staticmethod
    def survivor_info(tokens: Iterator[str]) -> SurvivorInfo:
        AegisParser.open_round_bracket(tokens)
        AegisParser.text(tokens, "ID")
        id = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "ENG_LEV")
        energy_level = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "DMG_FAC")
        damage_factor = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "BDM")
        body_mass = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "MS")
        mental_state = AegisParser.integer(tokens)
        AegisParser.close_round_bracket(tokens)
        return SurvivorInfo(id, energy_level, damage_factor, body_mass, mental_state)

    @staticmethod
    def survivor_group_info(tokens: Iterator[str]) -> SurvivorGroupInfo:
        AegisParser.open_round_bracket(tokens)
        AegisParser.text(tokens, "ID")
        id = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "NUM_SV")
        number_of_survivors = AegisParser.integer(tokens)
        AegisParser.comma(tokens)
        AegisParser.text(tokens, "ENG_LV")
        energy_level = AegisParser.integer(tokens)
        AegisParser.close_round_bracket(tokens)
        return SurvivorGroupInfo(id, energy_level, number_of_survivors)

    @staticmethod
    def open_round_bracket(tokens: Iterator[str]) -> None:
        token = next(tokens)
        if token != "(":
            raise AegisParserException(f"Expected: '(', found: {token}")

    @staticmethod
    def close_round_bracket(tokens: Iterator[str]) -> None:
        token = next(tokens)
        if token != ")":
            raise AegisParserException(f"Expected: ')', found: {token}")

    @staticmethod
    def open_square_bracket(tokens: Iterator[str]) -> None:
        token = next(tokens)
        if token != "[":
            raise AegisParserException(f"Expected: '[', found: {token}")

    @staticmethod
    def close_square_bracket(tokens: Iterator[str]) -> None:
        token = next(tokens)
        if token != "]":
            raise AegisParserException(f"Expected: ']', found: {token}")

    @staticmethod
    def comma(tokens: Iterator[str]) -> None:
        token = next(tokens)
        if token != ",":
            raise AegisParserException(f"Expected: ',', found: {token}")

    @staticmethod
    def done(tokens: Iterator[str]) -> None:
        token = next(tokens, None)
        if token is not None:
            raise AegisParserException("Expected to be done parsing")

    @staticmethod
    def vert_line(tokens: Iterator[str]) -> None:
        token = next(tokens)
        if token != "|":
            raise AegisParserException(f"Expected: '|', found: {token}")
