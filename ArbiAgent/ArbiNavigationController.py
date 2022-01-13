import time
import pathlib
import copy
import uuid
from threading import Thread
from typing import List
import sys

sys.path.append("/home/kist/demo/src/Python_mcArbiFramework/")
sys.path.append(str(pathlib.Path(__file__).parent.parent.resolve()))

from UOS_NavigationController.DataTypes.Message import Message
from UOS_NavigationController.DataTypes.RobotTask import RobotTask

from arbi_agent.agent.arbi_agent import ArbiAgent
from arbi_agent.ltm.data_source import DataSource
from arbi_agent.agent import arbi_agent_executor
from arbi_agent.model import generalized_list_factory as GLFactory

from UOS_NavigationController.MapManagement.MapMOS import MapMOS
from UOS_NavigationController.NavigationControl.NavigationControl import NavigationControl

agent_mapf_uri = "agent://www.arbi.com/Local/MultiAgentPathFinder"
broker_url = "tcp://192.168.0.2:61313"


# broker_url = 'tcp://' + os.environ["JMS_BROKER"]

class NavigationControllerDataSource(DataSource):
    def __init__(self, broker_url):

        self.broker = broker_url  # broker address
        self.connect(self.broker, "ds://www.arbi.com/Local/NavigationController", 2)  # connect broker

        self.map_file = str(pathlib.Path(
            __file__).parent.parent.resolve()) + "/data/map_cloud.txt"  # load map file (~/data/map_cloud.txt)
        self.MAP = MapMOS(self.map_file)  # interpret map

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
        self.navigation_controller: NavigationControl = None

        self.context_manager_uri = "agent://www.arbi.com/Local/ContextManager"

        self.task_manager_uri = {"AMR_LIFT1": "agent://www.arbi.com/Lift1/TaskManager",
                                 "AMR_LIFT2": "agent://www.arbi.com/Lift2/TaskManager",
                                 "AMR_TOW1": "agent://www.arbi.com/Tow1/TaskManager",
                                 "AMR_TOW2": "agent://www.arbi.com/Tow2/TaskManager"}  # agent address of robotTaskManager(robotTM)

        self.behavior_interface_uri = {
            "AMR_LIFT1": "agent://www.arbi.com/Lift1/BehaviorInterface",
            "AMR_LIFT2": "agent://www.arbi.com/Lift2/BehaviorInterface",
            "AMR_TOW1": "agent://www.arbi.com/Tow1/BehaviorInterface",
            "AMR_TOW2": "agent://www.arbi.com/Tow2/BehaviorInterface"
        }  # agent adress of robotBehaviorInterface(robotBI)

        self.SMM_name = "agent://www.arbi.com/Local/MapManager"  # agent address of SemanticMapManager(SMM)

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

        self.count = 0
        self.generator_queue = []
        self.preserved_queue = []
        self.canceled_robot_id = []
        self.data_received: List[Message] = []

    def on_start(self):  # executed when the agent initializes
        self.ltm = NavigationControllerDataSource(broker_url)  # ltm class
        self.ltm.connect(broker_url, "ds://www.arbi.com/Local/NavigationController", 2)  # connect ltm
        self.navigation_controller = self.ltm.NC

        self.main_loop()

    def main_loop(self):
        cleanse_list_gen = self.cleanse_list()
        while True:
            clean_generator_queue = []
            for task in self.generator_queue:
                try:
                    generator = task.generator
                    robot_id = task.robot_id
                    if robot_id in self.canceled_robot_id:
                        pass
                    else:
                        # print(generator)
                        next(generator)
                        clean_generator_queue.append(task)
                except StopIteration:
                    print("jobs done. generator removed?")
                    pass

            self.generator_queue = clean_generator_queue

            self.clear_generator_queue()

            self.preserved_queue = []
            self.canceled_robot_id = []

            # self.check_current_location()

            next(cleanse_list_gen)
            time.sleep(0.1)

    def clear_generator_queue(self):
        clean_generator_queue = []
        for task in self.generator_queue:
            if task.robot_id in self.canceled_robot_id:
                print("jobs canceled by canceledmove " + str(task.robot_id))
            else:
                clean_generator_queue.append(task)
        clean_generator_queue += self.preserved_queue
        self.generator_queue = clean_generator_queue

    def request(self, receiver: str, request: str) -> str:
        print("we sent request : " + request)
        return self.message_toolkit.request(receiver, request)

    def send(self, receiver: str, data: str):
        print("we sent data : " + data)
        return self.message_toolkit.send(receiver, data)

    def on_data(self, sender: str, data: str):
        self.data_received.append(Message(False, GLFactory.new_gl_from_gl_string(data)))
        print("we've got data : " + data)

    def on_notify(self, sender, notification):  # executed when the agent gets notification
        # print("[on Notify] " + notification)
        temp_gl = GLFactory.new_gl_from_gl_string(notification)  # notification to gl
        gl_name = temp_gl.get_name()  # get name of gl

        if gl_name == "MultiRobotPose":  # "MultiRobotPose" update from SMM
            ''' MultiRobotPose gl format: (MultiRobotPose (RobotPose $robot_id (vertex $vertex_id $vertex_id)), ...) '''

            self.update_multi_robot_pose(temp_gl)

        elif gl_name == "Collidable":  # "Collidable" update from SMM
            ''' Collidable gl format: (Collidable $num (pair $robot_id $robot_id $time), …) 
                                    num: number of collidable set
                                    time: in which collision is expected '''
            print('[ON NOTIFY] COLLIDABLE!!!!!!!! ' + str(notification))
            self.update_collidable(temp_gl)

    def update_collidable(self, temp_gl):
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
                    self.generator_queue.append(RobotTask(self.cancel_move(robot_id), "cancel_move"))

                self.navigation_controller.update_start_goal_collision(
                    robot_ids)  # update collidable robotIDs in NC

                path_response = self.multi_robot_path_query(
                    robot_ids)  # query about not collidable path to MultiAgentPathFinder(MAPF)
                time.sleep(0.5)
                path_response_gl = GLFactory.new_gl_from_gl_string(path_response)
                ''' path_response gl format: (MultiRobotPath (RobotPath $robot_id (path $v_id1 $v_id2 $v_id3, ...)), …) '''

                robot_ids = self.multi_robot_path_update(path_response_gl)  # update path of robot in NC
                print("4Thread create by collidable : " + str(robot_ids))
                for robot_id in robot_ids:
                    self.semantic_map_manager_notify(robot_id)  # # notify SMM of same control information
                    # print("[INFO] {RobotID} cancel move".format(RobotID=robot_id))
                    # self.cancel_move(robot_id)
                    # print("[INFO] {RobotID} Control request by <COLLIDABLE> Notification [{num}]".format(RobotID=robot_id, num=self.count))
                    # Thread(target=self.Control_request, args=(robot_id, True, False, self.count), daemon=True).start()
                    self.count = self.count + 1
                    if self.navigation_controller.current_command[robot_id]:
                        print("[INFO] {RobotID} Control request by <COLLIDABLE> Notification [{num}]".format(
                            RobotID=robot_id, num=self.count))
                        # Thread(target=self.Control_request, args=(robot_id, True, False, self.count), daemon=True).start()  # control request of robotID
                        self.generator_queue.append(RobotTask(self.control_request(robot_id, True, False, self.count), robot_id))
                    else:
                        self.move_flag[robot_id] = True

    def update_multi_robot_pose(self, temp_gl):
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
            
        robot_id_BI = self.navigation_controller.update_robot_TM(multi_robot_pose)  # update robot pose in NC
        ''' robot_sendTM: robotID that has any change of its path and notify the information of robotID to robotBI '''
        if robot_id_BI:  # check whether robot_id_BI is empty
            for robot_id in robot_id_BI:
                self.semantic_map_manager_notify(robot_id)  # # notify SMM of same control information
                # if (not self.avoid_flag[robot_id]) and (not self.move_flag[robot_id]):
                if not self.avoid_flag[robot_id]:
                    print("[INFO] {RobotID} cancel move".format(RobotID=robot_id))
                    self.generator_queue.append(RobotTask(self.cancel_move(robot_id), "cancel_move"))
                    print("[INFO] {RobotID} Control request by <COLLIDABLE> Notification [{num}]".format(
                        RobotID=robot_id, num=self.count))
                    self.preserved_queue.append(RobotTask(self.control_request(robot_id, True, False, self.count)))

                    self.count = self.count + 1

    def on_request(self, sender, request):  # executed when the agent gets request
        print("[on Request] " + request + sender)
        temp_gl = GLFactory.new_gl_from_gl_string(request)
        print("[on Request] " + temp_gl.get_name())
        if temp_gl.get_name() == "Move":  # "Move" request from robotTM
            ''' Move gl format: (Move (actionID $actionID) $robotID $start $end)
                                start: start vertex
                                end: end(goal) vertex '''

            robot_goal = {}  # {robotID: goalVertex}
            action_id = temp_gl.get_expression(0).as_generalized_list().get_expression(
                0).as_value().string_value()  # get actionID
            robot_id = temp_gl.get_expression(1).as_value().string_value()  # get robotID
            requested_robot_id = robot_id
            self.goal_actionID[robot_id] = action_id  # update actionID in agent
            temp_start = temp_gl.get_expression(2).as_value().int_value()
            real_goal = temp_gl.get_expression(3).as_value().int_value()  # get goalVertex
            self.real_goal[robot_id] = real_goal

            # actual_goal_gl = "(context (NavigationVertex {realGoal} $vertex))".format(realGoal=real_goal)
            # actual_goal_response = self.query(self.context_manager_uri, actual_goal_gl)
            # actual_goal_response_gl = GLFactory.new_gl_from_gl_string(actual_goal_response)
            # actual_goal = actual_goal_response_gl.get_expression(0).as_generalized_list().get_expression(
            #     1).as_value().int_value()
            # print("[{action_id}] actual goal : {actual_goal}".format(action_id=action_id, actual_goal=actual_goal))
            # self.actual_goal[robot_id] = actual_goal

            # robot_goal[robot_id] = actual_goal  # robotID-goalVertex pair
            robot_goal[robot_id] = real_goal
            _robot_id_replan, _robot_id_BI = self.navigation_controller.allocate_goal(robot_goal,
                                                                                    self.cur_robot_pose)  # allocate goal in NC
            robot_id_replan = copy.copy(_robot_id_replan)
            robot_id_BI = copy.copy(_robot_id_BI)
            ''' robot_id_replan: robot which needs to get replanning -> MAPF
                robot_id_BI: robotID that has any change of its path and notify the information of robotID to robotBI '''

            self.generator_queue.append(RobotTask(self.queue_requested_action(action_id, real_goal, robot_id_BI, robot_id_replan), robot_id))

            goal_request_result = "(ok)"  # response to robotTM that request is successful
            print("[{action_id}][on Request6] Response of request of {RobotID}: {Result}".format(action_id=action_id,
                                                                                                 RobotID=requested_robot_id,
                                                                                                 Result=goal_request_result))

            return goal_request_result
        
        elif temp_gl.get_name() == "GuideMove":
            ''' (GuideMove (actionID $actionID) $robotID $vertex $direction) '''
            print("[GuideMove] start GuideMove")
            action_id_gl = temp_gl.get_expression(0).as_generalized_list()
            print("[GuideMove] action ID GL" + str(action_id_gl))
            action_id = action_id_gl.get_expression(0).as_value().string_value()
            print("[GuideMove] action ID " + str(action_id))
            robot_id = temp_gl.get_expression(1).as_value().string_value()
            print("[GuideMove] robot ID " + str(robot_id))
            vertex = temp_gl.get_expression(2).as_value().int_value()
            print("[GuideMove] vertex " + str(vertex))
            direction = temp_gl.get_expression(3).as_value().string_value()
            print("[GuideMove] direction " + str(direction))
            print("GGGG")
            self.generator_queue.append(RobotTask(self.guide_move(robot_id, action_id, vertex, direction), "guidemove_" + robot_id))
            print("GGGG")
            return "(ok)"
            
        elif temp_gl.get_name() == "PreciseMove":
            ''' (PreciseMove (actionID $actionID) $robotID $vertex) '''
            print("[PreciseMove] start PreciseMove")
            action_id_gl = temp_gl.get_expression(0).as_generalized_list()
            action_id = action_id_gl.get_expression(0).as_value().string_value()
            robot_id = temp_gl.get_expression(1).as_value().string_value()
            vertex = temp_gl.get_expression(2).as_value().int_value()
            print("PPPP")
            self.generator_queue.append(RobotTask(self.precise_move(robot_id, action_id, vertex), "precisemove_" + robot_id))
            print("PPPP")
            return "(ok)"
            
        elif temp_gl.get_name() == "StraightBackMove":
            ''' (StraightBackMove (actionID $actionID) $robotID $vertex) '''
            print("[StraightBackMove] start StraightBackMove")
            action_id_gl = temp_gl.get_expression(0).as_generalized_list()
            action_id = action_id_gl.get_expression(0).as_value().string_value()
            robot_id = temp_gl.get_expression(1).as_value().string_value()
            vertex = temp_gl.get_expression(2).as_value().int_value()
            print("SSSS")
            self.generator_queue.append(RobotTask(self.straight_back_move(robot_id, action_id, vertex), "straightbackmove_" + robot_id))
            print("SSSS")
            return "(ok)"
            
        else:
            print("what?", str(temp_gl))
            return "(fail)"

    def queue_requested_action(self, action_id, real_goal, robot_id_BI, robot_id_replan):
        if robot_id_BI:  # check whether robot_id_BI is empty
            for robot_id in robot_id_BI:
                if len(robot_id_replan) < 2:
                    self.semantic_map_manager_notify(robot_id)  # # notify SMM of same control information
                    print(
                        "[{action_id}][INFO2] {RobotID} cancel move".format(action_id=action_id, RobotID=robot_id))
                    self.generator_queue.append(RobotTask(self.cancel_move(robot_id, action_id), "cancel_move"))
                    print("[{action_id}][INFO2] {RobotID} cancel move finish".format(action_id=action_id,
                                                                                     RobotID=robot_id))
                    try:
                        gen = self.wait_for_data(action_id, robot_id)
                        while True:
                            cancel_move_response = next(gen)
                            if cancel_move_response is not None:
                                break
                            print("[QUEUE_REQUESTED_ACTION]yield waiting " + action_id)
                            yield
                    except StopIteration:
                        pass

                    print("[{action_id}][INFO2] {RobotID}".format(action_id=action_id, RobotID=robot_id))
                    print(
                        "[{action_id}][INFO2] {RobotID} Control request by <Move> Request [{num}], to {goal}".format(
                            action_id=action_id, RobotID=robot_id, num=self.count, goal=real_goal))
                    # Thread(target=self.Control_request, args=(robot_id, False, True, self.count,),daemon=True).start()  # control request of robotID
                    self.preserved_queue.append(
                        RobotTask(self.control_request(robot_id, False, True, self.count), robot_id))
                    self.count = self.count + 1
        if robot_id_replan:  # check whether robot_id_replan is empty
            for robot_id in robot_id_replan:
                print("[{action_id}][INFO3] {RobotID} cancel move".format(action_id=action_id, RobotID=robot_id))
                self.generator_queue.append(RobotTask(self.cancel_move(robot_id), "cancel_move"))
                print("[{action_id}][INFO3] {RobotID} cancel move finish".format(action_id=action_id,
                                                                                 RobotID=robot_id))
                try:
                    gen = self.wait_for_data(action_id, robot_id)
                    while True:
                        cancel_move_response = next(gen)
                        if cancel_move_response is not None:
                            break
                        print("[QUEUE_REQUESTED_ACTION]yield waiting " + action_id)
                        yield
                except StopIteration:
                    pass
            path_response = self.multi_robot_path_query(
                robot_id_replan)  # query about not collidable path to MultiAgentPathFinder(MAPF)
            path_response_gl = GLFactory.new_gl_from_gl_string(path_response)
            ''' path_response_gl gl format: (MultiRobotPath (RobotPath $robot_id (path $v_id1 $v_id2 $v_id3, ...)), …) '''

            robot_ids = self.multi_robot_path_update(path_response_gl)  # update path of robot in NC
            for robot_id in robot_ids:
                self.semantic_map_manager_notify(robot_id)

            for robot_id in robot_id_replan:
                if self.navigation_controller.current_command[robot_id]:
                    print("[{action_id}][INFO3] {RobotID} Control request by <Move> Request [{num}]".format(
                        action_id=action_id, RobotID=robot_id, num=self.count))
                    # Thread(target=self.Control_request, args=(robot_id, False, True, self.count,), daemon=True).start()  # control request of robotID
                    self.preserved_queue.append(
                        RobotTask(self.control_request(robot_id, False, True, self.count), robot_id))
                    print("generator queue appended")
                else:
                    self.move_flag[robot_id] = True
                self.count = self.count + 1

    def async_sleep(self, seconds):
        end_time = time.time() + seconds
        print("current time is " + str(time.time()) + " and end time is " + str(end_time))
        while True:
            if time.time() > end_time:
                print("end waiting")
                break
            else:
                # print("current time is " + str(time.time()) + " and end time is " + str(end_time))
                yield

    def guide_move(self, robot_id, action_id, vertex, direction):
        counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
        robot_index = self.AMR_IDs.index(robot_id)
        c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
        while True:
            yield from self.async_sleep(1)
            if not (vertex in self.navigation_controller.current_command[c_robot_id][:3]):
                print("[INFO] {robot_id} no collision expected during {vertex} work".format(robot_id=robot_id, vertex=vertex))
                break
            else:
                print("[INFO] {robot_id} collision expected during {vertex} work -> waiting".format(robot_id=robot_id, vertex=vertex))
                yield
        
        ''' (guideMove (actionID $actionID) $vertex $direction) '''
        temp_guide_move_gl = "(guideMove (actionID \"{actionID}\") {vertex} \"{direction}\")"
        guide_move_gl = temp_guide_move_gl.format(actionID=action_id, vertex=vertex, direction=direction)
        is_failed = True
        while is_failed:
            response_str = self.request(self.behavior_interface_uri[robot_id], guide_move_gl)
            response_gl = GLFactory.new_gl_from_gl_string(response_str)
            if response_gl.get_name() != "fail":
                try:
                    gen = self.wait_for_data(action_id, robot_id)
                    while True:
                        guide_move_response = next(gen)
                        if guide_move_response is not None:
                            break
                        print("[GUIDE_MOVE]yield waiting " + action_id)
                        yield
                except StopIteration:
                    pass
                guide_move_result_gl = "(MoveResult (actionID \"{actionID}\") \"{result}\")".format(actionID=action_id, result="success")
                print(guide_move_result_gl)
                self.send(self.task_manager_uri[robot_id], guide_move_result_gl)
                is_failed = False
            else:
                yield from self.async_sleep(1)
        
    def precise_move(self, robot_id, action_id, vertex):
        counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
        robot_index = self.AMR_IDs.index(robot_id)
        c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot

        while True:
            yield from self.async_sleep(1)

            if not (vertex in self.navigation_controller.current_command[c_robot_id][:3]):
                print("[INFO] {robot_id} no collision expected during {vertex} work".format(robot_id=robot_id, vertex=vertex))
                break
            else:
                print("[INFO] {robot_id} collision expected during {vertex} work -> waiting".format(robot_id=robot_id, vertex=vertex))
                yield

        ''' (preciseMove (actionID $actionID) $vertex) '''
        temp_precise_move_gl = "(preciseMove (actionID \"{actionID}\") {vertex})"
        precise_move_gl = temp_precise_move_gl.format(actionID=action_id, vertex=vertex)
        is_failed = True
        while is_failed:
            response_gl_str = self.request(self.behavior_interface_uri[robot_id], precise_move_gl)
            response_gl = GLFactory.new_gl_from_gl_string(response_gl_str)
            if response_gl.get_name() != "fail":
                try:
                    gen = self.wait_for_data(action_id, robot_id)
                    while True:
                        precise_move_response = next(gen)
                        if precise_move_response is not None:
                            break
                        print("[PRECISE_MOVE]yield waiting " + action_id)
                        yield
                except StopIteration:
                    pass
                precise_move_result_gl = "(MoveResult (actionID \"{actionID}\") \"{result}\")".format(actionID=action_id, result="success")
                print(precise_move_result_gl)
                self.send(self.task_manager_uri[robot_id], precise_move_result_gl)
                is_failed = False
            else:
                yield from self.async_sleep(1)
        
    def straight_back_move(self, robot_id, action_id, vertex):
        counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
        robot_index = self.AMR_IDs.index(robot_id)
        c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
        while True:
            yield from self.async_sleep(1)

            if not (vertex in self.navigation_controller.current_command[c_robot_id][:3]):
                print("[INFO] {robot_id} no collision expected during {vertex} work".format(robot_id=robot_id, vertex=vertex))
                break
            else:
                print("[INFO] {robot_id} collision expected during {vertex} work -> waiting".format(robot_id=robot_id, vertex=vertex))
                
        ''' (straightBackMove (actionID $actionID) $vertex) '''
        temp_straight_back_move_gl = "(straightBackMove (actionID \"{actionID}\") {vertex})"
        straight_back_move_gl = temp_straight_back_move_gl.format(actionID=action_id, vertex=vertex)
        is_failed = True
        while is_failed:
            response_str = self.request(self.behavior_interface_uri[robot_id], straight_back_move_gl)
            response_gl = GLFactory.new_gl_from_gl_string(response_str)
            if response_gl.get_name() != "fail":
                try:
                    gen = self.wait_for_data(action_id, robot_id)
                    while True:
                        straight_back_move_response = next(gen)
                        if straight_back_move_response is not None:
                            break
                        print("[STRAIGHT_BACK_MOVE]yield waiting " + action_id)
                        yield
                except StopIteration:
                    pass
                straight_back_move_result_gl = "(MoveResult (actionID \"{actionID}\") \"{result}\")".format(actionID=action_id, result="success")
                print(straight_back_move_result_gl)
                self.send(self.task_manager_uri[robot_id], straight_back_move_result_gl)
                is_failed = False
            else:
                yield from self.async_sleep(1)
        
    def cancel_move(self, robot_id, action_id):
        # if len(self.navigation_controller.current_command[robot_id]) == 1:  # check whether robot is stationary
        #     # stationary_check = (self.cur_robot_pose[robot_id][0] == self.cur_robot_pose[robot_id][1] ==
        #     #                     self.navigation_controller.current_command[robot_id][
        #     #                         0])  # True if robot is stationary and will be stationary
        #     stationary_check = (self.real_goal[robot_id] == -1)
        # else:
        #     stationary_check = False

        # if self.navigation_controller.current_command[
        #     robot_id] and not stationary_check:  # check whether robot has path and not stationary
        print("[CancelMove]we're in cancel_move " + robot_id)
        if self.navigation_controller.current_command[robot_id]:
            ''' if robot is avoiding against counterpart robot, path of the robot is split
                e.g. self.NC.robotTM_set[avoidingRobotID] == [[path], [path]]
                     self.NC.robotTM_set[counterpartRobotID] == [[path]] '''
            print("[CancelMove] we've navigation_controller.current_command[robot_id]")
            if len(self.navigation_controller.command_set[robot_id]) == 1:  # not split path (not avoiding path)
                ### Cancel current control request if robot is moving ###
                # if self.move_flag[robot_id]:  # check whether robot is moving
                ''' If robot is moving now, current path should be canceled.
                    Cancel actionID:
                        "AMR_LIFT1": "\"5\""
                        "AMR_LIFT2": "\"6\""
                        "AMR_TOW1": "\"7\""
                        "AMR_TOW2": "\"8\""
                    cancelMove gl format: (cancelMove (actionID $actionID)) '''

                temp_Cancel_gl = "(cancelMove (actionID {actionID} \"{robotID}\"))"
                if action_id is None:
                    action_id = "\"" + str(uuid.uuid4()) + "\""
                Cancel_gl = temp_Cancel_gl.format(actionID=action_id, robotID=robot_id)  # Cancel actionID
                self.move_flag[robot_id] = False  # update moving state of robot
                print("[Request CancelMove1]\t{RobotID}".format(RobotID=robot_id))
                self.request(self.behavior_interface_uri[robot_id], Cancel_gl)  # get response of Cancel request
                try:
                    gen = self.wait_for_data(action_id, robot_id)
                    while True:
                        cancel_response_gl = next(gen)
                        if cancel_response_gl is not None:
                            break
                        print("[CANCEL_MOVE1]yield waiting " + action_id)
                        yield
                except StopIteration:
                    pass

                if cancel_response_gl.get_name() == "fail":
                    print("[Response CancelMove1]\t{RobotID}: FAIL".format(RobotID=robot_id))
                else:
                    self.canceled_robot_id.append(robot_id)
                    result = cancel_response_gl.get_expression(
                        1).as_value().string_value()  # "success" if Cancel request is done
                    print("[Response CancelMove1]\t{RobotID}: {Result}".format(RobotID=robot_id, Result=result))
                    self.data_received.append(Message(False, cancel_response_gl))
                    cancel_gl = GLFactory.new_gl_from_gl_string(
                        "(cancelMove (actionID " + action_id + " \""+robot_id+"\") \"success\")")
                    print(cancel_gl)
                    self.data_received.append(Message(False, cancel_gl))
            elif len(self.navigation_controller.command_set[robot_id]) >= 2:  # split path (avoiding path)
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
                # if self.move_flag[robot_id]:  # check whether robot is moving
                temp_Cancel_gl = "(cancelMove (actionID {actionID} \"{robotID}\"))"
                if action_id is None:
                    action_id = "\"" + str(uuid.uuid4()) + "\""
                Cancel_gl = temp_Cancel_gl.format(actionID=action_id, robotID=robot_id)  # Cancel actionID
                self.move_flag[robot_id] = False  # update moving state of robot
                print("[Request CancelMove2]\t{RobotID}".format(RobotID=robot_id))
                self.request(self.behavior_interface_uri[robot_id], Cancel_gl)  # get response of Cancel request

                try:
                    gen = self.wait_for_data(action_id, robot_id)
                    while True:
                        cancel_response_gl = next(gen)
                        if cancel_response_gl is not None:
                            break
                        print("[CANCEL_MOVE2]yield waiting " + action_id)
                        yield
                except StopIteration:
                    pass

                if cancel_response_gl.get_name() == "fail":
                    print("[Response CancelMove2]\t{RobotID}: FAIL".format(RobotID=robot_id))
                else:
                    self.canceled_robot_id.append(robot_id)
                    result = cancel_response_gl.get_expression(
                        1).as_value().string_value()  # "success" if Cancel request is done
                    print("[Response CancelMove2]\t{RobotID}: {Result}".format(RobotID=robot_id, Result=result))
                    self.data_received.append(Message(False, cancel_response_gl))
                    # cancel_gl = GLFactory.new_gl_from_gl_string(
                    #     "(cancelMove (actionID " + self.BI_actionID[robot_id][0] + ") \"success\")")
                    # self.data_received.append(Message(False, cancel_gl))
        else:
            self.data_received.append(Message(False, GLFactory.new_gl_from_gl_string("(cancelMove (actionID {actionID} \"{robotID}\"))".format(actionID=action_id, robotID=robot_id))))

        yield "finished"

    def control_request(self, robot_id, collide, replan, count):
        c = "[" + str(count) + "]"
        self.count = self.count + 1
        print(c + "[Info] Control request start : " + robot_id)
        self.move_flag[robot_id] = True
        ''' if robot is in stationary state, output from MAPF path is same with current vertex
            e.g. "AMR_TOW1" : in stationary state, no plan to move
                -> self.cur_robot_pose["AMR_TOW1"][0] == self.cur_robot_pose["AMR_TOW1"][1]
                -> len(self.NC.robotTM[robot_id][0]) == 1
            => no control is needed '''

        ''' self.NC.robotTM[robotID]: current path of robotID '''

        if collide:
            self.collide_flag[robot_id] = True
            # counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
            # robot_index = self.AMR_IDs.index(robot_id)
            # c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
            # self.collide_flag[c_robot_id] = True
            # time.sleep(1)
        elif replan:
            print("[control_request]REPLAN YIELD")
            yield from self.async_sleep(5)

        # if (self.cur_robot_pose[robot_id][0] == self.cur_robot_pose[robot_id][1]) and (self.cur_robot_pose[robot_id][0] == self.actual_goal[robot_id]):
        #     print(c + "current pose equals goal -> thread terminate")
        #     self.thread_flag[robot_id] = False

        while not self.navigation_controller.current_command[robot_id]:
            print(c + "waiting path by " + robot_id)
            yield
            if self.navigation_controller.current_command[robot_id]:
                print(c + "got path")
                print(c + " robot_id " + str(robot_id))
                print(c + " ROBOT_TM " + str(self.navigation_controller.current_command[robot_id]))
                break
            else:
                continue

        # if len(self.navigation_controller.current_command[robot_id]) == 1:  # check whether robot is stationary
        #     # stationary_check = (self.cur_robot_pose[robot_id][0] == self.cur_robot_pose[robot_id][1]) and (
        #     #         self.actual_goal[robot_id] == -1)  # True if robot is stationary and will be stationary
        #     stationary_check = (self.real_goal[robot_id] == -1)
        # else:
        #     stationary_check = False

        # print(str(robot_id) + " is now tested..." + str(stationary_check))

        # if self.navigation_controller.current_command[robot_id] and (
        #         not stationary_check):  # check whether robot has path and not stationary
        if self.navigation_controller.current_command[robot_id]:
            ''' if robot is avoiding against counterpart robot, path of the robot is split
                e.g. self.NC.robotTM_set[avoidingRobotID] == [[path], [path]]
                     self.NC.robotTM_set[counterpartRobotID] == [[path]] '''

            print(self.navigation_controller.command_set)
            print("length = " + str(len(self.navigation_controller.command_set[robot_id])))

            if len(self.navigation_controller.command_set[robot_id]) == 1:  # not split path (not avoiding path)
                print("single path control " + str(robot_id))
                yield from self.single_path_control(c, robot_id)
                print("single path control done" + str(robot_id))
            elif len(self.navigation_controller.command_set[robot_id]) >= 2:  # split path (avoiding path)
                print("multi path control" + str(robot_id))
                yield from self.multi_path_control(c, robot_id)
                print("multi path control done" + str(robot_id))

        if collide:
            self.collide_flag[robot_id] = False
            counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
            robot_index = self.AMR_IDs.index(robot_id)
            c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
            self.collide_flag[c_robot_id] = False
        print(c + "[Info] Control request finish " + str(robot_id))

    def multi_path_control(self, c, robot_id):
        print("path split")
        self.avoid_flag[robot_id] = True  # update avoiding state of robot
        counterpart_check = {0: 1, 1: 0, 2: 3, 3: 2}
        robot_index = self.AMR_IDs.index(robot_id)
        c_robot_id = self.AMR_IDs[counterpart_check[robot_index]]  # get robotID of counterpart robot
        self.avoid_flag[c_robot_id] = True
        # currnet_command_set = copy.copy(self.navigation_controller.command_set)  # get path set
        currnet_command_set = self.navigation_controller.command_set
        # current_command_set_start_condition = copy.copy(
        #     self.navigation_controller.command_start_condition)  # get start condition of robot
        current_command_set_start_condition = self.navigation_controller.command_start_condition
        ''' self.NC.robotTM_scond: start condition of split path
                            e.g. AMR_LIFT1 is avoiding robot and AMR_LIFT2 is counterpart robot
                                 self.NC.robotTM_set["AMR_LIFT1"] == [[1, 2, 3], [4, 5, 6, 7]]
                                 self.NC.robotTM_set["AMR_LIFT2"] == [4, 5, 6, 7, 8, 9]
                                 self.NC.robotTM_scond["AMR_LIFT1"] == [[], [["AMR_LIFT2", [0, 1]]]]

                            self.NC.robotTM_scond["AMR_LIFT1"]: start condition of "AMR_LIFT1"(avoidingRobot)
                            -> no condition of 0th path
                            -> [["AMR_LIFT2", [0, 1]]] condition of 1th path which means start after "AMR_LIFT2" passes 1th element(5) in 0th path([4, 5, 6, 7, 8, 9]) '''
        ### Control request to move ###
        for path_idx in range(len(currnet_command_set[robot_id])):  # consider path set
            print("start condition list " + str(currnet_command_set[robot_id]) + " / current idx" + str(path_idx))
            print("current_command_set_start_condition : " + str(current_command_set_start_condition))
            if current_command_set_start_condition[robot_id]:
                if current_command_set_start_condition[robot_id][path_idx]:  # check whether current path has any start condition
                    wait_flag = True
                    while wait_flag:
                        print("[MULTI_PATH_CONTROL]yield waiting current_command_set_start_condition")
                        if self.real_goal[c_robot_id] == -1:
                            break
                        else:
                            for cond in current_command_set_start_condition[robot_id][path_idx]:
                                if self.navigation_controller.PlanExecutedIdx[cond[0]][0] < cond[1][0] or \
                                        self.navigation_controller.PlanExecutedIdx[cond[0]][1] < cond[1][1]:
                                    wait_flag = True
                                    print("WAITING" + robot_id)
                                    print("cond: " + str(cond))
                                    print("current_command_set_start_condition: " + str(current_command_set_start_condition[robot_id][path_idx]))
                                    print("ExecutedIdx: " + str(self.navigation_controller.PlanExecutedIdx))
                                else:
                                    wait_flag = False
                                    # print("[INFO] Start Condition of {RobotID} is Satisfied".format(RobotID=robot_id))
                                    break
                        yield

            ''' Move actionID:
                    "AMR_LIFT1": "\"1\""
                    "AMR_LIFT2": "\"2\""
                    "AMR_TOW1": "\"3\""
                    "AMR_TOW2": "\"4\""
                move gl format: (move (actionID $actionID) $path) '''
            self.move_flag[robot_id] = True  # update moving state of robot
            print(c + "while start")
            while not self.navigation_controller.current_command[robot_id]:
                # print("[INFO] {RobotID} is waiting for Path Update".format(RobotID=robot_id))
                print("[MULTI_PATH_CONTROL]yield waiting path update from " + str(robot_id))
                yield
            if self.navigation_controller.current_command[robot_id]:
                print(c + "[current_command of NC]\t\t{current_command_set}".format(
                    current_command_set=self.navigation_controller.current_command))
                print(c + "[current_command]\t\t{current_command_set}".format(current_command_set=currnet_command_set))
                robot_path = currnet_command_set[robot_id][path_idx]  # get current path of path set
                print(c + "[current_command]\t\t{RobotID}\t{Path}".format(RobotID=robot_id, Path=str(robot_path)))

            move_gl_str_format = "(move (actionID {actionID}) {path})"
            path_gl = self.path_gl_generator(robot_path, robot_id)  # convert path list to path gl
            action_id = "\"" + str(uuid.uuid4()) + "\""
            move_gl = move_gl_str_format.format(actionID=action_id, path=path_gl)
            self.semantic_map_manager_notify(robot_id)

            print(c + "[Request Move2]\t\t{RobotID}\t{Path}".format(RobotID=robot_id, Path=str(path_gl)))
            self.move_flag[robot_id] = True
            move_response = self.request(self.behavior_interface_uri[robot_id],
                                         move_gl)  # request move control to robotBI, get response of request                                    print(c + "[response Move1]\t\t{RobotID}\t{response}".format(RobotID=robot_id, response=str(move_response)))

            if move_response != "(ok)":
                pass
            else:
                gen = self.wait_for_data(action_id, robot_id)
                print("[RM2] wait for data " + str(action_id))

                move_response_gl = None
                while move_response_gl is None:
                    move_response_gl = next(gen)
                    print("move_response_gl " + str(move_response_gl) + " / waiting " + str(action_id))
                    if move_response_gl is not None:
                        break
                    yield
                print(c + "[response Move2]\t\t{RobotID}\t{response}".format(RobotID=robot_id,
                                                                             response=str(
                                                                                 move_response)))
                print("[Response Move2] " + move_response_gl.get_name() + "/" + str(move_response_gl.get_name() != "fail"))
                if move_response != "fail" and str(move_response_gl.get_name()).lower() != "cancelmove":
                    result = move_response_gl.get_expression(
                        1).as_value().string_value()  # "success" if request is done, "(fail)"" if request can't be handled
                    print(c + "[Response Move2]\t\t{RobotID}\t{Path}: {Result}".format(RobotID=robot_id, Path=str(path_gl),
                                                                                       Result=str(result)))
        self.avoid_flag[robot_id] = False  # update avoiding state of robot
        self.avoid_flag[c_robot_id] = False  # update avoiding state of robot
        yield from self.async_sleep(0.5)
        yield from self.goal_check(robot_id, action_id)
        print("jobs done! by MPC")

    def single_path_control(self, c, robot_id):
        self.move_flag[robot_id] = True  # update moving state of robot
        while not self.navigation_controller.current_command[robot_id]:
            print("[SINGLE_PATH_CONTROL]yield waiting current command set")
            yield
        if self.navigation_controller.current_command[robot_id]:
            # robot_path = copy.copy(self.navigation_controller.current_command[robot_id])
            robot_path = self.navigation_controller.command_set[robot_id][0]
            # print("[INFO] {RobotID} got new path".format(RobotID=robot_id))
        move_gl_str_format = "(move (actionID {actionID}) {path})"
        path_gl = self.path_gl_generator(robot_path, robot_id)  # convert path list to path gl
        action_id = "\"" + str(uuid.uuid4()) + "\""
        move_gl = move_gl_str_format.format(actionID=action_id, path=path_gl)
        self.semantic_map_manager_notify(robot_id)
        print(
            c + "[Request Move1]\t\t{RobotID}\t{Path}".format(RobotID=robot_id, Path=str(path_gl)))
        self.move_flag[robot_id] = True
        move_response = self.request(self.behavior_interface_uri[robot_id],
                                     move_gl)  # request move control to robotBI, get response of request
        if move_response != "(ok)":
            print("move failed. jobs done!")
            pass
        else:
            try:
                gen = self.wait_for_data(action_id, robot_id)
                while True:
                    move_response_gl = next(gen)
                    print("[SINGLE_PATH_CONTROL]yield waiting move_response_gl : " + str(move_response_gl) + " // action_id is " + str(action_id))
                    if move_response_gl is not None:
                        break
                    yield
            except StopIteration:
                pass

            print(c + "[response Move1]\t\t{RobotID}\t{response}".format(RobotID=robot_id, response=str(move_response_gl)))
            print("[Response Move1] " + str(move_response_gl.get_name().lower()))
            if move_response != "fail" and str(move_response_gl.get_name()).lower() != "cancelmove":
                result = move_response_gl.get_expression(
                    1).as_value().string_value()  # "success" if request is done, "(fail)"" if request can't be handled
                print(c + "[response Move1]\t\t{RobotID}\t{Path}: {Result}".format(RobotID=robot_id,
                                                                                   Path=str(path_gl),
                                                                                   Result=str(result)))
                yield from self.async_sleep(0.5)
                yield from self.goal_check(robot_id, action_id)
            elif move_response != "fail" and str(move_response_gl.get_name()).lower() == "cancelmove":
                yield from self.async_sleep(1)
                yield from self.goal_check(robot_id, action_id)
            print("jobs done! by SPC")

    def semantic_map_manager_notify(self, robot_id):  # notify SMM of control information
        ''' RobotPathPlan gl format: (RobotPathPlan $robot_id $goal (path $v_id1 $v_id2 ….)) '''
        if self.navigation_controller.current_command[robot_id]:
            temp_SMM_gl = "(RobotPathPlan \"{robot_id}\" {goal} {path})"
            robot_path = copy.copy(self.navigation_controller.current_command[robot_id])
            path_gl = self.path_gl_generator(robot_path, robot_id)  # convert path list to path gl
            SMM_gl = temp_SMM_gl.format(robot_id=robot_id, goal=self.actual_goal[robot_id], path=path_gl)
            print("[Notify] Notify Path and Goal of {RobotID} to SMM".format(RobotID=robot_id))
            self.notify(self.SMM_name, SMM_gl)  # notify SMM
        else:
            # print("[INFO] {RobotID} has no path".format(RobotID=robot_id))
            pass

    def path_gl_generator(self, in_path, robot_id):  # convert path list to path gl
        ''' path gl format: (path $v_id1 $v_id2 ….) '''
        path = copy.copy(in_path)
        # if path[0] != self.cur_robot_pose[robot_id][0]:
        #     path.insert(0, self.cur_robot_pose[robot_id][0])
        path_gl = "(path"
        for path_i in path:
            path_gl += " "
            path_gl += str(path_i)
        path_gl += ")"
        print('1111111111111', path, path_gl)
        return path_gl

    def goal_check(self, robot_id,
                   action_id):  # check whether robot terminates its goal and if it terminates, send result of goal to robotTM
        while True:
            is_goal_terminated = self.navigation_controller.Flag_terminate[
                robot_id]  # get terminateFlag from NC (-1: Not terminated, 0: Success Terminate 1: Fail Terminate)
            print("GGGGGGGoal check from " + str(robot_id) + " / actionID : " + str(
                action_id) + " / is_goal_terminated : " + str(is_goal_terminated))
            if is_goal_terminated == -1:
                if self.navigation_controller.robotPose[robot_id][0] == self.navigation_controller.robotGoal[robot_id]:
                    is_goal_terminated = 0
                    # check twice
                    print("goal terminated turned into " + str(is_goal_terminated) + " by 2nd check method")

            if is_goal_terminated == 0:  # check wheather robot is moving and just terminates its goal
                self.move_flag[robot_id] = False  # update state of robot to not moving
                ''' MoveResult gl format: (MoveResult (actionID $actionID) $robotID $result) '''

                goal_result_gl = "(MoveResult (actionID \"{ActionID}\") \"{Result}\")".format(
                    ActionID=self.goal_actionID[robot_id],
                    Result="success")
                print("[INFO] \"{RobotID}\" to \"{GoalID}\": success".format(RobotID=robot_id,
                                                                             GoalID=self.real_goal[robot_id]))
                self.send(self.task_manager_uri[robot_id], goal_result_gl)  # send result to robotTM
                # self.actual_goal[robot_id] = self.navigation_controller.robotGoal[robot_id]
                self.real_goal[robot_id] = self.navigation_controller.robotGoal[robot_id]
                break
            else:
                yield

    def multi_robot_path_update(self, response_gl):  # update paths of robots in NC
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
            # path_size -= 1
            path = list()

            if path_size > 0:
                for j in range(path_size):
                    path.append(path_gl.get_expression(j).as_value().int_value())  # generate path list
            multipaths[robot_id] = path
            robot_pose[robot_id] = copy.copy(self.cur_robot_pose[robot_id])  # get current pose of robot
            print('robot ID : ' + str(robot_id))
            print('path : ' + str(path))
        self.navigation_controller.get_multipath_plan(multipaths)  # update path in NC
        command_set = self.navigation_controller.command_set

        for current_robot_key in command_set.keys():
            current_robot_command = command_set[current_robot_key]
            for path_i in range(len(current_robot_command)):
                if len(current_robot_command) > path_i > 0:
                    last_element = current_robot_command[path_i-1][-1]
                    first_element = current_robot_command[path_i][0]
                    if last_element != first_element:
                        current_robot_command[path_i].insert(0, last_element)

        print("[MultiRobotPathUpdate] " + str(command_set))
        print("[MultiRobotPathUpdate] " + str(self.navigation_controller.command_set))
        # self.navigation_controller.current_command[id] = []  # a sequence of vertices
        # self.navigation_controller.command_set[id] = []  # [robotTM, robotTM, robotTM, ...]
        # self.navigation_controller.command_start_condition[id] = []  # start condition of robotTM
        # self.navigation_controller.PlanExecutedIdx[id] = [-1,-1]  # [i,j] Save the last index of NavPath[i][j] which the robot follows
        # self.navigation_controller.Flag_terminate[id] = -1
        self.navigation_controller.update_robot_TM(robot_pose)  # update pose in NC

        return robot_ids

    def multi_robot_path_query(self, replanned_robot_ids):  # query about path to MultiAgentPathFinder(MAPF)
        ''' MultiRobotPath gl format: (MultiRobotPath (RobotPath $robot_id $cur_vertex $goal_id), …) '''

        path_query_gl = "(MultiRobotPath"
        for robot_id in replanned_robot_ids:
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

            if len(replanned_robot_ids) == 1:  # check wheather robot_id_replan(argument) has one ID
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

        print("[Query] Query Robot Path to MAPF :", path_query_gl)
        path_response = self.query(agent_mapf_uri, path_query_gl)
        print("[Query] Response from MAPF :", path_response)

        return path_response

    def wait_for_data(self, action_id, robot_id):
        print("waiting " + action_id + " from " + robot_id)
        while True:
            _action_id = None
            result_gl = None
            set_count_before = len(self.data_received)
            # print("i'm looking for action_id " + str(action_id))
            for msg in self.data_received:
                gl = msg.gl
                action_id_gl = gl.get_expression(0).as_generalized_list()
                _action_id = action_id_gl.get_expression(0).as_value().string_value()
                print("_action_id is " + str(_action_id) + " and action_id is " + str(action_id) + " so result is " + str(
                    str(action_id).replace("\"", "") == str(_action_id)) + " and original gl is " + str(gl))
                if str(action_id).replace("\"", "") == str(_action_id):
                    result_gl = gl
                    msg.survive_flag = False
                    print("gl removed : " + str(gl))

                if action_id_gl.get_expression_size() > 1:
                    _robot_id = action_id_gl.get_expression(1).as_value().string_value()
                    if robot_id == _robot_id:
                        result_gl = gl
                        msg.survive_flag = False
                        print("gl removed : " + str(gl))

            yield result_gl

    def cleanse_list(self):
        while True:
            cleansed_list = []
            for msg in self.data_received:
                if msg.survive_flag:
                    cleansed_list.append(msg)
                elif not msg.dead_flag:
                    cleansed_list.append(msg)
                    msg.dead_flag = True
            self.data_received = cleansed_list
            yield


if __name__ == "__main__":
    agent = NavigationControllerAgent()
    arbi_agent_executor.execute(broker_url=broker_url,
                                agent_name="agent://www.arbi.com/Local/NavigationController",
                                agent=agent, broker_type=2)  # same role with agent.initialize
    while True:
        pass
