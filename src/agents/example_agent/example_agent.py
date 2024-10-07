# Assignment 01
# Name: Jingke Huang (30115284)
# Date: Oct 07, 2024
# Course: CPSC 383 - Fall 2024
# Tutorial: T02
# Reference for A* Algorithm: https://www.redblobgames.com/pathfinding/a-star/introduction.html

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
        
        
        # Check and print the survivor's location
        if self.SURVIVOR_LOCATION is None:
            world_grid_info = world.get_world_grid()
            for grids in world_grid_info:
                for single_grid in grids:
                    if single_grid.percent_chance > 0:
                        self.SURVIVOR_LOCATION = single_grid.location
                        print("Survivor is at:", self.SURVIVOR_LOCATION)
        
        if self.SURVIVOR_LOCATION:
            # Perform A* search
            path = self.a_star_search(self._agent.get_location(), self.SURVIVOR_LOCATION, world)
            if path:
                next_move = path[0]  # Get the next step from the path
                self.send_and_end_turn(MOVE(next_move))
                return

        # Default action: Move the agent north.
        self.send_and_end_turn(MOVE(Direction.NORTH))

    def a_star_search(self, start, goal, world) -> list:
        """A* pathfinding to find the best path to the survivor using basic lists."""
        open_set = [start]  # Open set has nodes to evaluate
        came_from = {}  # Store the path
        g_score = {start: 0}  # Cost from start to this node
        f_score = {start: self.heuristic(start, goal)}  # Estimated cost from start to goal

        while open_set:
            # Get the lowest f_score
            current = min(open_set, key=lambda loc: f_score.get(loc, float('inf')))

            if current == goal:
                return self.reconstruct_path(came_from, current)

            open_set.remove(current)

            # Explore neighbors
            for direction in Direction:
                neighbor_loc = current.add(direction)
                neighbor_grid = world.get_grid_at(neighbor_loc)
                
                if not neighbor_grid:  # Skip invalid neighbors
                    continue

                # Skip dangerous grids
                if self.is_dangerous(neighbor_grid):
                    continue

                tentative_g_score = g_score[current] + neighbor_grid.move_cost

                if neighbor_loc not in g_score or tentative_g_score < g_score[neighbor_loc]:
                    came_from[neighbor_loc] = (current, direction)
                    g_score[neighbor_loc] = tentative_g_score
                    f_score[neighbor_loc] = tentative_g_score + self.heuristic(neighbor_loc, goal)

                    if neighbor_loc not in open_set:
                        open_set.append(neighbor_loc) # Add neighbor_loc to open_set to explore the map

        return []  # No path found

    def reconstruct_path(self, came_from, current) -> list:
        """Reconstructs the path from A* search result."""
        total_path = []
        while current in came_from:
            current, direction = came_from[current]
            total_path.append(direction)
        total_path.reverse()  # Reverse the path to start from the current position
        return total_path

    def heuristic(self, start, goal) -> int:
        """Heuristic: Manhattan distance on a square grid."""
        return abs(start.x - goal.x) + abs(start.y - goal.y)
    
    def is_dangerous(self, grid: Grid) -> bool:
        """Check if a grid is dangerous."""
        return grid.is_fire_grid() or grid.is_killer_grid() or grid.is_on_fire()


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
