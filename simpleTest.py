import vrep
import time
import math
import numpy as np
from breezyslam.algorithms import RMHC_SLAM
from breezyslam.sensors import Laser
from roboviz import MapVisualizer
from mines import pioner

MAP_SIZE_PIXELS = 1000
MAP_SIZE_METERS = 25

error_old = 0
i_min = -0.2
i_max = 0.2
i_sum = 0

def controller(error):

    up = 2 * error;

    global error_old, i_min, i_max, i_sum

    i_sum += error
    i_sum = max(i_sum, i_min)
    i_sum = min(i_sum, i_max)
    ui = 0.007 * i_sum

    ud = 0.07 * (error - error_old)
    error_old = error

    return up + ud + ui;

print('Program started')
vrep.simxFinish(-1)
clientID = vrep.simxStart('127.0.0.1', 19997, True, True, 5000, 5)
if clientID != -1:
    print("Connected to remote server")
else:
    print('Connection not successful')
    sys.exit('Could not connect')

errorCode, left_motor_handle = vrep.simxGetObjectHandle(clientID, 'Pioneer_p3dx_leftMotor', vrep.simx_opmode_oneshot_wait)
errorCode, right_motor_handle = vrep.simxGetObjectHandle(clientID,'Pioneer_p3dx_rightMotor', vrep.simx_opmode_oneshot_wait)

errorCode, proximity_sensor1 = vrep.simxGetObjectHandle(clientID, 'ps1', vrep.simx_opmode_oneshot_wait)
errorCode, detectionState, detectedPoint, detectedObjectHandle, detectedSurfaceNormalVector = vrep.simxReadProximitySensor(clientID, proximity_sensor1, vrep.simx_opmode_streaming)
errorCode, proximity_sensor2 = vrep.simxGetObjectHandle(clientID, 'ps2', vrep.simx_opmode_oneshot_wait)
errorCode, detectionState, detectedPoint, detectedObjectHandle, detectedSurfaceNormalVector = vrep.simxReadProximitySensor(clientID, proximity_sensor2, vrep.simx_opmode_streaming)

errorCode, vision_sensor1 = vrep.simxGetObjectHandle(clientID, 'SICK_TiM310_sensor1', vrep.simx_opmode_oneshot_wait)
errorCode, vision_sensor2 = vrep.simxGetObjectHandle(clientID, 'SICK_TiM310_sensor2', vrep.simx_opmode_oneshot_wait)

errorCode, vision_sensor = vrep.simxGetObjectHandle(clientID, 'Vision_sensor', vrep.simx_opmode_oneshot_wait)
err, resolution, image = vrep.simxGetVisionSensorImage(clientID, vision_sensor, 0, vrep.simx_opmode_streaming)

slam = RMHC_SLAM(Laser(134, 5, 270., 10), MAP_SIZE_PIXELS, MAP_SIZE_METERS, map_quality=1)
viz = MapVisualizer(MAP_SIZE_PIXELS, MAP_SIZE_METERS, 'SLAM')
mapbytes = bytearray(MAP_SIZE_PIXELS * MAP_SIZE_PIXELS)

purpose = 0.3
v = 0.7
robot = pioner()
prev_pos_left = prev_pos_right = 0
velocities = ()

vrep.simxStartSimulation(clientID, vrep.simx_opmode_streaming)
time.sleep(3)
print('Simulation starts')

while vrep.simxGetConnectionId(clientID) != -1:
    #PID-regulation
    errorCode, detectionStateR, detectedPointR, detectedObjectHandle, detectedSurfaceNormalVector = vrep.simxReadProximitySensor(clientID, proximity_sensor1, vrep.simx_opmode_buffer)
    rightX, rightY = detectedPointR[2], detectedPoint[1] if detectionStateR == True else 1e6
    errorCode, detectionStateF, detectedPointF, detectedObjectHandle, detectedSurfaceNormalVector = vrep.simxReadProximitySensor(clientID, proximity_sensor2, vrep.simx_opmode_buffer)
    front = detectedPointF[2] - 0.3 if detectionStateF == True else 1e6
    dist = min(math.sqrt(rightX**2 + rightY**2), front)
    error = dist - purpose
    if error < 10:
        u = controller(error)

    if abs(error) > 1:
        errorCode = vrep.simxSetJointTargetVelocity(clientID, left_motor_handle, v, vrep.simx_opmode_streaming)
        errorCode = vrep.simxSetJointTargetVelocity(clientID, right_motor_handle, v/1.8, vrep.simx_opmode_streaming)

    elif error > 0:
        errorCode = vrep.simxSetJointTargetVelocity(clientID, left_motor_handle, v + u, vrep.simx_opmode_streaming)
        errorCode = vrep.simxSetJointTargetVelocity(clientID, right_motor_handle, v - u, vrep.simx_opmode_streaming)

    elif error < 0:
        errorCode = vrep.simxSetJointTargetVelocity(clientID, left_motor_handle, v + u, vrep.simx_opmode_streaming)
        errorCode = vrep.simxSetJointTargetVelocity(clientID, right_motor_handle, v - u, vrep.simx_opmode_streaming)

    #Data from lidar
    errorCode, detectionState, auxPackets1 = vrep.simxReadVisionSensor(clientID, vision_sensor1, vrep.simx_opmode_blocking)
    errorCode, detectionState, auxPackets2 = vrep.simxReadVisionSensor(clientID, vision_sensor2, vrep.simx_opmode_blocking)
    data = auxPackets1[1][1::2][0::4] + auxPackets2[1][1::2][0::4]
    data = data[1:68] + data[69:136]
    scan = list(np.array(data) * 1000)

    #Odometry
    errorCode, x_left = vrep.simxGetJointPosition(clientID, left_motor_handle, vrep.simx_opmode_streaming)
    dx_left = abs(x_left - prev_pos_left)
    prev_pos_left = x_left
    if dx_left >= 0:
        dx_left = (dx_left + math.pi) % (2 * math.pi) - math.pi
    else:
        dx_left = (dx_left - math.pi) % ( 2 * math.pi) + math.pi
    errorCode, x_right = vrep.simxGetJointPosition(clientID, right_motor_handle, vrep.simx_opmode_streaming)
    dx_right = abs(x_right - prev_pos_right)
    prev_pos_right = x_right
    if dx_right >= 0:
        dx_right = (dx_right + math.pi) % (2 * math.pi) - math.pi
    else:
        dx_right = (dx_right - math.pi) % (2 * math.pi) + math.pi
    velocities = robot.computePoseChange(time.time(), abs(dx_left), abs(dx_right))

    #Slam
    slam.update(scan, velocities)
    x, y, theta = slam.getpos()
    slam.getmap(mapbytes)
    if not viz.display(x / 1000., y / 1000., theta, mapbytes):
        exit(0)

print('Simulation finished')
exit(0)