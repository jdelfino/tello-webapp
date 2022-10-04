from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import time
from threading import Thread
import logging
import base64
import cv2
import queue

import tello_subprocess

logging.basicConfig(level=logging.DEBUG)
log = logging.getLogger(__name__)
logging.getLogger('werkzeug').setLevel(logging.WARN)

app = Flask(__name__)
socketio = SocketIO(app)
program_thread = Thread()

t = tello_subprocess.TelloThread()

@app.route('/')
def index():
	return render_template('index.html')

def handle_drone_video(frame, flier):
	jpg = cv2.imencode('.jpg', frame[0])[1].tobytes()
	encoded_jpg = base64.encodebytes(jpg).decode("utf-8")
	socketio.emit("VS", encoded_jpg)
	#socketio.emit('VS',encoded_jpg);
	#print("emitted")
	#print("got drone frame {}".format(frame[1]))

def handle_webcam_video(frame, flier):
	#print("got webcam frame {}".format(frame[1]))
	pass

def handle_data(data, flier):
	#print("got data frame {}".format(data[0]))
	pass

def fly():
	global t
	with t.start_flight(
		output_dir='outdir',
		fps = 15,
		drone_video_handler=handle_drone_video,
		cam_video_handler=handle_webcam_video,
		data_handler=handle_data) as (tello, _):

		'''
		print("sending takeoff")
		tello.takeoff()
		print("takeoff finished")
		tello.move_up(50)
		tello.land()
		'''
		while True:
			time.sleep(1)

	print("Finished")

@socketio.on('launch')
def launch(json):
	global program_thread
	if not program_thread.is_alive():
		program_thread = Thread(target=fly)
		program_thread.start()
	print("launched")

@socketio.on('stop')
def abort(json):
	t.stop()
	print("stopped")

@socketio.on('emergency_stop')
def abort(json):
	t.emergency()
	print("emergency stopped")

@socketio.on('connect')
def test_connect():
	global t
	emit('after connect',  {'data':'Lets dance'})

if __name__ == '__main__':
	print("Serving...")
	socketio.run(app)