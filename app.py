from flask import Flask, render_template, Response, send_from_directory
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

@app.route('/flights/<path:path>')
def send_flight(path):
    return send_from_directory('flights', path)

def socket_emit_drone_video(frame):
	jpg = cv2.imencode('.jpg', frame[0])[1].tobytes()
	encoded_jpg = base64.encodebytes(jpg).decode("utf-8")
	socketio.emit("VS", encoded_jpg)

class FrameHandler(Thread):
	def __init__(self, handle_fn):
		super().__init__()
		self.in_queue = queue.Queue()
		self.handle_fn = handle_fn

	def attach(self, frame_generator):
		frame_generator.register_output(self.in_queue)
		return self

	def run(self):
		while True:
			frame = self.in_queue.get()
			if frame is None:
				break
			self.handle_fn(frame)

def fly(lines):
	global t
	now = time.strftime("%Y-%m-%d_%H-%M-%S")

	outdir = 'flights/{}'.format(now)
	try:
		with t.start_flight(
			output_dir=outdir,
			fps = 15) as (tello, drone_video_monitor, cam_video_monitor, data_monitor):

			f = FrameHandler(lambda x: socketio.emit('data', x[0]))
			f.attach(data_monitor)
			f.start()

			f2 = FrameHandler(socket_emit_drone_video)
			f2.attach(drone_video_monitor)
			f2.start()

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
			'''
			print("sending takeoff")
			tello.takeoff()
			print("takeoff finished")
			tello.move_up(50)
			tello.land()
			'''
		socketio.emit('flight_finished', {
			'drone_video': outdir + '/drone_video.mp4',
			'cam_video': outdir + '/cam_video.mp4',
			'data_csv': outdir + '/data.csv'
		})
	except Exception as e:
		log.exception("Flight failed")
		socketio.emit('flight_failed', {'msg': str(e)})

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
	socketio.run(app, host="0.0.0.0")



'''
class FrameBuffer(Thread):
	def __init__(self):
		super().__init__()
		self.in_queue = queue.Queue()

	def attach(self, frame_generator):
		frame_generator.register_output(self.in_queue)
		return self

	def run(self):
		pass

	def gen(self):
		while True:
			frame = self.in_queue.get()
			if frame is None:
				break
			(flag, jpg) = cv2.imencode('.jpg', frame[0])
			yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + bytearray(jpg) + b'\r\n')


fb = FrameBuffer()
@app.route('/drone_video')
def drone_video():
       global vf
       return Response(fb.gen(), mimetype="multipart/x-mixed-replace; boundary=frame")
'''