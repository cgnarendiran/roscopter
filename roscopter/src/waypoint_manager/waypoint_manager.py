#!/usr/bin/env python

import numpy as np
import rospy
import std_msgs.msg

from nav_msgs.msg import Odometry
from rosflight_msgs.msg import Command
from roscopter_msgs.msg import RelativePose
from roscopter_msgs.srv import AddWaypoint, RemoveWaypoint, SetWaypointsFromFile, ListWaypoints


class WaypointManager():

    def __init__(self):

        # get parameters
        try:
            self.waypoint_list = rospy.get_param('~waypoints')
        except KeyError:
            rospy.logfatal('waypoints not set')
            rospy.signal_shutdown('Parameters not set')


        # how close does the MAV need to get before going to the next waypoint?
        self.threshold = rospy.get_param('~threshold', 5)
        self.cyclical_path = rospy.get_param('~cycle', True)

        self.prev_time = rospy.Time.now()

        # set up Services
        self.add_waypoint_service = rospy.Service('add_waypoint', AddWaypoint, self.addWaypointCallback)
        self.remove_waypoint_service = rospy.Service('remove_waypoint', RemoveWaypoint, self.removeWaypointCallback)
        self.set_waypoints_from_file_service = rospy.Service('set_waypoints_from_file', SetWaypointsFromFile, self.setWaypointsFromFileCallback)
        self.list_waypoints = rospy.Service('list_waypoints', ListWaypoints, self.listWaypoints)

        # Wait a second before we publish the first waypoint
        while (rospy.Time.now() < rospy.Time(2.)):
            pass

        # Set Up Publishers and Subscribers
        self.xhat_sub_ = rospy.Subscriber('state', Odometry, self.odometryCallback, queue_size=5)
        self.waypoint_pub_ = rospy.Publisher('high_level_command', Command, queue_size=5, latch=True)
        self.relPose_pub_ = rospy.Publisher('relative_pose', RelativePose, queue_size=5, latch=True)

        #Create the initial relPose estimate message
        relativePose_msg = RelativePose()
        relativePose_msg.x = 0
        relativePose_msg.y = 0
        relativePose_msg.z = 0
        relativePose_msg.F = 0
        self.relPose_pub_.publish(relativePose_msg)

        #Create the initial command message
        self.current_waypoint_index = 0
        command_msg = Command()
        current_waypoint = np.array(self.waypoint_list[0])

        command_msg.header.stamp = rospy.Time.now()
        command_msg.x = current_waypoint[0]
        command_msg.y = current_waypoint[1]
        command_msg.F = current_waypoint[2]
        if len(current_waypoint) > 3:
            command_msg.z = current_waypoint[3]
        else:
            command_msg.z = 0.
        command_msg.mode = Command.MODE_XPOS_YPOS_YAW_ALTITUDE
        self.waypoint_pub_.publish(command_msg)

        while not rospy.is_shutdown():
            # wait for new messages and call the callback when they arrive
            rospy.spin()


    def addWaypointCallback(self, req):
        # Add a waypoint to the waypoint list at the specified index.
        new_waypoint = [req.x, req.y, req.z, req.psi]
        if req.index == -1:
            index = len(self.waypoint_list)
        elif req.index > len(self.waypoint_list):
            rospy.logwarn("Waypoint Index Out of Range")
            return
        else:
            index = req.index
        self.waypoint_list.insert(index, new_waypoint)
        if self.current_waypoint_index >= index:
            self.current_waypoint_index += 1
        rospy.loginfo("Added New Waypoint")
        return len(self.waypoint_list)

    def removeWaypointCallback(self, req):
        # Remove a waypoint from the index
        if len(self.waypoint_list) == 1:
            rospy.logwarn("Cannot Remove Only Waypoint")
            return len(self.waypoint_list)
        if req.index >= len(self.waypoint_list):
            rospy.logwarn("Waypoint Index Out of Range")
            return
        del self.waypoint_list[req.index]
        # If the current waypoint was removed, wrap then publish
        if req.index == self.current_waypoint_index:
            self.wrapWaypointIndex()
            self.pubNextWaypoint()
        # Elif the current waypoint was the last, keep as last, don't publish
        elif self.current_waypoint_index >= len(self.waypoint_list):
            self.current_waypoint_index -=1

        return len(self.waypoint_list)

    def setWaypointsFromFileCallback(self, req):
        #TODO
        print("set Waypoints from File (NOT IMPLEMENTED)")

    def listWaypoints(self, req):
        # Returns the waypoint list
        print(self.waypoint_list)
        return True

    # def clearWaypoints(self,req): #TODO

    def odometryCallback(self, msg):
        # Get error between waypoint and current state
        current_waypoint = np.array(self.waypoint_list[self.current_waypoint_index])
        current_position = np.array([msg.pose.pose.position.x,
                                     msg.pose.pose.position.y,
                                     -msg.pose.pose.position.z])

        # orientation in quaternion form
        qw = msg.pose.pose.orientation.w
        qx = msg.pose.pose.orientation.x
        qy = msg.pose.pose.orientation.y
        qz = msg.pose.pose.orientation.z

        # yaw from quaternion
        y = np.arctan2(2*(qw*qz + qx*qy), 1 - 2*(qy**2 + qz**2))
        error = np.linalg.norm(current_position - current_waypoint[0:3])

        #publish the relative pose estimate
        relativePose_msg = RelativePose()
        relativePose_msg.x = current_position[0]
        relativePose_msg.y = current_position[1]
        relativePose_msg.z = y
        relativePose_msg.F = current_position[2]
        self.relPose_pub_.publish(relativePose_msg)

        if error < self.threshold:
            # Get new waypoint index
            self.current_waypoint_index += 1
            self.wrapWaypointIndex()
            self.pubNextWaypoint()

    def wrapWaypointIndex(self):
        if self.cyclical_path:
            self.current_waypoint_index %= len(self.waypoint_list)
        else:
            if self.current_waypoint_index >= len(self.waypoint_list):
                self.current_waypoint_index -=1

    def pubNextWaypoint(self):
        next_waypoint = np.array(self.waypoint_list[self.current_waypoint_index])
        command_msg = Command()
        command_msg.header.stamp = rospy.Time.now()
        command_msg.x = next_waypoint[0]
        command_msg.y = next_waypoint[1]
        command_msg.F = next_waypoint[2]
        if len(next_waypoint) > 3:
            command_msg.z = next_waypoint[3]
        else:
            command_msg.z = 0.
        command_msg.mode = Command.MODE_XPOS_YPOS_YAW_ALTITUDE
        self.waypoint_pub_.publish(command_msg)

if __name__ == '__main__':
    rospy.init_node('waypoint_manager', anonymous=True)
    try:
        wp_manager = WaypointManager()
    except:
        rospy.ROSInterruptException
    pass
