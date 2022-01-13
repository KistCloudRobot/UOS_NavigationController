class RobotTask:
    def __init__(self, generator, robot_id):
        self.generator = generator
        self.robot_id = robot_id

    def next(self):
        yield from self.generator

    def is_canceled(self, robot_id):
        return self.robot_id == robot_id
