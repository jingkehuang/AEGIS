from typing import override

from aegis.common import Direction
from aegis.common.commands.aegis_commands import MOVE_RESULT, SAVE_SURV_RESULT
from aegis.common.commands.agent_command import AgentCommand
from aegis.common.commands.agent_commands import (
    END_TURN,
    MOVE,
    SAVE_SURV,
)
from aegis.common.world.grid import Grid
from aegis.common.world.info import SurroundInfo, SurvivorInfo, WorldObjectInfo
from aegis.common.world.objects import Survivor
from agent.base_agent import BaseAgent
from agent.brain import Brain
from agent.log_levels import LogLevels


class ExampleAgent(Brain):
    def __init__(self) -> None:
        super().__init__()
        self._agent = BaseAgent.get_base_agent()
        self.SURVIVOR_LOCATION = None

    @override
    def handle_move_result(self, mr: MOVE_RESULT) -> None:
        self.update_surround(mr.surround_info)

    @override
    def handle_save_surv_result(self, ssr: SAVE_SURV_RESULT) -> None:
        self.update_surround(ssr.surround_info)

    @override
    def think(self) -> None:
        BaseAgent.log(LogLevels.Always, "Thinking")

        # At the start of the first round, send a request for surrounding information
        # by moving to the center of the current grid. This will help initiate pathfinding.
        if self._agent.get_round_number() == 1:
            self.send_and_end_turn(MOVE(Direction.CENTER))
            return

        # Retrieve the current state of the world.
        world = self.get_world()
        if world is None:
            self.send_and_end_turn(MOVE(Direction.CENTER))
            return

        # Fetch the grid at the agent’s current location. If the location is outside the world’s bounds,
        # return a default move action and end the turn.
        grid = world.get_grid_at(self._agent.get_location())
        if grid is None:
            self.send_and_end_turn(MOVE(Direction.CENTER))
            return

        # Get the top layer at the agent’s current location.
        # If a survivor is present, save it and end the turn.
        top_layer = grid.get_top_layer()
        if top_layer:
            self.send_and_end_turn(SAVE_SURV())
            return
        
        
        # Check for the survivor's location in the world grid information
        if self.SURVIVOR_LOCATION is None:
            world_grid_info = world.get_world_grid()
            for grids in world_grid_info:
                for single_grid in grids:
                    if single_grid.percent_chance > 0:
                        # Survivor location identified
                        self.SURVIVOR_LOCATION = single_grid.location
                        print("Survivor is at:", self.SURVIVOR_LOCATION)
        
        if self.SURVIVOR_LOCATION:
            # Perform A* search to move towards survivor
            path = self.a_star_search(self._agent.get_location(), self.SURVIVOR_LOCATION, world)
            if path:
                next_move = path[0]  # Get the next step from the path
                self.send_and_end_turn(MOVE(next_move))
                return

        # Default action: Move the agent north if no other specific conditions are met.
        self.send_and_end_turn(MOVE(Direction.NORTH))


    def send_and_end_turn(self, command: AgentCommand):
        """Send a command and end your turn."""
        BaseAgent.log(LogLevels.Always, f"SENDING {command}")
        self._agent.send(command)
        self._agent.send(END_TURN())

    def update_surround(self, surround_info: SurroundInfo):
        """Updates the current and surrounding grid cells of the agent."""
        world = self.get_world()
        if world is None:
            return

        for dir in Direction:
            grid_info = surround_info.get_surround_info(dir)
            if grid_info is None:
                continue

            grid = world.get_grid_at(grid_info.location)
            if grid is None:
                continue

            grid.move_cost = grid_info.move_cost
            self.update_top_layer(grid, grid_info.top_layer_info)

    def update_top_layer(self, grid: Grid, top_layer: WorldObjectInfo):
        """Updates the top layer of the grid. Converting WorldObjectInfo to WorldObject"""
        if isinstance(top_layer, SurvivorInfo):
            layer = Survivor(
                top_layer.id,
                top_layer.energy_level,
                top_layer.damage_factor,
                top_layer.body_mass,
                top_layer.mental_state,
            )
            grid.set_top_layer(layer)
