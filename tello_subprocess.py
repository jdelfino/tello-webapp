
from threading import Thread, Event
import multiprocessing as mp
from contextlib import contextmanager
import queue
import os
import time
import logging
import asyncio

from djitellopy import Tello

import monitor

log = logging.getLogger(__name__)

WEBCAM_SRC = 0

def controller(command_pipe, interrupt_pipe, drone_video_queue, cam_video_queue, data_queue, fps):
	## todo: support combined video on the fly
	## todo: output dir arg is weird

	event = Event()

	dvm = None
	cvm = None
	dm = None
	combiner = None

	if drone_video_queue is not None:
		dvm = DroneVideoMonitor(output_dir, fps, drone_video_queue)

	if cam_video_queue is not None:
		cvm = WebcamVideoMonitor(output_dir, fps, webcam_src, cam_video_queue)

	if data_queue is not None:
		dm = DataMonitor(output_dir, fps, data_queue)

	if drone_video_queue is not None and cam_video_queue is not None and data_queue is not None:
		combiner = CombinedPostprocessor(dvm, cvm, dm)

	m = DroneMonitor(webcam_src, [dvm, cvm, dm], ([combiner] if combiner is not None else []))

	tello = Tello()
	tello.connect()
	m.start(tello, fps)
	print("monitoring has started")

	try:
		while not event.is_set():
			ready = mp.connection.wait([command_pipe, interrupt_pipe], 1)
			if len(ready) == 0:
				continue

			command = ''

			interrupt = list(filter(lambda x: x.fileno() == interrupt_pipe.fileno(), ready))
			if len(interrupt) > 0:
				p = interrupt[0]
			else:
				p = ready[0]

			command = p.recv()

			if command == 'emergency':
				tello.emergency()
				event.set()
			elif command == 'land':
				tello.land()
				event.set()
			elif command == 'takeoff':
				tello.takeoff()
			else:
				tello.send_control_command(command)
			p.send('ok')

		dvt.join()
		cvt.join()
		dt.join()
	finally:
		m.stop()
		tello.end()

class Flier:
	def __init__(self, command_pipe, interrupt_pipe):
		self.command_pipe = command_pipe
		self.interrupt_pipe = interrupt_pipe

	# todo: lazy, provide a real interface
	def command(self, command):
		print("putting command {}".format(command))
		self.command_pipe.send(command)
		f = self.command_pipe.recv()
		if f != "ok":
			print("Got an error: {}".format(f))

	def emergency(self):
		self.interrupt_pipe.send('emergency')
		self.interrupt_pipe.recv()

	def stop(self):
		self.interrupt_pipe.send('stop')
		self.interrupt_pipe.recv()

class QueueDispatcher(Thread):
	def __init__(self, queue, handle_fn, flier, event):
		super().__init__()

		self.handle_fn = handle_fn
		self.flier = flier
		self.event = event
		self.queue = queue

	async def run(self):
		while True:
			try:
				d = self.queue.get(True, 1)
				self.handle_fn(d, self.flier)
			except queue.Empty:
				continue
			except Exception as e:
				log.exception("Exception in QueueDispatcher")
				raise

class TelloSubprocess:

	def is_flying(self):
		return self.f is not None

	@contextmanager
	def start_flight(
		self,
		fps,
		drone_video = None,
		webcam_video = None,
		data_file = None,
		drone_video_handler = None,
		cam_video_handler = None,
		data_handler = None):

		ctx = mp.get_context('spawn')

		cmd_here, cmd_there = ctx.Pipe()
		interrupt_here, interrupt_there = ctx.Pipe()
		dv_dispatcher = None
		c_dispatcher = None
		data_dispatcher = None

		self.f = Flier(cmd_here, interrupt_here)

		event = Event()
		if drone_video_handler is not None:
			dv_dispatcher = QueueDispatcher(ctx.Queue(), drone_video_handler, self.f, event)
			dv_dispatcher.start()
		if cam_video_handler is not None:
			c_dispatcher = QueueDispatcher(ctx.Queue(), cam_video_handler, self.f, event)
			c_dispatcher.start()
		if data_handler is not None:
			data_dispatcher = QueueDispatcher(ctx.Queue(), data_video_handler, self.f, event)
			data_dispatcher.start()

		p = ctx.Process(target=controller, args=(
			cmd_there,
			interrupt_there,
			dv_dispatcher.queue if dv_dispatcher is not None else None,
			c_dispatcher.queue if c_dispatcher is not None else None,
			 data_dispatcher.queue if data_dispatcher is not None else None,
			fps))

		p.start()

		yield self.f

		event.set()
		dv_dispatcher.join()
		c_dispatcher.join()
		data_dispatcher.join()

		self.f.stop()
		p.join()
		self.f = None

	def emergency(self):
		if self.f:
			self.f.emergency()

	def stop(self):
		if self.f:
			self.f.stop()


class TelloThread:

	@contextmanager
	def start_flight(
		self,
		fps,
		output_dir):

		os.makedirs(output_dir, exist_ok=True)

		self.tello = Tello(retry_count=2)
		self.tello.connect()
		self.tello.streamon()

		event = Event()
		start_time = time.time()

		dvm = monitor.VideoMonitor(self.tello.get_udp_video_address(), start_time, fps, event)
		cvm = monitor.VideoMonitor(WEBCAM_SRC, start_time, fps, event)
		dm = monitor.DataMonitor(start_time, fps, self.tello, event)

		drone_frame_accum = monitor.FrameAccumulator().attach(dvm)
		cam_frame_accum = monitor.FrameAccumulator().attach(cvm)
		data_accum = monitor.FrameAccumulator().attach(dm)

		drone_video_writer = monitor.VideoWriter(output_dir + '/drone_video.mp4', fps).attach(dvm)
		cam_video_writer = monitor.VideoWriter(output_dir + '/cam_video.mp4', fps).attach(cvm)
		data_writer = monitor.DataWriter(os.path.join(output_dir, 'data.csv')).attach(dm)

		threads = [x for x in [
			dvm, cvm, dm,
			drone_frame_accum, cam_frame_accum, data_accum,
			drone_video_writer, cam_video_writer, data_writer
		] if x is not None]
		combiner = monitor.CombinedPostprocessor(output_dir, drone_frame_accum, cam_frame_accum, data_accum)

		for t in threads:
			t.start()

		time.sleep(5)
		try:
			print("yielding")
			yield (self.tello, dvm, cvm, dm)

		except Exception as e:
			log.exception("Exception in flight execution")
			raise

		finally:
			event.set()
			for t in threads:
				t.join()

			combiner.process()
			print("monitor finished")

			self.tello.end()
			print("tello ended")
			self.tello = None