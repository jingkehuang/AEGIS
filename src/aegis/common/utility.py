import random
import sys
from enum import Enum


class GridType(Enum):
    """Enum representing different types of grids."""

    NO_GRID = 1
    NORMAL_GRID = 2
    CHARGING_GRID = 3
    FIRE_GRID = 4
    KILLER_GRID = 5


class Utility:
    """A utility class."""

    random.seed(12345)

    @staticmethod
    def random_in_range(low: int, high: int) -> int:
        """
        Returns a random number between low and high.

        Args:
            low: The lower bound of the range.
            high: The upper bound of the range.
        """
        return low + random.randint(0, high - low)

    @staticmethod
    def set_random_seed(seed: int) -> None:
        """
        Sets the seed of the random number generator.

        Args:
            seed: The seed value for the random number generator.
        """
        random.seed(seed)

    @staticmethod
    def next_int() -> int:
        """Returns a random number between 0 and sys.maxsize."""
        return abs(random.randint(0, sys.maxsize))

    @staticmethod
    def next_boolean() -> bool:
        """Returns a random boolean value."""
        return random.choice([True, False])
