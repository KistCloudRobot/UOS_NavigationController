import pathlib
import sys
import threading
from datetime import time
from threading import Condition, Thread

from UOS_NavigationController.DataTypes import Robot

sys.path.append("/home/kist/demo/src/Python_mcArbiFramework/")

from arbi_agent.agent.arbi_agent import ArbiAgent
from arbi_agent.ltm.data_source import DataSource

from UOS_NavigationController.DataTypes.MapManagement.MapMOS import MapMOS
from UOS_NavigationController.NavigationControl.NavigationControl import NavigationControl

agent_MAPF = "agent://www.arbi.com/Local/MultiAgentPathFinder"
broker_url = "tcp://172.16.165.171:61313"


class NavigationControllerDataSource(DataSource):
    def __init__(self, broker_url):

        self.broker = broker_url  # broker address
        self.connect(self.broker, "ds://www.arbi.com/Local/NavigationController", 2)  # connect broker

        self.map_file = str(pathlib.Path(
            __file__).parent.parent.resolve()) + "/data/map_cloud.txt"  # load map file (~/data/map_cloud.txt)
        self.MAP = MapMOS(self.map_file)  # interprete map

        self.AMR_IDs = ["AMR_LIFT1", "AMR_LIFT2", "AMR_TOW1", "AMR_TOW2"]  # AMR IDs
        self.AMR_LIFT_IDs = list()  # LIFT IDs
        self.AMR_TOW_IDs = list()  # TOW IDs
        for identifier in self.AMR_IDs:
            if "LIFT" in identifier:
                self.AMR_LIFT_IDs.append(identifier)
            elif "TOW" in identifier:
                self.AMR_TOW_IDs.append(identifier)

        self.NC = NavigationControl(self.AMR_IDs, self.AMR_LIFT_IDs,
                                    self.AMR_TOW_IDs)  # launch NC(NavigationController)


class NavigationControllerAgent(ArbiAgent):
    def __init__(self):
        super().__init__()
        self.ltm = None  # ltm address (to be modified after on_start)
        self.lock = Condition()

        self.CM_name = "agent://www.arbi.com/Local/ContextManager"

        self.TM_name = {"AMR_LIFT1": "agent://www.arbi.com/Lift1/TaskManager",
                        "AMR_LIFT2": "agent://www.arbi.com/Lift2/TaskManager",
                        "AMR_TOW1": "agent://www.arbi.com/Tow1/TaskManager",
                        "AMR_TOW2": "agent://www.arbi.com/Tow2/TaskManager"}  # agent address of robotTaskManager(robotTM)

        self.BI_name = {
            "AMR_LIFT1": "agent://www.arbi.com/Lift1/BehaviorInterface",
            "AMR_LIFT2": "agent://www.arbi.com/Lift2/BehaviorInterface",
            "AMR_TOW1": "agent://www.arbi.com/Tow1/BehaviorInterface",
            "AMR_TOW2": "agent://www.arbi.com/Tow2/BehaviorInterface"
        }  # agent adress of robotBehaviorInterface(robotBI)

        self.SMM_name = "agent://www.arbi.com/Local/MapManager"  # agent address of SemanticMapManager(SMM)

        self.BI_actionID = {
            "AMR_LIFT1": ["\"1\"", "\"5\""],
            "AMR_LIFT2": ["\"2\"", "\"6\""],
            "AMR_TOW1": ["\"3\"", "\"7\""],
            "AMR_TOW2": ["\"4\"", "\"8\""]
        }  # actionID [moveID, cancelID] to send to robotBI

        self.AMR_IDs = ["AMR_LIFT1", "AMR_LIFT2", "AMR_TOW1", "AMR_TOW2"]  # AMR IDs
        self.AMR_LIFT_IDs = list()  # LIFT IDs
        self.AMR_TOW_IDs = list()  # TOW IDs
        for identifier in self.AMR_IDs:
            if "LIFT" in identifier:
                self.AMR_LIFT_IDs.append(identifier)
            elif "TOW" in identifier:
                self.AMR_TOW_IDs.append(identifier)

        self.cur_robot_pose = {}  # current pose of robot (notify from SMM) e.g. {robotID: [vertex, vertex]}
        self.goal_actionID = {}  # actionID from TM(goal request) e.g. {robotID: actionID}

        self.robots = {
            "AMR_LIFT1": Robot.Robot(name="AMR_LIFT1"),
            "AMR_LIFT2": Robot.Robot(name="AMR_LIFT2"),
            "AMR_TOW1": Robot.Robot(name="AMR_TOW1"),
            "AMR_TOW2": Robot.Robot(name="AMR_TOW2")
        }

        self.message_queue = list[Robot.RobotJob]

    def on_start(self):
        self.ltm = NavigationControllerDataSource(broker_url)
        self.ltm.connect(broker_url, "ds://www.arbi.com/Local/NavigationController")
        # Thread(target=self.main_loop, args=(), daemon=True).start()
        self.main_loop()

    def main_loop(self):
        while True:
            message = self.message_queue.pop(0)
            if message.type == "MOVE_REQUEST":
                self.control_request(message)
            elif message.type == "COLLIDABLE":
                self.handle_collidable(message)
            elif message.type == "MULTIROBOT_POSE":
                self.update_multi_robot_pose(message)
            time.sleep(1)
