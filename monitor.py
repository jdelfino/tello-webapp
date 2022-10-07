import cv2
import logging
import time
from threading import Thread, Event
import queue
import csv
from collections import OrderedDict
import numpy as np
import os
import math
from djitellopy import Tello
from contextlib import contextmanager,redirect_stderr,redirect_stdout
import multiprocessing as mp
import logging
import asyncio

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

class VideoMonitor(Thread):
	def __init__(self, address, start_time, fps, event):
		super().__init__()
		self.fps = fps
		self.queues = []
		self.address = address
		self.event = event
		self.start_time = start_time

	def register_output(self, q):
		self.queues.append(q)

	def run(self):
		cap = cv2.VideoCapture(self.address)
		next_time = time.time() + (1/self.fps)
		try:
			while not self.event.is_set():
				grabbed, frame = cap.read()

				if not grabbed:
					print("VM {} grab failed".format(self.address))
					break

				t = time.time()
				if t > next_time:
					next_time = time.time() + (1/self.fps)
					for q in self.queues:
						q.put([frame, time.time() - self.start_time])
		finally:
			if cap:
				cap.release()

		for q in self.queues:
			print("Video monitor dropping none")
			q.put(None)

class DataMonitor(Thread):
	def __init__(self, start_time, fps, tello, event):
		super().__init__()
		self.command_queue = []
		self.fps = fps
		self.event = event
		self.queues = []
		self.start_time = start_time
		self.tello = tello

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

	def register_output(self, q):
		self.queues.append(q)

	def run(self):
		wrap_send_command(self.tello, self)
		while not self.event.is_set():
			data_frame = {}
			for k, get_fn in self.datapoints.items():
				data_frame[k] = get_fn(self.tello)

			t = time.time() - self.start_time
			data_frame['time_s'] = t

			for q in self.queues:
				q.put([data_frame, time.time() - self.start_time])
			time.sleep(1 / self.fps)

		for q in self.queues:
			q.put(None)

	def record_command(self, command):
		self.command_queue.append(command)

class CombinedPostprocessor:
	def __init__(self, outdir, drone_accum, cam_accum, data_accum):
		self.drone_accum = drone_accum
		self.cam_accum = cam_accum
		self.data_accum = data_accum
		self.outdir = outdir

	def process(self):
		_write_combined(self.drone_accum.frames, self.cam_accum.frames, self.data_accum.frames, os.path.join(self.outdir, "combined.mp4"))

class FrameAccumulator(Thread):
	def __init__(self):
		super().__init__()
		self.frames = []
		self.in_queue = queue.Queue()

	def attach(self, frame_generator):
		frame_generator.register_output(self.in_queue)
		return self

	def run(self):
		while True:
			frame = self.in_queue.get()
			if frame is None:
				break

			self.frames.append(frame)

class VideoWriter(Thread):
	def __init__(self, filename, fps):
		super().__init__()
		self.filename = filename
		self.fps = fps
		self.in_queue = queue.Queue()

	def attach(self, frame_generator):
		frame_generator.register_output(self.in_queue)
		return self

	def run(self):
		writer = None
		while True:
			frame = self.in_queue.get()
			if frame is None:
				break

			if writer is None:
				height, width, _ = frame[0].shape
				writer = cv2.VideoWriter(self.filename, cv2.VideoWriter_fourcc(*'avc1'), self.fps, (width, height))

			cv2.putText(frame[0], "%.2f" % frame[1], (50, 75), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 255), 4)
			writer.write(frame[0])

		if writer:
			writer.release()

class DataWriter(Thread):
	def __init__(self, filename):
		super().__init__()
		self.filename = filename
		self.dwriter = None
		self.outfile = None
		self.in_queue = queue.Queue()

	def attach(self, frame_generator):
		frame_generator.register_output(self.in_queue)
		return self

	def run(self):
		with open(self.filename, 'w', newline='') as outfile:
			dwriter = None
			while True:
				frame = self.in_queue.get()
				if frame is None:
					break

				if dwriter is None:
					dwriter = csv.DictWriter(outfile, fieldnames=frame[0].keys())
					dwriter.writeheader()

				dwriter.writerow(frame[0])


class DroneMonitor:
	def __init__(self, processors):
		self.processors = processors

	async def start(self, tello):
		tello.streamon()

		for p in self.processors:
			p.start()

		# Ugly, but give the video capture some time to start
		time.sleep(5)

	async def stop(self):
		for p in self.processors:
			p.join()

