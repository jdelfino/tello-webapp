import numpy as np
import cv2
import sys
import os
import time
import tellomonitor.monitor as monitor
import queue

DATA_PATH = "static/yolo"
LABELS_FILE = "coco.names"
#WEIGHTS_FILE = "yolov3.weights"
#CFG_FILE = "yolov3.cfg"
WEIGHTS_FILE = "yolov3-tiny.weights"
CFG_FILE = "yolov3-tiny.cfg"
CONFIDENCE = 0.5
THRESHOLD = 0.3

class DetectedObject:
	def __init__(self, center_x, center_y, width, height, class_id, label, confidence, colors):
		self.center_x = center_x
		self.center_y = center_y
		self.width = width
		self.height = height
		self.left_x = int(center_x - (width / 2))
		self.top_y = int(center_y - (height / 2))
		self.class_id = class_id
		self.label = label
		self.confidence = confidence
		self.color = [int(c) for c in colors[class_id]]
		self.special_color = [int(c) for c in colors[-1]]

	def box(self):
		return [self.left_x, self.top_y, self.width, self.height]

	def draw_on_image(self, image, special_color=False):
		cv2.rectangle(
			image,
			(self.left_x, self.top_y),
			(self.left_x + self.width, self.top_y + self.height),
			self.special_color if special_color else self.color, 2)

		text = "{}: {:.4f}".format(self.label, self.confidence)
		cv2.putText(
			image, text,
			(self.left_x, self.top_y - 5),
			cv2.FONT_HERSHEY_SIMPLEX,
			0.5, self.special_color if special_color else self.color, 2)


class YoloDetector(monitor.BaseImageProcessor):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		with open(os.path.join(DATA_PATH, LABELS_FILE)) as labels_file:
			self.labels = labels_file.read().strip().split("\n")

		weightsPath = os.path.join(DATA_PATH, WEIGHTS_FILE)
		configPath = os.path.join(DATA_PATH, CFG_FILE)

		self.net = cv2.dnn.readNetFromDarknet(configPath, weightsPath)
		print("Loaded YOLO v3")

		self.ln = self.net.getLayerNames()
		print("1 {}".format(self.ln))
		self.ln = [self.ln[i - 1] for i in self.net.getUnconnectedOutLayers()]
		print("2 {}".format(self.ln))

		np.random.seed(42)
		self.colors = np.random.randint(0, 255, size=(len(self.labels) + 1, 3), dtype="uint8")

	def detect(self, image):
		if not self.tello.is_flying:
			return

		real_start = time.time()
		(H, W) = image.shape[:2]

		blob = cv2.dnn.blobFromImage(image, 1 / 255.0, (320, 320),
			swapRB=True, crop=False)
		self.net.setInput(blob)
		start = time.time()
		layerOutputs = self.net.forward(self.ln)
		end = time.time()

		#print("[INFO] YOLO took {:.6f} seconds".format(end - start))

		boxes = []
		confidences = []
		classIDs = []
		detected_objects = []
		# loop over each of the layer outputs
		for output in layerOutputs:
			# loop over each of the detections
			for detection in output:
				# extract the class ID and confidence (i.e., probability) of
				# the current object detection
				scores = detection[5:]
				classID = np.argmax(scores)
				confidence = scores[classID]
				# filter out weak predictions by ensuring the detected
				# probability is greater than the minimum probability
				if confidence > CONFIDENCE:
					# scale the bounding box coordinates back relative to the
					# size of the image
					box = detection[0:4] * np.array([W, H, W, H])
					(centerX, centerY, width, height) = box.astype("int")
					# update our list of bounding box coordinates, confidences,
					# and class IDs
					detected_objects.append(
						DetectedObject(centerX, centerY, int(width), int(height), classID,
							self.labels[classID], float(confidence), self.colors))

		idxs = cv2.dnn.NMSBoxes([x.box() for x in detected_objects], [x.confidence for x in detected_objects], CONFIDENCE, THRESHOLD)
		if len(idxs) == 0:
			return

		to_display = [detected_objects[i] for i in idxs.flatten()]
		#matches = to_display
		matches = [o for o in to_display if o.label == 'person']

		if len(matches) == 0:
			return

		matches = sorted(matches, key=lambda x: x.width, reverse=True)

		for idx, obj in enumerate(matches):
			if idx == 0:
				obj.draw_on_image(image, True)
			else:
				obj.draw_on_image(image)

		#print("[INFO] Full detection took {:.6f} seconds".format(time.time() - real_start))

		self.follow_banana(matches[0], W, H)

	def follow_banana(self, banana, img_width, img_height):
		vert_img_center = img_width / 2
		vert_center_offset = banana.center_x - vert_img_center
		vert_degrees_off_center = int(45 * (vert_center_offset / vert_img_center))

		horz_img_center = img_height / 4
		horz_center_offset = banana.top_y - horz_img_center
		horz_degrees_off_center = int(45 * (horz_center_offset / horz_img_center))

		if abs(horz_degrees_off_center) > abs(vert_degrees_off_center) and abs(horz_degrees_off_center) > 10:
			if horz_center_offset < 0:
				print("up 20")
				if MOVE:
					self.move(lambda: self.tello.move_up(20))
			else:
				print("down 20")
				if MOVE:
					self.move(lambda: self.tello.move_down(20))

		elif abs(vert_degrees_off_center) > 10:
			if vert_degrees_off_center < 0:
				print("ccw {}".format(vert_degrees_off_center * -1))
				if MOVE:
					self.move(lambda: self.tello.rotate_counter_clockwise(vert_degrees_off_center * -1))
			else:
				print("cw {}".format(vert_degrees_off_center * -1))
				if MOVE:
					self.move(lambda: self.tello.rotate_clockwise(vert_degrees_off_center))

MOVE=True
monitor.fly_with_image_processing(YoloDetector, fps=15, takeoff=MOVE)
