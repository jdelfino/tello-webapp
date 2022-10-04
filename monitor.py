import cv2
import logging
import time
from threading import Thread, Event
import csv
from collections import OrderedDict
import numpy as np
import os
import math
from djitellopy import Tello
from contextlib import contextmanager,redirect_stderr,redirect_stdout
import multiprocessing as mp
import logging

log = logging.getLogger(__name__)

def _writeFrames(frame_timestamps, filename):
    duration = frame_timestamps[-1][1] - frame_timestamps[0][1]
    print("Writing video buffer to '%s', frames = %d, duration = %.2f" % (filename, len(frame_timestamps), duration))
    fps = len(frame_timestamps) / duration
    height, width, _ = frame_timestamps[0][0].shape
    video = cv2.VideoWriter(filename, cv2.VideoWriter_fourcc(*'avc1'), fps, (width, height))

    for frame, timestamp in frame_timestamps:
        cv2.putText(frame, "%.2f" % timestamp, (50, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 4)
        video.write(frame)

    video.release()

def _make_combined_frame(drone_frame, cam_frame, data_frame):
    drone_height, drone_width, _ = drone_frame.shape
    _, total_width, _ = cam_frame.shape

    #cv2.putText(drone_frame, "%.2f" % drone_ts, (50, 75), font, 1, (0, 255, 255), 4)

    top_frame = np.zeros((drone_height, total_width, 3), np.uint8)
    top_frame[0:drone_height,0:drone_width] = drone_frame

    def putDataText(text, y_offset):
        cv2.putText(top_frame, text, (drone_width + 50, y_offset), cv2.FONT_HERSHEY_SIMPLEX, .75, (0, 255, 255), 4)

    putDataText("Height (cm): %d" % data_frame['height_cm'], 100)
    putDataText("Pitch (deg): %d" % data_frame['pitch_degrees'], 150)
    putDataText("Roll (deg): %d" % data_frame['roll_degrees'], 200)
    putDataText("Yaw (deg): %d" % data_frame['yaw_degrees'], 250)
    putDataText("Speed x: %d" % data_frame['speed_x'], 300)
    putDataText("Speed y: %d" % data_frame['speed_y'], 350)
    putDataText("Speed z: %d" % data_frame['speed_z'], 400)

    # timestamp already there from individual videos
    #cv2.putText(f2, "%.2f" % cam_ts, (50, 75), font, 1, (0, 255, 255), 4)

    return np.concatenate((top_frame, cam_frame), axis=0)

def _write_combined(drone_frames, cam_frames, data_frames, filename):
    if len(drone_frames) == 0 or len(cam_frames) == 0 or len(data_frames) == 0:
        print("Missing some frames, skipping combined")
        return

    # make combined side-by-side video
    # assumption: drone cam is narrower than webcam, and data can fit into that extra width
    drone_height, _, _ = drone_frames[0][0].shape
    cam_height, cam_width, _ = cam_frames[0][0].shape

    # mp4v
    video = cv2.VideoWriter(filename, cv2.VideoWriter_fourcc(*'avc1'), 30, (cam_width, drone_height + cam_height))

    start = min(drone_frames[0][1], cam_frames[0][1])
    stop = max(drone_frames[-1][1], cam_frames[-1][1])
    total_duration = stop - start

    print("Writing combined video to '%s', frames = %d / %d, duration = %.2f" % (filename, len(drone_frames), len(cam_frames), total_duration))

    dind = 0
    cind = 0
    dataind = 0

    for i in np.arange(start, stop, 1 / 30):
        while ((dind < (len(drone_frames) - 1) and drone_frames[dind][1] < i)):
            dind += 1
        while ((cind < (len(cam_frames) - 1) and cam_frames[cind][1] < i)):
            cind += 1
        while ((dataind < (len(data_frames) -1) and data_frames[dataind][1] < i)):
            dataind += 1

        combined = _make_combined_frame(drone_frames[dind][0], cam_frames[cind][0], data_frames[dataind][0])
        video.write(combined)
    video.release()

def wrap_send_command(tello, m):
    '''
    Injects monitoring around the function that sends commands to the drone, so the commands
    show up in the captured data.
    '''
    def wrap(f):
        def wrapped(command: str, timeout: int = Tello.RESPONSE_TIMEOUT) -> bool:
            print("Executing command: {}".format(command))
            m.record_command(command)
            return f(tello, command, timeout)
        return wrapped
    # The check is to prevent double wrapping
    if not getattr(tello, 'orig_send_control_command', None):
        setattr(tello, 'orig_send_control_command', Tello.__dict__['send_control_command'])
        setattr(tello, 'send_control_command', wrap(Tello.__dict__['send_control_command']))

@contextmanager
def monitored_tello(output_dir, webcam_src=1, fps=30):
    '''
    Usage example:
    with monitored_tello('data_output') as tello:
        tello.takeoff()
        tello.move_up(50)
        tello.land()
    '''

    if tello is None:
        tello = Tello()

    dvm = DroneVideoMonitor(output_dir, fps)
    cvm = WebcamVideoMonitor(output_dir, fps, webcam_src)
    dm = DataMonitor(output_dir, fps)
    combiner = CombinedPostprocessor(dvm, cvm, dm)

    m = DroneMonitor(webcam_src, [dvm, cvm, dm], [combiner])

    tello.connect()
    m.start(tello, fps)
    print("Monitoring...")

    try:
        yield (tello, m)
    finally:
        m.stop()
        tello.end()

@contextmanager
def suppress_stdout_stderr():
    """A context manager that redirects stdout and stderr to devnull"""
    with open(os.devnull, 'w') as fnull:
        with redirect_stderr(fnull) as err:
            yield err

class DroneVideoMonitor(Thread):
    def __init__(self, outdir, fps, outq=None):
        super().__init__()
        self.frames = []
        self.outdir = outdir
        self.fps = fps
        self.outq = outq

    def bind(self, start_time, tello, event):
        self.start_time = start_time
        self.tello = tello
        self.event = event

    def run(self):
        with suppress_stdout_stderr():
            frame_read = self.tello.get_frame_read()
            while not self.event.is_set():
                # slight lag on drone camera, fudge it by subtracting 0.25s
                fcopy = frame_read.frame.copy()
                self.frames.append((fcopy, time.time() - self.start_time - 0.25))
                if self.outq:
                    self.outq.put(self.frames[-1])

                time.sleep(1 / self.fps)

        _writeFrames(self.frames, os.path.join(self.outdir, "drone_video.mp4"))

class WebcamVideoMonitor(Thread):
    def __init__(self, outdir, fps, webcam_src, outq=None):
        super().__init__()
        self.frames = []
        self.outdir = outdir
        self.fps = fps
        self.webcam_src = webcam_src
        self.outq = outq

    def bind(self, start_time, _, event):
        self.start_time = start_time
        self.event = event

    def run(self):
        with suppress_stdout_stderr():
            cap = cv2.VideoCapture(self.webcam_src)
            while not self.event.is_set():
                ret, frame = cap.read()
                if not ret:
                    print("Read failed")
                    break
                fcopy = frame.copy()
                self.frames.append((fcopy, time.time() - self.start_time))
                if self.outq:
                    self.outq.put(self.frames[-1])

                time.sleep(1 / self.fps)
            cap.release()
        _writeFrames(self.frames, os.path.join(self.outdir, "cam_video.mp4"))

class CombinedPostprocessor:
    def __init__(self, outdir, drone_mon, cam_mon, data_mon):
        self.drone_mon = drone_mon
        self.cam_mon = cam_mon
        self.data_mon = data_mon
        self.outdir = outdir

    def process(self):
        _write_combined(self.drone_mon.frames, self.cam_mon.frames, self.data_mon.frames, os.path.join(self.outdir, "combined.mp4"))

class DataMonitor(Thread):
    def __init__(self, outdir, fps, outq=None):
        super().__init__()
        self.frames = []
        self.command_queue = []

        self.outdir = outdir
        self.fps = fps
        self.outq = outq

        self.datapoints = OrderedDict([
            ('time_s', lambda t: None),
            ('acceleration_x', lambda t: t.get_acceleration_x()),
            ('acceleration_y', lambda t: t.get_acceleration_y()),
            ('acceleration_z', lambda t: t.get_acceleration_z()),
            ('barometer', lambda t: t.get_barometer()),
            ('battery', lambda t: t.get_battery()),
            ('flight_time', lambda t: t.get_flight_time()),
            ('height_cm', lambda t: t.get_height()),
            ('to_floor_cm', lambda t: t.get_distance_tof()),
            ('pitch_degrees', lambda t: t.get_pitch()),
            ('roll_degrees', lambda t: t.get_roll()),
            ('speed_x', lambda t: t.get_speed_x()),
            ('speed_y', lambda t: t.get_speed_y()),
            ('speed_z', lambda t: t.get_speed_z()),
            ('temperature_c', lambda t: t.get_temperature()),
            ('yaw_degrees', lambda t: t.get_yaw()),
            ('command', lambda t: (self.command_queue.pop() if len(self.command_queue) else None))
        ])

    def bind(self, start_time, tello, event):
        self.start_time = start_time
        self.tello = tello
        self.event = event
        wrap_send_command(self.tello, self)

    def run(self):
        while not self.event.is_set():
            to_write = {}
            for k, get_fn in self.datapoints.items():
                to_write[k] = get_fn(self.tello)

            t = time.time() - self.start_time
            to_write['time_s'] = t
            self.frames.append((to_write, t))
            if self.outq:
                self.outq.put(self.frames[-1])

            time.sleep(1 / self.fps)

        with open(os.path.join(self.outdir, 'data.csv'), 'w', newline='') as csvfile:
            dwriter = csv.DictWriter(csvfile, fieldnames=self.datapoints)
            dwriter.writeheader()

            for frame in self.frames:
                dwriter.writerow(frame[0])

    def record_command(self, command):
        self.command_queue.append(command)

class DroneMonitor:
    def __init__(self, monitors, post_processors):
        self.monitors = [m for m in monitors if m is not None]
        self.post_processors = [p for p in post_processors if p is not None]
        self.event = Event()

    def start(self, tello, fps):
        tello.streamon()

        start_time = time.time()

        for m in self.monitors:
            m.bind(start_time, tello, self.event)
            m.event = self.event
            m.tello = tello
            m.start()
            print("sub-monitor started")

        # Ugly, but give the video capture some time to start
        time.sleep(5)

    def stop(self):
        self.event.set()
        for m in self.monitors:
            m.join()

        for p in self.post_processors:
            p.process()

