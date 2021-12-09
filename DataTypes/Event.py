from enum import Enum


class EventType(Enum):
    """type for NC Events"""
    MOVE_REQUEST = 1
    COLLIDABLE = 2
    MULTIROBOT_POSE = 3
    DATA_RECEIVED = 4


class Event:
    def __init__(self, type: EventType):
        self.type = type


class MoveRequestMessage(Event):
    def __init__(self, type: EventType):
        self.type = type
