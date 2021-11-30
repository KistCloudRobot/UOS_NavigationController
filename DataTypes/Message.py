from enum import Enum


class MessageType(Enum):
    """type for NC messages"""
    MOVE_REQUEST = 1
    COLLIDABLE = 2
    MULTIROBOT_POSE = 3
    DATA_RECEIVED = 4


class Message:
    def __init__(self, job_type: MessageType, gl):
        self.type = job_type
        self.gl = gl
