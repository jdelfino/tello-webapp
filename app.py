from flask import Flask, render_template, Response, send_from_directory
from flask_socketio import SocketIO, emit
import time
from threading import Thread
import logging
import base64
import cv2
import csv
import queue
import sys
import subprocess
import os

import tellomonitor.monitor as monitor

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
logging.getLogger('werkzeug').setLevel(logging.WARN)

app = Flask(__name__)
socketio = SocketIO(app)
program_thread = Thread()
tello_handle = None

DRONE_VIDEO_FILE = 'drone_video.mp4'
CAM_VIDEO_FILE = 'cam_video.mp4'
DATA_FILE = 'data.csv'
COMBINED_VIDEO_FILE = 'combined.mp4'

@app.route('/')
def index():
	return render_template('index.html')

@app.route('/height_driver')
def height_driver():
	return render_template('height_driver.html')

@app.route('/flights/<date>')
def review_flight(date):
	data = []
	with open(os.path.join('flights', date, DATA_FILE), 'r') as csvfile:
		data = list(csv.reader(csvfile, delimiter=','))

	return render_template('review_data.html', date=date, graph_data=data)

@app.route('/flights/<date>/<filename>')
def send_flight(date, filename):
    return send_from_directory(os.path.join('flights', date), filename)

def socket_emit_drone_video(frame):
	jpg = cv2.imencode('.jpg', frame[0])[1].tobytes()
	encoded_jpg = base64.encodebytes(jpg).decode("utf-8")
	socketio.emit("drone_video_frame", encoded_jpg)


class FrameHandler(monitor.BaseProcessor):
	def __init__(self, handle_fn):
		super().__init__()
		self.in_queue = queue.Queue()
		self.handle_fn = handle_fn

	def handle_frame(self, frame):
		self.handle_fn(frame)


def drive(lines, tello):
	for line in lines:
		line = line.strip()
		if line.startswith('wait'):
			amt = line.split(' ')[1]
			print("Sleeping {}".format(int(amt)))
			time.sleep(int(amt))
		elif line.startswith('takeoff'):
			tello.takeoff()
		elif line.startswith('land'):
			tello.land()
		else:
			tello.send_control_command(line)

def drone_keepalive(tello):
	tello.takeoff()
	while tello.is_flying:
		try:
			tello.send_command_nolog("moff")
		except Exception:
			log.exception("Keepalive failed")
			break
		time.sleep(10)

def setup_standard_processors(
	output_dir, fps,
	record_drone, record_webcam, stream_drone_video,
	drone_video_monitor, cam_video_monitor, data_monitor):

	os.makedirs(output_dir, exist_ok=True)

	print("Drone: {} cam {} stream drone {}".format(record_drone, record_webcam, stream_drone_video))
	# write data to disk
	if record_drone:
		drone_video_monitor.attach(monitor.VideoWriter(os.path.join(output_dir, DRONE_VIDEO_FILE), fps))
	if record_webcam:
		cam_video_monitor.attach(monitor.VideoWriter(os.path.join(output_dir, CAM_VIDEO_FILE), fps))
	data_monitor.attach(monitor.DataWriter(os.path.join(output_dir, DATA_FILE)))

	# make a combined video of drone, camera, and data and write to disk
	if record_drone and record_webcam:
		combined_writer = monitor.CombinedWriter(os.path.join(output_dir, COMBINED_VIDEO_FILE))
		drone_video_monitor.attach(combined_writer)
		cam_video_monitor.attach(combined_writer)
		data_monitor.attach(combined_writer)

	# stream drone video to client
	if stream_drone_video:
		drone_video_monitor.attach(FrameHandler(socket_emit_drone_video))

	# stream drone data to client
	data_monitor.attach(FrameHandler(lambda x: socketio.emit('data', x[0])))

def fly(lines, wait, record_drone, record_webcam, stream_drone_video, fps=30):
	global tello_handle
	outdir = os.path.join('flights', time.strftime("%Y-%m-%d_%H-%M-%S"))

	try:
		setup = lambda x,y,z: setup_standard_processors(
			outdir, fps, record_drone, record_webcam, stream_drone_video, x, y, z)

		with monitor.start_flight(setup, fps) as tello:
			# keep global handle to support stop/emergency stop
			tello_handle = tello

			if wait:
				drone_keepalive(tello)
			elif lines:
				drive(lines, tello)

		socketio.emit('flight_finished', {
			'drone_video': os.path.join(outdir, DRONE_VIDEO_FILE),
			'cam_video': os.path.join(outdir, CAM_VIDEO_FILE),
			'data_csv': os.path.join(outdir, DATA_FILE)
		})

	except Exception as e:
		log.exception("Flight failed")
		socketio.emit('flight_failed', {'msg': str(e)})
	finally:
		tello_handle = None

	print("Finished")

@socketio.on('launch')
def launch(json):

	lines = json.get('moves', "").splitlines()
	wait = json.get('wait', False)
	record_webcam = json.get('record_webcam', False)
	record_drone = json.get('record_drone', False)
	stream_drone_video = json.get('stream_drone_video', False)

	global program_thread
	if not program_thread.is_alive():
		program_thread = Thread(target=fly, args=(lines, wait, record_drone, record_webcam, stream_drone_video))
		program_thread.start()
	print("launched")

@socketio.on('move')
def move(json):
	global tello_handle
	if tello_handle:
		tello_handle.send_control_command(json['command'])
		print("sent command {}".format(json['command']))

@socketio.on('stop')
def abort(json):
	global tello_handle
	if tello_handle:
		tello_handle.land()
		print("stopped")

@socketio.on('emergency_stop')
def abort(json):
	global tello_handle
	if tello_handle:
		tello_handle.emergency()
		print("emergency stopped")

@socketio.on('connect')
def test_connect():
	emit('after connect',  {'data':'Lets dance'})

def update_wifi_status():
	time.sleep(5)
	while True:
		ap = None
		if sys.platform == 'linux':
			ap = subprocess.check_output(['iwgetid', 'wlan1', '--raw'], text=True).strip()
		elif sys.platform == 'darwin':
			info = subprocess.check_output(['/System/Library/PrivateFrameworks/Apple80211.framework/Resources/airport', '-I'], text=True).split('\n')
			ssid_line = [x.strip() for x in info if ' SSID:' in x]
			if len(ssid_line):
				ap = ssid_line[0].split(':')[1].strip()
		socketio.emit('wifi_status', {'ssid': ap})
		time.sleep(5)

if __name__ == '__main__':
	print("Serving...")
	t = Thread(target=update_wifi_status)
	t.start()
	socketio.run(app, host="0.0.0.0")

