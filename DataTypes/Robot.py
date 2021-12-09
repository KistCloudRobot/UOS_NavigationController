from enum import Enum
from typing import List, Set


class Robot:
    def __init__(self, name: str, position):
        self.name = name
        self.current_action: RobotAction = None
        self.position = position


class RobotAction:
    def __init__(self, action_id, participant: Set[Robot], goal, path: List[int]):
        self.action_id = action_id
        self.participant = participant
        self.goal = goal
        self.move_flag = False
        self.avoid_flag = False
        self.collide_flag = False
        self.path = path

