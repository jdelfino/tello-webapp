from flask import Flask, render_template, Response, send_from_directory
from flask_socketio import SocketIO, emit
import time
from threading import Thread
import logging
import base64
import cv2
import queue
import sys
import subprocess

import tellomonitor.monitor as monitor

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
logging.getLogger('werkzeug').setLevel(logging.WARN)

app = Flask(__name__)
socketio = SocketIO(app)
program_thread = Thread()
tello_handle = None

@app.route('/')
def index():
	return render_template('index.html')

@app.route('/flights/<path:path>')
def send_flight(path):
    return send_from_directory('flights', path)

def socket_emit_drone_video(frame):
	jpg = cv2.imencode('.jpg', frame[0])[1].tobytes()
	encoded_jpg = base64.encodebytes(jpg).decode("utf-8")
	socketio.emit("VS", encoded_jpg)


class FrameHandler(monitor.BaseProcessor):
	def __init__(self, handle_fn):
		super().__init__()
		self.in_queue = queue.Queue()
		self.handle_fn = handle_fn

	def handle_frame(self, frame):
		self.handle_fn(frame)


def fly(lines):
	global tello_handle
	now = time.strftime("%Y-%m-%d_%H-%M-%S")

	outdir = 'flights/{}'.format(now)
	try:
		with monitor.start_flight(
			output_dir = outdir,
			fps = 30) as (tello, drone_video_monitor, cam_video_monitor, data_monitor):

			global tello_handle
			tello_handle = tello
			data_monitor.attach(FrameHandler(lambda x: socketio.emit('data', x[0])))
			drone_video_monitor.attach(FrameHandler(socket_emit_drone_video))

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

		socketio.emit('flight_finished', {
			'drone_video': outdir + '/drone_video.mp4',
			'cam_video': outdir + '/cam_video.mp4',
			'data_csv': outdir + '/data.csv'
		})
	except Exception as e:
		log.exception("Flight failed")
		socketio.emit('flight_failed', {'msg': str(e)})
	finally:
		tello_handle = None

	print("Finished")

@socketio.on('launch')
def launch(json):
	lines = json['moves'].splitlines()

	global program_thread
	if not program_thread.is_alive():
		program_thread = Thread(target=fly, args=(lines, ))
		program_thread.start()
	print("launched")

@socketio.on('stop')
def abort(json):
	global tello_handle
	if tello_handle:
		tello_handle.stop()
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
	time.sleep(10)
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

