from keras.models import load_model
from PIL import Image, ImageOps
import numpy as np

import cv2
from djitellopy import Tello
import logging
import time
from threading import Thread
import queue
from PIL import Image

from tello_subprocess import TelloThread

# Load the model
model = load_model('keras_model.h5')

def check_fruit(frame):
	print("Checking fruit")
	cv2.imwrite("fruit.png", frame)
	# Create the array of the right shape to feed into the keras model
	# The 'length' or number of images you can put into the array is
	# determined by the first position in the shape tuple, in this case 1.
	data = np.ndarray(shape=(1, 224, 224, 3), dtype=np.float32)
	# Replace this with the path to your image
	image = Image.open('fruit.png')
	#resize the image to a 224x224 with the same strategy as in TM2:
	#resizing the image to be at least 224x224 and then cropping from the center
	size = (224, 224)
	image = ImageOps.fit(image, size, Image.ANTIALIAS)
	#turn the image into a numpy array
	image_array = np.asarray(image)
	# Normalize the image
	normalized_image_array = (image_array.astype(np.float32) / 127.0) - 1
	# Load the image into the array
	data[0] = normalized_image_array
	# run the inference
	prediction = model.predict(data)
	#print(prediction)

	maxi = max(prediction)
	if np.argmax(prediction) == 1:
		print("**** Banana with confidence " + str(np.amax(prediction)))
		return True
	else:
		print("**** Nothing with confidence " + str(np.amax(prediction)))
		return False

def handle_drone_video(data, tello, q):
	print("got drone frame {}".format(data[1]))
	#q.put(data[0])
	img = Image.fromarray(data[0], 'RGB')
	img.show()

	#cv2.imshow('dv', data[0])
	#cv2.waitKey(1)
	c = check_fruit(data[0])
	if(c):
		tello.move_back(50)
		tello.rotate_clockwise(180)

t = TelloThread()


q = queue.Queue()
with t.start_flight(
	output_dir='outdir',
	fps = 1,
	drone_video_handler=lambda d,t: handle_drone_video(d, t, q)
	#cam_video_handler=handle_webcam_video,
	#data_handler=handle_data
	) as (tello, _):

	#tello.takeoff()

	i = 0
	while i < 10:
		f = q.get()
		#cv2.imshow('dv', f)
		#cv2.waitKey(1)
		#tello.rotate_counter_clockwise(1)
		#tello.rotate_clockwise(1)
		i += 1

	#tello.land()

