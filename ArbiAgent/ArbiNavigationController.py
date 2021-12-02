import copy
import pathlib
import sys
import threading
import time
from threading import Condition, Thread

#sys.path.append("/home/kist/demo/src/Python_mcArbiFramework/")
from ..DataTypes.Message import Message, MessageType, MoveRequestMessage

sys.path.append("../../Python_mcArbiFramework")

from Python_mcArbiFramework.arbi_agent.agent.arbi_agent import ArbiAgent
from Python_mcArbiFramework.arbi_agent.model import generalized_list_factory
from Python_mcArbiFramework.arbi_agent.ltm.data_source import DataSource

from ..DataTypes.MapManagement.MapMOS import MapMOS
from ..NavigationControl.NavigationControl import NavigationControl
from ..DataTypes import Robot

agent_MAPF = "agent://www.arbi.com/Local/MultiAgentPathFinder"
broker_url = "tcp://172.16.165.171:61313"


class NavigationControllerDataSource(DataSource):
    def __init__(self, _broker_url):
        super().__init__()
        self.broker = _broker_url  # broker address
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

        self.navigation_controller = NavigationControl(self.AMR_IDs, self.AMR_LIFT_IDs, self.AMR_TOW_IDs)  # launch NC(NavigationController)


class NavigationControllerAgent(ArbiAgent):
    def __init__(self):
        super().__init__()
        self.ltm = None  # ltm address (to be modified after on_start)
        self.navigation_controller = None
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
        self.real_goal = {
            "AMR_LIFT1": -1,
            "AMR_LIFT2": -1,
            "AMR_TOW1": -1,
            "AMR_TOW2": -1
        }
        self.actual_goal = {
            "AMR_LIFT1": -1,
            "AMR_LIFT2": -1,
            "AMR_TOW1": -1,
            "AMR_TOW2": -1
        }
        self.move_flag = {
            "AMR_LIFT1": False,
            "AMR_LIFT2": False,
            "AMR_TOW1": False,
            "AMR_TOW2": False
        }  # identify whether robot is moving
        self.avoid_flag = {
            "AMR_LIFT1": False,
            "AMR_LIFT2": False,
            "AMR_TOW1": False,
            "AMR_TOW2": False
        }  # identify whether robot is in avoiding plan
        self.collide_flag = {
            "AMR_LIFT1": False,
            "AMR_LIFT2": False,
            "AMR_TOW1": False,
            "AMR_TOW2": False
        }  # identify whether robot is in avoiding plan

        self.message_queue = list[Message]
        self.generator_queue = []

    def on_start(self):
        self.ltm = NavigationControllerDataSource(broker_url)
        self.ltm.connect(broker_url, "ds://www.arbi.com/Local/NavigationController")
        self.navigation_controller = self.ltm.navigation_controller
        # Thread(target=self.main_loop, args=(), daemon=True).start()
        self.main_loop()

    def on_notify(self, sender: str, notification: str):
        temp_gl = generalized_list_factory.new_gl_from_gl_string(notification)  # notification to gl
        gl_name = temp_gl.get_name()  # get name of gl
        if gl_name == "MultiRobotPose":
            self.message_queue.append(Message(job_type=MessageType.MULTIROBOT_POSE, gl=notification))
        elif gl_name == "Collidable":
            self.message_queue.append(Message(job_type=MessageType.COLLIDABLE, gl=notification))

    def main_loop(self):
        while True:
            message = self.message_queue.pop(0)
            if message.type == "MOVE_REQUEST":
                self.control_request(message)
            elif message.type == "COLLIDABLE":
                self.handle_collidable(message)
            elif message.type == "MULTIROBOT_POSE":
                self.update_multi_robot_pose(message)
            self.proceed_generators()
            time.sleep(1)

    def control_request(self, robot_id):
        print("[Info] Control request start : " + robot_id)
        self.thread_flag[robot_id] = True
        self.move_flag[robot_id] = True
        # print("111111111111111", self.NC.robotTM_set[robot_id])
        ''' if robot is in stationary state, output from MAPF path is same with current vertex
            e.g. "AMR_TOW1" : in stationary state, no plan to move
                -> self.cur_robot_pose["AMR_TOW1"][0] == self.cur_robot_pose["AMR_TOW1"][1]
                -> len(self.NC.robotTM[robot_id][0]) == 1
            => no control is needed '''

        ''' self.NC.robotTM[robotID]: current path of robotID '''

        while self.thread_flag[robot_id]:
            print("waiting path")
            time.sleep(0.1)
            if self.navigation_controller.robotTM[robot_id]:
                print("got path")
                print(" robot_id " + str(robot_id))
                print(" ROBOT_TM " + str(self.navigation_controller.robotTM[robot_id]))
                break
            else:
                yield

        if self.thread_flag[robot_id]:
            if len(self.navigation_controller.robotTM[robot_id]) == 1:  # check whether robot is stationary
                stationary_check = (self.cur_robot_pose[robot_id][0] == self.cur_robot_pose[robot_id][1]) and (
                            self.actual_goal[robot_id] == -1)  # True if robot is stationary and will be stationary
            else:
                stationary_check = False

            if self.navigation_controller.robotTM[robot_id] and not stationary_check:  # check whether robot has path and not stationary
                ''' if robot is avoiding against counterpart robot, path of the robot is split
                    e.g. self.NC.robotTM_set[avoidingRobotID] == [[path], [path]]
                         self.NC.robotTM_set[counterpartRobotID] == [[path]] '''

                if len(self.navigation_controller.robotTM_set[robot_id]) == 1:  # not split path (not avoiding path)
                    ### Cancel current control request if robot is moving ###
                    # if self.move_flag[robot_id]:  # check whether robot is moving
                    #     ''' If robot is moving now, current path should be canceled.
                    #         Cancel actionID:
                    #             "AMR_LIFT1": "\"5\""
                    #             "AMR_LIFT2": "\"6\""
                    #             "AMR_TOW1": "\"7\""
                    #             "AMR_TOW2": "\"8\""
                    #         cancelMove gl format: (cancelMove (actionID $actionID)) '''

                    #     while True:
                    #         temp_Cancel_gl = "(cancelMove (actionID {actionID}))"
                    #         Cancel_gl = temp_Cancel_gl.format(actionID=self.BI_actionID[robot_id][1])  # Cancel actionID
                    #         self.move_flag[robot_id] = False  # update moving state of robot
                    #         print(c + "[Request CancelMove1]\t{RobotID}".format(RobotID=robot_id))
                    #         cancel_response = self.request(self.BI_name[robot_id], Cancel_gl)  # get response of Cancel request
                    #         cancel_response_gl = GLFactory.new_gl_from_gl_string(cancel_response)
                    #         if cancel_response_gl.get_name() == "fail":
                    #             print(c + "[Response CancelMove1]\t{RobotID}: FAIL".format(RobotID=robot_id))
                    #             time.sleep(1)
                    #             continue
                    #         else:
                    #             result = cancel_response_gl.get_expression(1).as_value().string_value()  # "success" if Cancel request is done
                    #             print(c + "[Response CancelMove1]\t{RobotID}: {Result}".format(RobotID=robot_id, Result=result))
                    #             time.sleep(0.5)
                    #             break

                    ### Control Request to move ###
                    ''' Move actionID:
                            "AMR_LIFT1": "\"1\""
                            "AMR_LIFT2": "\"2\""
                            "AMR_TOW1": "\"3\""
                            "AMR_TOW2": "\"4\""
                        move gl format: (move (actionID $actionID) $path) '''

                    self.move_flag[robot_id] = True  # update moving state of robot
                    while self.thread_flag[robot_id]:
                        time.sleep(1)
                        # print("[INFO] {RobotID} is waiting for Path Update".format(RobotID=robot_id))
                        if self.navigation_controller.robotTM[robot_id]:
                            robot_path = copy.copy(self.navigation_controller.robotTM[robot_id])
                            # print("[INFO] {RobotID} got new path".format(RobotID=robot_id))
                            break

                    if self.thread_flag[robot_id]:
                        temp_Move_gl = "(move (actionID {actionID}) {path})"
                        path_gl = self.path_gl_generator(robot_path, robot_id)  # convert path list to path gl
                        Move_gl = temp_Move_gl.format(actionID=self.BI_actionID[robot_id][0], path=path_gl)

                        self.SMM_notify(robot_id)
                        while self.thread_flag[robot_id]:
                            print("[Request Move1]\t\t{RobotID}\t{Path}".format(RobotID=robot_id, Path=str(path_gl)))
                            self.move_flag[robot_id] = True
                            move_response = self.request(self.BI_name[robot_id],
                                                         Move_gl)  # request move control to robotBI, get response of request
                            print("[response Move1]\t\t{RobotID}\t{response}".format(RobotID=robot_id, response=str(move_response)))
                            move_response_gl = generalized_list_factory.new_gl_from_gl_string(move_response)
                            if move_response_gl.get_name() == "fail":
                                time.sleep(1)
                            else:
                                result = move_response_gl.get_expression(
                                    1).as_value().string_value()  # "success" if request is done, "(fail)"" if request can't be handled
                                print("[response Move1]\t\t{RobotID}\t{Path}: {Result}".format(RobotID=robot_id, Path=str(path_gl), Result=str(result)))
                                break

                elif len(self.navigation_controller.robotTM_set[robot_id]) >= 2:  # split path (avoiding path)
                    self.avoid_flag[robot_id] = True  # update avoiding state of robot
                    counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
                    robot_index = self.AMR_IDs.index(robot_id)
                    c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
                    self.avoid_flag[c_robot_id] = True

                    robotTM_set = copy.copy(self.navigation_controller.robotTM_set)  # get path set
                    robotTM_scond = copy.copy(self.navigation_controller.robotTM_scond)  # get start condition of robot
                    ''' self.NC.robotTM_scond: start condition of split path
                        e.g. AMR_LIFT1 is avoiding robot and AMR_LIFT2 is counterpart robot
                             self.NC.robotTM_set["AMR_LIFT1"] == [[1, 2, 3], [4, 5, 6, 7]]
                             self.NC.robotTM_set["AMR_LIFT2"] == [4, 5, 6, 7, 8, 9]
                             self.NC.robotTM_scond["AMR_LIFT1"] == [[], [["AMR_LIFT2", [0, 1]]]]

                        self.NC.robotTM_scond["AMR_LIFT1"]: start condition of "AMR_LIFT1"(avoidingRobot)
                        -> no condition of 0th path
                        -> [["AMR_LIFT2", [0, 1]]] condition of 1th path which means start after "AMR_LIFT2" passes 1th element(5) in 0th path([4, 5, 6, 7, 8, 9]) '''

                    ### Cancel current control request if robot is moving ###
                    # if self.move_flag[robot_id]:  # check whether robot is moving
                    #     while True:
                    #         temp_Cancel_gl = "(cancelMove (actionID {actionID}))"
                    #         Cancel_gl = temp_Cancel_gl.format(actionID=self.BI_actionID[robot_id][1])  # Cancel actionID
                    #         self.move_flag[robot_id] = False  # update moving state of robot
                    #         print(c + "[Request CancelMove2]\t{RobotID}".format(RobotID=robot_id))
                    #         cancel_response = self.request(self.BI_name[robot_id], Cancel_gl)  # get response of Cancel request
                    #         cancel_response_gl = GLFactory.new_gl_from_gl_string(cancel_response)
                    #         if cancel_response_gl.get_name() == "fail":
                    #             print(c + "[Response CancelMove2]\t{RobotID}: FAIL".format(RobotID=robot_id))
                    #             time.sleep(1)
                    #             continue
                    #         else:
                    #             result = cancel_response_gl.get_expression(1).as_value().string_value()  # "success" if Cancel request is done
                    #             print(c + "[Response CancelMove2]\t{RobotID}: {Result}".format(RobotID=robot_id, Result=result))
                    #             time.sleep(0.5)
                    #             break

                    ### Control request to move ###
                    for path_idx in range(len(robotTM_set[robot_id])):  # consider path set
                        if robotTM_scond[robot_id][path_idx]:  # check whether current path has any start condition
                            wait_flag = True
                            while wait_flag and self.thread_flag[robot_id]:
                                time.sleep(1)
                                for cond in robotTM_scond[robot_id][path_idx]:
                                    if self.navigation_controller.PlanExecutedIdx[cond[0]][0] < cond[1][0] or \
                                            self.navigation_controller.PlanExecutedIdx[cond[0]][1] < cond[1][1]:
                                        wait_flag = True
                                    else:
                                        wait_flag = False
                                        # print("[INFO] Start Condition of {RobotID} is Satisfied".format(RobotID=robot_id))
                                        break

                        ''' Move actionID:
                                "AMR_LIFT1": "\"1\""
                                "AMR_LIFT2": "\"2\""
                                "AMR_TOW1": "\"3\""
                                "AMR_TOW2": "\"4\""
                            move gl format: (move (actionID $actionID) $path) '''
                        self.move_flag[robot_id] = True  # update moving state of robot
                        while self.thread_flag[robot_id]:
                            time.sleep(1)
                            # print("[INFO] {RobotID} is waiting for Path Update".format(RobotID=robot_id))
                            if self.navigation_controller.robotTM[robot_id]:
                                robot_path = robotTM_set[robot_id][path_idx]  # get current path of path set
                                # print("[INFO] {RobotID} got new path".format(RobotID=robot_id))
                                break

                        if self.thread_flag[robot_id]:
                            temp_Move_gl = "(move (actionID {actionID}) {path})"
                            path_gl = self.path_gl_generator(robot_path, robot_id)  # convert path list to path gl
                            Move_gl = temp_Move_gl.format(actionID=self.BI_actionID[robot_id][0], path=path_gl)
                            self.SMM_notify(robot_id)

                            while self.thread_flag[robot_id]:
                                print("[Request Move2]\t\t{RobotID}\t{Path}".format(RobotID=robot_id, Path=str(path_gl)))
                                self.move_flag[robot_id] = True
                                move_response = self.request(self.BI_name[robot_id],
                                                             Move_gl)  # request move control to robotBI, get response of request
                                print("[response Move2]\t\t{RobotID}\t{response}".format(RobotID=robot_id, response=str(move_response)))
                                move_response_gl = generalized_list_factory.new_gl_from_gl_string(move_response)
                                if move_response_gl.get_name() == "fail":
                                    time.sleep(1)
                                else:
                                    result = move_response_gl.get_expression(
                                        1).as_value().string_value()  # "success" if request is done, "(fail)"" if request can't be handled
                                    print("[Response Move2]\t\t{RobotID}\t{Path}: {Result}".format(RobotID=robot_id ,Path=str(path_gl), Result=str(result)))
                                    break
                    self.avoid_flag[robot_id] = False  # update avoiding state of robot
                    self.avoid_flag[c_robot_id] = False  # update avoiding state of robot

            # if collide and self.thread_flag[robot_id]:
            #     self.collide_flag[robot_id] = False
            #     counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
            #     robot_index = self.AMR_IDs.index(robot_id)
            #     c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
            #     self.collide_flag[c_robot_id] = False
        self.thread_flag[robot_id] = False
        with self.lock[robot_id]:
            self.lock[robot_id].notify()
        print("[Info] Control request finish " + str(robot_id))

    def handle_collidable(self, message):
        self.update_collidable(message)

    def notify_robot_path_plan(self, robot_id):  # notify SMM of control information
        ''' RobotPathPlan gl format: (RobotPathPlan $robot_id $goal (path $v_id1 $v_id2 ….)) '''
        if self.navigation_controller.robotTM[robot_id]:
            temp_SMM_gl = "(RobotPathPlan \"{robot_id}\" {goal} {path})"
            robot_path = copy.copy(self.navigation_controller.robotTM[robot_id])
            path_gl = self.path_gl_generator(robot_path, robot_id)  # convert path list to path gl
            SMM_gl = temp_SMM_gl.format(robot_id=robot_id, goal=self.actual_goal[robot_id], path=path_gl)
            # print("[Notify] Notify Path and Goal of {RobotID} to SMM".format(RobotID=robot_id))
            self.notify(self.SMM_name, SMM_gl)  # notify SMM
        else:
            # print("[INFO] {RobotID} has no path".format(RobotID=robot_id))
            pass

    def path_gl_generator(self, path, robot_id):  # convert path list to path gl
        ''' path gl format: (path $v_id1 $v_id2 ….) '''

        if path[0] != self.cur_robot_pose[robot_id][0]:
            path.insert(0, self.cur_robot_pose[robot_id][0])
        path_gl = "(path"
        for path_i in path:
            path_gl += " "
            path_gl += str(path_i)
        path_gl += ")"

        return path_gl

    def update_collidable(self, message):
        ''' Collidable gl format: (Collidable $num (pair $robot_id $robot_id $time), …)
                                            num: number of collidable set
                                            time: in which collision is expected '''
        temp_gl = generalized_list_factory.new_gl_from_gl_string(message)
        collide_num = temp_gl.get_expression(0).as_value().int_value()  # get number of collidable set
        for i in range(collide_num):
            ''' collidable_set(pair) gl format: (pair $robot_id $robot_id $time) '''

            collidable_set_gl = temp_gl.get_expression(i + 1).as_generalized_list()  # get ith collidable set
            robot_ids = [collidable_set_gl.get_expression(0).as_value().string_value(),
                         collidable_set_gl.get_expression(
                             1).as_value().string_value()]  # get robotIDs of collidable set
            check = 0  # check if the robots are already in collidable triggered plan
            for robot_id in robot_ids:
                check += self.collide_flag[robot_id]
            if check == 0:
                for robot_id in robot_ids:
                    self.collide_flag[robot_id] = True
                    print("[INFO] {RobotID} cancel move by collidable".format(RobotID=robot_id))
                    self.cancel_move(robot_id)
                for robot_id in robot_ids:
                    # self.collide_flag[robot_id] = True
                    # print("[INFO] {RobotID} cancel move by collidable".format(RobotID=robot_id))
                    # self.cancel_move(robot_id)
                    if self.thread_flag[robot_id]:
                        self.thread_flag[robot_id] = False
                        with self.lock[robot_id]:
                            self.lock[robot_id].wait()

                self.navigation_controller.update_start_goal_collision(robot_ids)  # update collidable robotIDs in NC

                path_response = self.query_multi_robot_path(robot_ids)  # query about not collidable path to MultiAgentPathFinder(MAPF)
                path_response_gl = generalized_list_factory.new_gl_from_gl_string(path_response)
                ''' path_response gl format: (MultiRobotPath (RobotPath $robot_id (path $v_id1 $v_id2 $v_id3, ...)), …) '''

                robot_ids = self.update_multi_robot_path(path_response_gl)  # update path of robot in NC
                print("4Thread create by collidable : " + str(robot_ids))
                for robot_id in robot_ids:
                    self.notify_robot_path_plan(robot_id)  # # notify SMM of same control information
                    # print("[INFO] {RobotID} cancel move".format(RobotID=robot_id))
                    # self.cancel_move(robot_id)
                    # print("[INFO] {RobotID} Control request by <COLLIDABLE> Notification [{num}]".format(RobotID=robot_id, num=self.count))
                    # Thread(target=self.Control_request, args=(robot_id, True, False, self.count), daemon=True).start()
                    self.generator_queue.append(self.control_request(robot_id, True, False))
                    if self.navigation_controller.robotTM[robot_id]:
                        print("[INFO] {RobotID} Control request by <COLLIDABLE> Notification [{num}]".format(RobotID=robot_id, num=self.count))
                        # Thread(target=self.Control_request, args=(robot_id, True, False, self.count),daemon=True).start()  # control request of robotID
                    else:
                        self.move_flag[robot_id] = True

    def update_multi_robot_path(self, response_gl):  # update paths of robots in NC
        ''' MultiRobotPath gl format: (MultiRobotPath (RobotPath $robot_id (path $v_id1 $v_id2 $v_id3, ...)), …) '''
        print('multi robot path update : ' + str(response_gl))
        multipaths = dict()  # {robotoID: path}
        robot_num = response_gl.get_expression_size()  # get number of robots
        robot_pose = {}  # {robotID: [vertex, vertex]}
        robot_ids = []
        for i in range(robot_num):
            ''' RobotPath gl format: (RobotPath $robot_id (path $v_id1 $v_id2 $v_id3, ...)) '''
            robot_info = response_gl.get_expression(i).as_generalized_list()  # get RobotPath information from gl
            robot_id = robot_info.get_expression(0).as_value().string_value()  # get robotID
            robot_ids.append(robot_id)
            path_gl = robot_info.get_expression(1).as_generalized_list()  # get path
            path_size = path_gl.get_expression_size()  # get path size
            path_size -= 1
            path = list()

            if path_size > 0:
                for j in range(path_size):
                    path.append(path_gl.get_expression(j).as_value().int_value())  # generate path list
            multipaths[robot_id] = path
            robot_pose[robot_id] = copy.copy(self.cur_robot_pose[robot_id])  # get current pose of robot
            print('robot ID : ' + str(robot_id))
            print('path : ' + str(path))

        # print("before multipath plan")
        self.navigation_controller.get_multipath_plan(multipaths)  # update path in NC
        # print("after multipath plan")
        self.navigation_controller.update_robot_TM(robot_pose)  # update pose in NC

        return robot_ids

    def query_multi_robot_path(self, robot_id_replan):  # query about path to MultiAgentPathFinder(MAPF)
        ''' MultiRobotPath gl format: (MultiRobotPath (RobotPath $robot_id $cur_vertex $goal_id), …) '''

        path_query_gl = "(MultiRobotPath"
        for robot_id in robot_id_replan:
            # start_id = copy.deepcopy(self.cur_robot_pose[robot_id][0])  # get current nearest vertext to set start vertex
            # start_id = copy.copy(self.cur_robot_pose[robot_id][0])  # get current nearest vertext to set start vertex
            start_id = self.cur_robot_pose[robot_id][0]
            # goal_id = copy.deepcopy(self.NC.robotGoal[robot_id]) # get current goal
            # goal_id = copy.deepcopy(self.real_goal[robot_id])
            goal_id = copy.copy(self.real_goal[robot_id])
            if goal_id == -1:  # check whether robot has no goal
                goal_id = start_id  # no gal -> start==goal
            path_query_gl += " (RobotPath \"" + robot_id + "\" " + str(start_id) + " " + str(goal_id) + ")"

            ''' MultiRobotPath querh should have all of robots in same type
                e.g. TOW1/TOW2 or LIFT1/LIFT2 '''

            if len(robot_id_replan) == 1:  # check wheather robot_id_replan(argument) has one ID
                ''' if only has
                        LIFT1 -> add LIFT2
                        LIFT2 -> add LIFT1
                        TOW1 -> add TOW2
                        TOW2 -> add TOW1 '''

                counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
                robot_index = self.AMR_IDs.index(robot_id)
                c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
                # c_start_id = copy.deepcopy(self.cur_robot_pose[c_robot_id][0])  # get current nearest vertext
                # c_goal_id = copy.deepcopy(self.real_goal[c_robot_id])  # get current goal
                c_start_id = copy.copy(self.cur_robot_pose[c_robot_id][0])  # get current nearest vertext
                c_goal_id = copy.copy(self.real_goal[c_robot_id])  # get current goal
                if c_goal_id == -1:  # check whether robot has no goal
                    c_goal_id = c_start_id  # no gal -> start==goal
                path_query_gl += " (RobotPath \"" + c_robot_id + "\" " + str(c_start_id) + " " + str(c_goal_id) + ")"

        path_query_gl += ")"

        time.sleep(0.05)
        print("[Query] Query Robot Path to MAPF :", path_query_gl)
        path_response = self.query(agent_MAPF, path_query_gl)
        print("[Query] Response from MAPF :", path_response)

        return path_response

    def update_multi_robot_pose(self,message):
        temp_gl = generalized_list_factory.new_gl_from_gl_string(message)
        robot_num = temp_gl.get_expression_size()  # check updated number of robots
        multi_robot_pose = {}  # {robotID: [vertex, vertex]}

        for i in range(robot_num):  # update robot pose from gl
            '''robot_pose_gl format: (RobotPose $robot_id (vertex $vertex_id $vertex_id))'''

            robot_pose_gl = temp_gl.get_expression(i).as_generalized_list()  # get ith gl content
            robot_id = robot_pose_gl.get_expression(0).as_value().string_value()  # get robotID
            robot_vertex_gl = robot_pose_gl.get_expression(1).as_generalized_list()  # get current vertex
            robot_vertex = [robot_vertex_gl.get_expression(0).as_value().int_value(),
                            robot_vertex_gl.get_expression(1).as_value().int_value()]  # current pose to list
            multi_robot_pose[robot_id] = robot_vertex
            self.cur_robot_pose[robot_id] = robot_vertex  # update current robot pose in agent

        changed_robot_list = self.navigation_controller.update_robot_TM(multi_robot_pose)  # update robot pose in NC
        ''' robot_sendTM: robotID that has any change of its path and notify the information of robotID to robotBI '''

        if changed_robot_list:  # check whether changed_robot_list is empty
            print("3Thread create by MultiRobotPose num : " + str(len(changed_robot_list)))
            for robot_id in changed_robot_list:
                self.notify_robot_path_plan(robot_id)  # # notify SMM of same control information
                # if not self.avoid_flag[robot_id]:
                if (not self.avoid_flag[robot_id]) and (not self.move_flag[robot_id]):
                    print("[INFO] {RobotID} cancel move".format(RobotID=robot_id))
                    self.cancel_move(robot_id)

                    print(
                        "[INFO] {RobotID} Control request by <COLLIDABLE> Notification".format(RobotID=robot_id))
                    # Thread(target=self.Control_request, args=(robot_id, True, False, self.count), daemon=True).start()
                    self.generator_queue.append(self.control_request(robot_id, True, False))

    def cancel_move(self, robot_id):
        if len(self.navigation_controller.robotTM[robot_id]) == 1:  # check whether robot is stationary
            print("[" + str(robot_id) + "]" + str(self.cur_robot_pose[robot_id][0]))
            print("[" + str(robot_id) + "]" + str(self.cur_robot_pose[robot_id][1]))
            stationary_check = (self.cur_robot_pose[robot_id][0] == self.cur_robot_pose[robot_id][1] ==
                                self.navigation_controller.robotTM[robot_id][0])  # True if robot is stationary and will be stationary
        else:
            stationary_check = False

        print("[" + str(robot_id) + "]" + str(self.navigation_controller.robotTM[robot_id]))
        print("[" + str(robot_id) + "]" + str(stationary_check))
        print("[" + str(robot_id) + "]" + str(self.navigation_controller.robotTM_set[robot_id]))
        print("[" + str(robot_id) + "]" + str(len(self.navigation_controller.robotTM_set[robot_id])))
        if self.navigation_controller.robotTM[robot_id] and (not stationary_check):  # check whether robot has path and not stationary
            ''' if robot is avoiding against counterpart robot, path of the robot is split
                e.g. self.NC.robotTM_set[avoidingRobotID] == [[path], [path]]
                     self.NC.robotTM_set[counterpartRobotID] == [[path]] '''

            if len(self.navigation_controller.robotTM_set[robot_id]) == 1:  # not split path (not avoiding path)
                ### Cancel current control request if robot is moving ###
                if self.move_flag[robot_id]:  # check whether robot is moving
                    ''' If robot is moving now, current path should be canceled.
                        Cancel actionID:
                            "AMR_LIFT1": "\"5\""
                            "AMR_LIFT2": "\"6\""
                            "AMR_TOW1": "\"7\""
                            "AMR_TOW2": "\"8\""
                        cancelMove gl format: (cancelMove (actionID $actionID)) '''

                    temp_Cancel_gl = "(cancelMove (actionID {actionID}))"
                    Cancel_gl = temp_Cancel_gl.format(actionID=self.BI_actionID[robot_id][1])  # Cancel actionID
                    self.move_flag[robot_id] = False  # update moving state of robot
                    print("[Request CancelMove1]\t{RobotID}".format(RobotID=robot_id))
                    cancel_response = self.request(self.BI_name[robot_id],
                                                   Cancel_gl)  # get response of Cancel request
                    cancel_response_gl = generalized_list_factory.new_gl_from_gl_string(cancel_response)
                    if cancel_response_gl.get_name() == "fail":
                        print("[Response CancelMove1]\t{RobotID}: FAIL".format(RobotID=robot_id))
                    else:
                        result = cancel_response_gl.get_expression(
                            1).as_value().string_value()  # "success" if Cancel request is done
                        print("[Response CancelMove1]\t{RobotID}: {Result}".format(RobotID=robot_id, Result=result))
            elif len(self.navigation_controller.robotTM_set[robot_id]) >= 2:  # split path (avoiding path)
                self.avoid_flag[robot_id] = True  # update avoiding state of robot
                counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
                robot_index = self.AMR_IDs.index(robot_id)
                c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
                self.avoid_flag[c_robot_id] = True

                ''' self.NC.robotTM_scond: start condition of split path
                    e.g. AMR_LIFT1 is avoiding robot and AMR_LIFT2 is counterpart robot
                         self.NC.robotTM_set["AMR_LIFT1"] == [[1, 2, 3], [4, 5, 6, 7]]
                         self.NC.robotTM_set["AMR_LIFT2"] == [4, 5, 6, 7, 8, 9]
                         self.NC.robotTM_scond["AMR_LIFT1"] == [[], [["AMR_LIFT2", [0, 1]]]]

                    self.NC.robotTM_scond["AMR_LIFT1"]: start condition of "AMR_LIFT1"(avoidingRobot)
                    -> no condition of 0th path
                    -> [["AMR_LIFT2", [0, 1]]] condition of 1th path which means start after "AMR_LIFT2" passes 1th element(5) in 0th path([4, 5, 6, 7, 8, 9]) '''

                ### Cancel current control request if robot is moving ###
                if self.move_flag[robot_id]:  # check whether robot is moving
                    temp_Cancel_gl = "(cancelMove (actionID {actionID}))"
                    Cancel_gl = temp_Cancel_gl.format(actionID=self.BI_actionID[robot_id][1])  # Cancel actionID
                    self.move_flag[robot_id] = False  # update moving state of robot
                    print("[Request CancelMove2]\t{RobotID}".format(RobotID=robot_id))
                    cancel_response = self.request(self.BI_name[robot_id],
                                                   Cancel_gl)  # get response of Cancel request
                    cancel_response_gl = generalized_list_factory.new_gl_from_gl_string(cancel_response)
                    if cancel_response_gl.get_name() == "fail":
                        print("[Response CancelMove2]\t{RobotID}: FAIL".format(RobotID=robot_id))
                    else:
                        result = cancel_response_gl.get_expression(1).as_value().string_value()  # "success" if Cancel request is done
                        print("[Response CancelMove2]\t{RobotID}: {Result}".format(RobotID=robot_id, Result=result))

    def proceed_generators(self):
        clean_list = []
        for generator in self.generator_queue:
            try:
                next(generator)
                clean_list.append(generator)
            except StopIteration:
                pass
        self.generator_queue = clean_list

