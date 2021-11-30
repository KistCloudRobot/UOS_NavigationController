from enum import Enum
from typing import List, Set


class Robot:
    def __init__(self, name: str):
        self.real_goal = ""
        self.actual_goal = ""
        self.name = name


class RobotPath:
    def __init__(self, origin, destination):
        self.origin = origin
        self.destination = destination


class RobotAction:
    def __init__(self, action_id, participant: Set[Robot], goal, path: List[RobotPath]):
        self.action_id = action_id
        self.participant = participant
        self.goal = goal
        self.move_flag = False
        self.avoid_flag = False
        self.collide_flag = False
        self.path = path
        self.current_location = path[0]
