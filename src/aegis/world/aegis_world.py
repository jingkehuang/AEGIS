import base64
import gzip
import json
import os
import queue
import random
from typing import TypedDict, cast

from aegis.assist.state import State
from aegis.common import AgentID, AgentIDList, Constants, Direction, Location, Utility
from aegis.common.world.agent import Agent
from aegis.common.world.grid import Grid
from aegis.common.world.info import GridInfo, SurroundInfo
from aegis.common.world.objects import Survivor, SurvivorGroup
from aegis.common.world.world import World
from aegis.parsers.aegis_world_file import AegisWorldFile
from aegis.parsers.helper.world_file_type import StackContent, WorldFileType
from aegis.parsers.world_file_parser import WorldFileParser
from aegis.server_websocket import WebSocketServer
from aegis.world.object_handlers import (
    NoLayersHandler,
    ObjectHandler,
    RubbleHandler,
    SurvivorGroupHandler,
    SurvivorHandler,
)
from aegis.world.simulators.fire_simulator import FireSimulator
from aegis.world.simulators.survivor_simulator import SurvivorSimulator


class LocationDict(TypedDict):
    x: int
    y: int


class Stack(TypedDict):
    grid_loc: LocationDict
    move_cost: int
    contents: list[StackContent]


class GridCellDict(TypedDict):
    grid_type: str
    stack: Stack


class AgentInfoDict(TypedDict):
    id: int
    gid: int
    x: int
    y: int
    energy_level: int
    command_sent: str


class WorldDict(TypedDict):
    grid_data: list[GridCellDict]
    agent_data: list[AgentInfoDict]
    top_layer_rem_data: list[LocationDict]
    number_of_alive_agents: int
    number_of_dead_agents: int
    number_of_survivors: int
    number_of_survivors_alive: int
    number_of_survivors_dead: int
    number_of_survivors_saved_alive: int
    number_of_survivors_saved_dead: int


MOVE_COST_TOGGLE: bool = json.load(open("sys_files/aegis_config.json"))[
    "Enable_Move_Cost"
]


