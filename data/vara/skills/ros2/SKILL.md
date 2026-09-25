---
name: ros2
description: Inspect, build and run ROS 2 robots and simulations safely (topics, nodes, packages, colcon, launch)
---

# ROS 2

## Look first (no approval needed)

- `ros2 topic list -t`, `ros2 node list`, `ros2 topic info /cmd_vel -v`
- One message: `ros2 topic echo /odom --once` (always `--once`; add `--no-arr` for big arrays)
- Rates: `ros2 topic hz /scan` with a timeout of about 10 s
- Types: `ros2 interface show geometry_msgs/msg/Twist`
- `ros2 doctor --report` when something is off

Nothing listed? The robot or simulation isn't running, or ROS_DOMAIN_ID differs: ask the person.

## Safety with real robots

- `ros2 topic pub`, `ros2 service call`, `ros2 action send_goal`, `ros2 run` and `ros2 launch` can move hardware:
  say what will move, how fast and for how long, and use small values first.
- Publish once with `-1` (`ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist "{linear: {x: 0.1}}"`), and
  send a zero Twist afterwards to stop.
- Prefer a simulation (turtlesim, Gazebo) to test new code.

## Packages and building

```bash
mkdir -p ~/Projects/ros_ws/src && cd ~/Projects/ros_ws/src
ros2 pkg create --build-type ament_python --dependencies rclpy geometry_msgs my_robot
cd .. && colcon build --symlink-install && source install/setup.bash
```

- Python nodes: add an entry point in `setup.py` (`console_scripts`), rebuild, then `ros2 run my_robot node_name`.
- The `ros2` tool sources `/opt/ros/<distro>/setup.bash` and the workspace's `install/setup.bash` when run from the workspace folder.
- Long-running `ros2 run`/`launch`: give a timeout, or suggest the person runs it in a Terminal.

## Installing ROS 2 on PolyOS

ROS 2's official packages target Ubuntu. On PolyOS (Debian) the simplest ways are RoboStack
(conda-forge; `micromamba create -n ros_env -c conda-forge -c robostack-staging ros-jazzy-desktop`, then
`micromamba run -n ros_env ros2 ...` through run_command) or a container (`docker run -it --net=host ros:jazzy`).
Explain the choice and let the person decide before installing anything.
