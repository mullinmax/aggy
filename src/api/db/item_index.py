from typing import List, Optional
from .base import AggyBaseModel


class ItemIndex(AggyBaseModel):
    source_key: str  # Key of the source (could be feed, source, etc.)
    position: List[float]  # High-dimensional position of the node
    radius: float = None  # Cached radius of the ball
    population: int = 1  # Number of points in this node (default to 1)
    center: List[float] = None  # Cached center of the points (initially the position)

    left_child: Optional[str] = None  # Left child (identified by 0)
    right_child: Optional[str] = None  # Right child (identified by 1)

    def __init__(self, **data):
        super().__init__(**data)
        if self.center is None:
            self.center = self.position

    @property
    def key(self) -> str:
        return f"{self.source_key}:INDEX"

    @property
    def as_dict(self) -> dict:
        return {
            "position": self.position,
            "radius": self.radius,
            "population": self.population,
            "center": self.center,
        }

    def create(self) -> None:
        """Saves the node to Redis."""
        with self.db_con() as r:
            r.set(self.key, self.json)

    def update(self) -> None:
        """Updates the node in Redis."""
        self.create()

    def add_child(self, child_node: "BallTreeNode", is_left: bool) -> None:
        """Adds a left or right child."""
        child_key = f"{self.key}:{'0' if is_left else '1'}"
        if is_left:
            self.left_child = child_key
        else:
            self.right_child = child_key
        child_node.source_key = child_key
        child_node.create()
        self.update()

    @classmethod
    def read(cls, source_key: str) -> "BallTreeNode":
        """Reads the node from Redis."""
        with cls.db_con() as r:
            node_json = r.get(f"{source_key}:INDEX")

        if node_json:
            return cls.model_validate_json(node_json)
        return None

    def split(self, new_position: List[float]) -> "BallTreeNode":
        """Splits the node, creating left and right children based on the new point."""
        # Determine which side to put the new node on
        is_left = self.should_go_left(new_position)

        # Create a new child node
        child_node = BallTreeNode(source_key=self.source_key, position=new_position)

        # Add child and update the radius, population, and center
        self.add_child(child_node, is_left)
        self.update_properties()

        return child_node

    def update_properties(self):
        """Recalculate radius, center, and population."""
        positions = [self.position]
        if self.left_child:
            left_node = self.read(self.left_child)
            positions.append(left_node.position)
        if self.right_child:
            right_node = self.read(self.right_child)
            positions.append(right_node.position)

        self.center = [sum(dim) / len(positions) for dim in zip(*positions)]
        self.radius = max(
            self.calculate_distance(self.center, pos) for pos in positions
        )
        self.population = len(positions)

    @staticmethod
    def calculate_distance(pos1: List[float], pos2: List[float]) -> float:
        """Calculates Euclidean distance between two positions."""
        return sum((x - y) ** 2 for x, y in zip(pos1, pos2)) ** 0.5

    def should_go_left(self, new_position: List[float]) -> bool:
        """Determines if the new point should go left (returns True) or right."""
        return new_position[0] < self.position[0]  # Simple 1D decision for example