class AegisWorld:
    def __init__(self) -> None:
        self._object_handlers: dict[str, ObjectHandler] = {}
        self.install_object_handler(NoLayersHandler())
        self.install_object_handler(RubbleHandler())
        self.install_object_handler(SurvivorGroupHandler())
        self.install_object_handler(SurvivorHandler())
        self._agent_locations: dict[AgentID, Location] = {}
        self._agent_spawn_locations: dict[tuple[Location, int | None], int] = {}
        self._low_survivor_level: int = 0
        self._mid_survivor_level: int = 0
        self._high_survivor_level: int = 0
        self._random_seed: int = 0
        self.round: int = 0
        self._world: World | None = None
        self._agents: list[Agent] = []
        self._safe_grid_list: list[Grid] = []
        self._fire_grids_list: list[Grid] = []
        self._non_fire_grids_list: list[Grid] = []
        self._survivors_list: dict[int, Survivor] = {}
        self._survivor_groups_list: dict[int, SurvivorGroup] = {}
        self._top_layer_removed_grid_list: list[Location] = []
        self._fire_simulator = FireSimulator(
            self._fire_grids_list, self._non_fire_grids_list, self._world
        )
        self._survivor_simulator = SurvivorSimulator(
            self._survivors_list, self._survivor_groups_list
        )
        self._initial_agent_energy: int = Constants.DEFAULT_MAX_ENERGY_LEVEL
        self._agent_world_filename: str = ""
        self._number_of_survivors: int = 0
        self._number_of_alive_agents: int = 0
        self._number_of_dead_agents: int = 0
        self._number_of_survivors_alive: int = 0
        self._number_of_survivors_dead: int = 0
        self._number_of_survivors_saved_alive: int = 0
        self._number_of_survivors_saved_dead: int = 0
        self._max_move_cost: int = 0
        self._states: queue.Queue[State] = queue.Queue()

    def build_world_from_file(self, filename: str, ws_server: WebSocketServer) -> bool:
        try:
            aegis_world_file_info = WorldFileParser().parse_world_file(filename)
            success = self.build_world(aegis_world_file_info)

            world = self._get_json_world(filename)
            data = {"event_type": "World", "data": world}
            compressed_data = gzip.compress(json.dumps(data).encode())
            encoded_data = base64.b64encode(compressed_data).decode().encode()

            ws_server.add_event(encoded_data)
            return success
        except Exception:
            return False

    def build_world(self, aegis_world_file: AegisWorldFile | None) -> bool:
        if aegis_world_file is None:
            return False
        try:
            self._agent_spawn_locations = aegis_world_file.agent_spawn_locations
            self._low_survivor_level = aegis_world_file.low_survivor_level
            self._mid_survivor_level = aegis_world_file.mid_survivor_level
            self._high_survivor_level = aegis_world_file.high_survivor_level
            self._random_seed = aegis_world_file.random_seed
            self._initial_agent_energy = aegis_world_file.initial_agent_energy
            Utility.set_random_seed(aegis_world_file.random_seed)
            self.round = 1

            # Create a world of known size
            self._world = World(
                width=aegis_world_file.width, height=aegis_world_file.height
            )

            # Special type grids
            for grid_setting in aegis_world_file.grid_settings:
                if not grid_setting.locs:
                    continue
                for loc in grid_setting.locs:
                    grid = self._world.get_grid_at(loc)
                    if grid is None:
                        continue
                    grid.setup_grid(grid_setting.name)

            # Grid info (move_cost and contents)
            for grid_info_setting in aegis_world_file.grid_stack_info:
                if not self._world.on_map(grid_info_setting.location):
                    continue

                grid = self._world.get_grid_at(grid_info_setting.location)
                if grid is None:
                    continue
                grid.move_cost = grid_info_setting.move_cost

                # reverse so the top of the stack is actually
                # the top declared in the world file
                grid_info_setting.contents.reverse()
                for content in grid_info_setting.contents:
                    object_handler = self._object_handlers.get(content["type"].upper())
                    if not object_handler:
                        continue

                    layer = object_handler.create_world_object(content["arguments"])
                    if layer is not None:
                        grid.add_layer(layer)

            # Grids that are safe
            for x in range(self._world.width):
                for y in range(self._world.height):
                    grid = self._world.get_grid_at(Location(x, y))
                    if grid is None:
                        continue

                    if grid.is_stable():
                        self._safe_grid_list.append(grid)

            survivor_group_handler = cast(
                SurvivorGroupHandler, self._object_handlers.get("SVG")
            )
            survivor_handler = cast(SurvivorHandler, self._object_handlers.get("SV"))
            self._number_of_survivors_alive = (
                survivor_group_handler.alive + survivor_handler.alive
            )
            self._number_of_survivors_dead = (
                survivor_group_handler.dead + survivor_handler.dead
            )

            self._number_of_survivors = (
                self._number_of_survivors_alive + self._number_of_survivors_dead
            )
            self._survivors_list = survivor_handler.sv_map
            self._survivor_groups_list = survivor_group_handler.svg_map
            self._write_agent_world_file()
            return True
        except Exception as e:
            print(f"Error in building world: {e}")
            return False

    def install_object_handler(self, object_handler: ObjectHandler) -> None:
        keys = object_handler.get_keys()
        for key in keys:
            self._object_handlers[key.upper()] = object_handler

    def _write_agent_world_file(self) -> None:
        try:
            file = "WorldInfoFile.out"
            with open(file, "w") as writer:
                if self._world is None:
                    return

                width = self._world.width
                height = self._world.height
                _ = writer.write(f"Size: ( WIDTH {width} , HEIGHT {height} )\n")
                for x in range(self._world.width):
                    for y in range(self._world.height):
                        grid = self._world.get_grid_at(Location(x, y))
                        if grid is None:
                            _ = writer.write(f"[({x},{y}),No Grid]\n")
                            continue

                        choice = Utility.next_boolean()
                        percent = 0


                        if grid.number_of_survivors() <= 0:
                            percent = 0
                        else:
                            if grid.number_of_survivors() <= self._low_survivor_level:
                                if choice:
                                    percent = Utility.random_in_range(0, 5)
                                else:
                                    percent = 5 + Utility.random_in_range(0, 5)
                            elif grid.number_of_survivors() <= self._mid_survivor_level:
                                if choice:
                                    percent = 15 + Utility.random_in_range(0, 10)
                                else:
                                    percent = 25 + Utility.random_in_range(0, 15)
                            else:
                                if choice:
                                    percent = 15 + Utility.random_in_range(0, 35)
                                else:
                                    percent = 50 + Utility.random_in_range(0, 40)
                            percent = max(1, percent)

                        fire = "+F" if grid.is_on_fire() else "-F"
                        killer = "+K" if grid.is_killer() else "-K"
                        charging = "+C" if grid.is_charging_grid() else "-C"

                        if MOVE_COST_TOGGLE:
                            _ = writer.write(
                                f"[({x},{y}),({fire},{killer},{charging}),{percent:3.0f}%,{grid.move_cost}]\n"
                            )
                        else:
                            _ = writer.write(
                                f"[({x},{y}),({fire},{killer},{charging}),{percent:3.0f}%]\n"
                            )
            path = os.path.realpath(os.getcwd())
            self._agent_world_filename = os.path.join(path, file)
        except Exception:
            print(
                f"Aegis  : Unable to write agent world file to '{self._agent_world_filename}'!"
            )

    def run_simulators(self) -> str:
        s = "Sim_Events;\n"
        if Constants.FIRE_SPREAD:
            s += self._fire_simulator.run()

        s += self._survivor_simulator.run()
        top_layer_remove_message = "Top_Layer_Rem; { "
        if not self._top_layer_removed_grid_list:
            top_layer_remove_message += "NONE"
        else:
            for location in self._top_layer_removed_grid_list:
                top_layer_remove_message += f"{location.proc_string()},"
        top_layer_remove_message += " };\n"
        s += top_layer_remove_message
        self._top_layer_removed_grid_list.clear()

        agents_information_message = "Agents_Information; { "
        if not self._agents:
            agents_information_message += "NONE"
        else:
            for agent in self._agents:
                agents_information_message += f"({agent.agent_id.id},{agent.agent_id.gid},{agent.get_energy_level()},{agent.location.x},{agent.location.y}),"
        agents_information_message += " };\n"
        s += agents_information_message
        s += "End_Sim;\n"
        return s

    def grim_reaper(self) -> AgentIDList:
        dead_agents = AgentIDList()
        for agent in self._agents:
            if agent.get_energy_level() <= 0:
                print(f"Aegis  : Agent {agent} ran out of energy and died.\n")
                dead_agents.add(agent.agent_id)
                continue

            if self._world:
                grid = self._world.get_grid_at(agent.location)
                if grid is None:
                    continue

                if grid.is_on_fire():
                    print(f"Aegis  : Agent {agent} ran into the fire and died.\n")
                    dead_agents.add(agent.agent_id)
                elif grid.is_killer():
                    print(f"Aegis  : Agent {agent} ran into killer grid and died.\n")
                    dead_agents.add(agent.agent_id)

        self._number_of_dead_agents += dead_agents.size()
        return dead_agents

    def get_agent_world_filename(self) -> str:
        return self._agent_world_filename

    def _get_spawn(self, agent_id: AgentID) -> tuple[Location, int | None]:
        # Priority spawn
        spawns = self._agent_spawn_locations
        for spawn, gid in spawns:
            if gid == agent_id.gid:
                return spawn, gid

        # Spawn randomly
        no_gid_locations = [spawn for spawn, gid in spawns if gid is None]

        return random.choice(no_gid_locations), None

    def _delete_prio_spawn(self, loc: Location, gid: int):
        spawn_locs = self._agent_spawn_locations
        key = (loc, gid)
        if key in spawn_locs:
            if spawn_locs[key] > 1:
                spawn_locs[key] -= 1
            else:
                del spawn_locs[key]

    def add_agent_by_id(self, agent_id: AgentID) -> None:
        if self._world is None:
            return

        spawn_loc, gid = self._get_spawn(agent_id)
        grid = self._world.get_grid_at(spawn_loc)

        if grid is not None and gid is not None:
            self._delete_prio_spawn(spawn_loc, gid)

        if grid is None:
            if len(self._safe_grid_list) == 0:
                grid = self._world.get_grid_at(Location(0, 0))
            else:
                grid = random.choice(self._safe_grid_list)

        if grid is None:
            raise Exception("Aegis  : No grid found for agent")

        if grid.is_on_fire():
            print("Aegis  : Warning, agent has been placed on a fire grid!")
        elif grid.is_killer():
            print("Aegis  : Warning, agent has been placed on a killer grid!")

        agent = Agent(agent_id, grid.location, self._initial_agent_energy)
        self.add_agent(agent)

    def add_agent(self, agent: Agent) -> None:
        if agent not in self._agents:
            self._agents.append(agent)
            if self._world is None:
                return

            grid = self._world.get_grid_at(agent.location)
            if grid is None:
                return

            grid.agent_id_list.add(agent.agent_id)
            self._number_of_alive_agents += 1
            print(f"Aegis  : Added agent {agent}")

    def get_agent(self, agent_id: AgentID) -> Agent | None:
        for agent in self._agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def move_agent(self, agent_id: AgentID, location: Location) -> None:
        agent = self.get_agent(agent_id)
        if agent is None or self._world is None:
            return

        curr_grid = self._world.get_grid_at(agent.location)
        dest_grid = self._world.get_grid_at(location)

        if dest_grid is None or curr_grid is None:
            return

        curr_grid.agent_id_list.remove(agent.agent_id)
        dest_grid.agent_id_list.add(agent.agent_id)
        agent.location = dest_grid.location

    def remove_agent(self, agent: Agent | None) -> None:
        if agent in self._agents and self._world is not None:
            self._agents.remove(agent)
            agent_grid = self._world.get_grid_at(agent.location)
            if agent_grid is None:
                return

            agent_grid.agent_id_list.remove(agent.agent_id)
            self._number_of_alive_agents -= 1

    def remove_layer_from_grid(self, location: Location) -> None:
        if self._world is None:
            return

        grid = self._world.get_grid_at(location)
        if grid is None:
            return

        world_object = grid.remove_top_layer()
        if world_object is None:
            return

        self._top_layer_removed_grid_list.append(location)
        if isinstance(world_object, Survivor):
            survivor = world_object
            if survivor.get_energy_level() <= 0:
                self._number_of_survivors_saved_dead += 1
            else:
                self._number_of_survivors_saved_alive += 1
        elif isinstance(world_object, SurvivorGroup):
            survivor_group = world_object
            if survivor_group.get_energy_level() <= 0:
                self._number_of_survivors_saved_dead += (
                    survivor_group.number_of_survivors
                )
            else:
                self._number_of_survivors_saved_alive += (
                    survivor_group.number_of_survivors
                )

    def get_grid_at(self, location: Location) -> Grid | None:
        if self._world is not None:
            return self._world.get_grid_at(location)
        return None

    def get_surround_info(self, location: Location) -> SurroundInfo | None:
        surround_info = SurroundInfo()
        if self._world is None:
            return
        grid = self._world.get_grid_at(location)
        if grid is None:
            return
        surround_info.life_signals = grid.get_generated_life_signals()
        surround_info.set_current_info(grid.get_grid_info())

        for direction in Direction:
            grid = self._world.get_grid_at(location.add(direction))
            if grid is None:
                surround_info.set_surround_info(direction, GridInfo())
            else:
                surround_info.set_surround_info(direction, grid.get_grid_info())
        return surround_info

    def remove_survivor(self, survivor: Survivor) -> None:
        del self._survivors_list[survivor.id]

    def remove_survivor_group(self, survivor_group: SurvivorGroup) -> None:
        del self._survivor_groups_list[survivor_group.id]

    def _get_json_world(self, filename: str) -> WorldFileType:
        with open(filename, "r") as file:
            world: WorldFileType = json.load(file)
        return world

    def convert_to_json(self) -> WorldDict:
        if self._world is None:
            raise Exception(
                "Aegis  : World is not initialized! Cannot send world object to client!"
            )

        agent_data: list[AgentInfoDict] = []
        grid_data: list[GridCellDict] = []
        top_layer_rem_data: list[LocationDict] = []
        agent_map = {
            (
                agent.agent_id.id,
                agent.agent_id.gid,
            ): agent
            for agent in self._agents
        }

        for x in range(self._world.width):
            for y in range(self._world.height):
                grid = self._world.get_grid_at(Location(x, y))
                if grid is None:
                    continue

                grid_info = grid.get_grid_info()
                grid_layers = grid.get_grid_layers()

                grid_dict: GridCellDict = {
                    "grid_type": str(grid_info.grid_type),
                    "stack": {
                        "grid_loc": {"x": x, "y": y},
                        "move_cost": grid_info.move_cost,
                        "contents": [layer.json() for layer in grid_layers],
                    },
                }
                grid_data.append(grid_dict)

                for agent_id in grid.agent_id_list:
                    key = (agent_id.id, agent_id.gid)
                    agent = agent_map.get(key)

                    if agent is not None:
                        agent_dict: AgentInfoDict = {
                            "id": agent.agent_id.id,
                            "gid": agent.agent_id.gid,
                            "x": x,
                            "y": y,
                            "energy_level": agent.get_energy_level(),
                            "command_sent": agent.command_sent,
                        }
                        agent_data.append(agent_dict)

        for top_layer in self._top_layer_removed_grid_list:
            top_dict: LocationDict = {"x": top_layer.x, "y": top_layer.y}
            top_layer_rem_data.append(top_dict)

        world_dict: WorldDict = {
            "grid_data": grid_data,
            "agent_data": agent_data,
            "top_layer_rem_data": top_layer_rem_data,
            "number_of_alive_agents": self._number_of_alive_agents,
            "number_of_dead_agents": self._number_of_dead_agents,
            "number_of_survivors": self._number_of_survivors,
            "number_of_survivors_alive": self._number_of_survivors_alive,
            "number_of_survivors_dead": self._number_of_survivors_dead,
            "number_of_survivors_saved_alive": self._number_of_survivors_saved_alive,
            "number_of_survivors_saved_dead": self._number_of_survivors_saved_dead,
        }

        return world_dict

    def set_state(self, state: State) -> None:
        self._states.put(state)

    def get_state(self) -> State:
        if self._states.empty():
            return State.NONE
        try:
            return self._states.get(block=True)
        except queue.Empty:
            return State.NONE

    def wait_state(self) -> State:
        return self.get_state()

    def get_num_survivors(self) -> int:
        return self._number_of_survivors

    def get_total_saved_survivors(self) -> int:
        return (
            self._number_of_survivors_saved_alive + self._number_of_survivors_saved_dead
        )

    def get_agents(self) -> list[Agent]:
        return self._agents
