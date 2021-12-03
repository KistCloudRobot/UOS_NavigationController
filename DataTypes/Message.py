from arbi_agent.model.generalized_list import GeneralizedList


class Message:
    def __init__(self, survive_flag: bool, gl: GeneralizedList):
        self.survive_flag = survive_flag
        self.gl = gl
