from __future__ import annotations

from typing import override
from aegis.common.direction import Direction


class Location:
    """
    Represents a location in the world.

    Attributes:
        x (int): The x-coordinate of the location.
        y (int): The y-coordinate of the location.
    """

    def __init__(self, x: int, y: int) -> None:
        """
        Initializes a new Location instance.

        Args:
            x: The x-coordinate of the location.
            y: The y-coordinate of the location.
        """
        self.x = x
        self.y = y

    @override
    def __str__(self) -> str:
        return f"( X {self.x} , Y {self.y} )"

    def proc_string(self) -> str:
        """Returns a string representation of the Location in a procedular format."""
        return f"( {self.x}, {self.y} )"

    def clone(self) -> Location:
        """
        Creates and returns a new Location with the same coordinates.

        Returns:
            A new Location object with same coordinates as the current instance.
        """
        return Location(self.x, self.y)

    @override
    def __hash__(self) -> int:
        hash = 3
        hash = 89 * hash + self.x
        hash = 89 * hash + self.y
        return hash

    def add(self, direction: Direction) -> Location:
        """
        Adds the given direction to the current location.

        Args:
            direction: The direction to add to the current location.

        Returns:
            A new Location object one unit away in the given direction.
        """
        return Location(self.x + direction.dx, self.y + direction.dy)

    def distance_to(self, location: Location) -> int:
        """
        Calculates the squared distance between the current location
        and the given location.

        Args:
            location: The location to which the distance is calculated.

        Returns:
            The squared distance to the given location.
        """
        dx = self.x - location.x
        dy = self.y - location.y
        return dx * dx + dy * dy

    @override
    def __eq__(self, other: object) -> bool:
        if isinstance(other, Location):
            return self.x == other.x and self.y == other.y
        return False

    @override
    def __ne__(self, other: object) -> bool:
        if isinstance(other, Location):
            return not self.__eq__(other)
        return False

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Location):
            if self.x < other.x:
                return True
            elif self.x == other.x:
                return self.y < other.y
        return False

    def __gt__(self, other: object) -> bool:
        if isinstance(other, Location):
            if self.x > other.x:
                return True
            elif self.x == other.x:
                return self.y > other.y
        return False

    def __le__(self, other: object) -> bool:
        if isinstance(other, Location):
            return self.__lt__(other) or self.__eq__(other)
        return False

    def __ge__(self, other: object) -> bool:
        if isinstance(other, Location):
            return self.__gt__(other) or self.__eq__(other)
        return False
