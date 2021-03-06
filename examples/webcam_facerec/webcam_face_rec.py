from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import cv2
import time
import traceback
import numpy as np
from collections import deque
import logging
import os

from gtts import gTTS
from pygame import mixer
from tempfile import TemporaryFile

import face_trigger

from face_trigger.model.deep.FaceRecognizer import FaceRecognizer
from face_trigger.process.post_process import FaceDetector, LandmarkDetector, FaceAlign
from face_trigger.utils.common import RepeatedTimer, clamp_rectangle

from configurator import setup_logging, setup_config


source = None  # reference to cv2.VideoCapture object
fps_counter = None  # repeated timer object
frame_count = 0  # frames ingested
fps = 0  # computed fps
sequence = 0  # sequence indicating consecutive face detections
landmarks = []  # list to hold the face landmarks across the batch
faces = []  # list to hold face bounding boxes across the batch
# queue holding information of the last fps counts; used to generate avg, fps
fps_queue = deque(maxlen=100)


def speak(unknown=False, person_name=None):
    """
    Speaks out the text fed to it.
    :param bool unknown: flag to indicate whether the person was unidentified
    :param str person_name: the name of the person. If unknown is set to TRue, no need to set this parameter.
    """
    voice_path = os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "voice")

    if not os.path.exists(voice_path):
        os.makedirs(voice_path)

    person_unknown_msg = "Person cannot be identified"
    person_id_msg_prefix = "Person identified as "
    try:
        tts = None
        if unknown is True:
            tts = gTTS(person_unknown_msg)
        else:
            msg = person_id_msg_prefix + \
                str(unicode(person_name, encoding='utf-8'))
            tts = gTTS(msg)

        mixer.init()
        sf = TemporaryFile()
        tts.write_to_fp(sf)
        sf.seek(0)
        mixer.music.load(sf)
        mixer.music.play()

        time.sleep(4)

    except Exception:
        raise


def run(config):
    """
    Main loop of the program

    :param config: a dict with default values for various configuration parameters
    :type config: dict
    """

    logger = logging.getLogger(__name__)

    global frame_count
    global source
    global fps_counter
    global fps
    global sequence
    global landmarks
    global faces

    # setup the configuration
    face_area_threshold = config.get("face_area_threshold", 0.25)
    camera_index = config.get("camera_index", 0)
    cam_height, cam_width = config.get(
        "cam_height", 640), config.get("cam_width", 640)
    batch_size = config.get("batch_size", 15)
    face_recognition_confidence_threshold = config.get(
        "face_recognition_confidence_threshold", 0.35)
    frame_skip_factor = config.get("frame_skip_factor", 8)
    unknown_class = config.get("unknown_class", -1)

    svm_model_path = config.get(
        "svm_model_path", "classifier.pkl")
    label_mapping_path = config.get(
        "label_mapping_path", "label_mapping.pkl")

    # print("{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n".format(
    #     face_area_threshold, camera_index, cam_height, cam_width, batch_size,
    #     face_recognition_confidence_threshold, frame_skip_factor, unknown_class,  svm_model_path, label_mapping_path))

    source = cv2.VideoCapture(index=camera_index)
    source.set(cv2.CAP_PROP_FRAME_WIDTH, cam_width)
    source.set(cv2.CAP_PROP_FRAME_HEIGHT, cam_height)

    print(source.get(cv2.CAP_PROP_FRAME_WIDTH), "x",
          source.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # init the fps counter object
    fps_counter = RepeatedTimer(interval=1.0, function=fps_count)

    # reference to face detector
    face_detector = FaceDetector(face_area_threshold=face_area_threshold)
    # reference to landmark detector
    landmark_detector = LandmarkDetector(
        predictor_path=None)
    # reference to face recognizer
    face_recognizer = FaceRecognizer(
        dnn_model_path=None, classifier_model_path=svm_model_path, label_map_path=label_mapping_path)

    # open the source if not opened already
    if not source.isOpened():
        source.open()

    # initialise the sequence count
    sequence = 0

    # start the fps counter
    fps_counter.start()

    # loop through the frames in the video feed
    while True:
        ret, frame = source.read()
        frame = cv2.flip(frame, 1)

        # increment frame count; for fps calculation
        frame_count += 1

        # only process every 'frame_skip_factor' frame
        if not frame_count % frame_skip_factor == 0:
            continue

        # convert to grayscale
        grayImg = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # equalize the histogram
        grayImg = cv2.equalizeHist(grayImg)

        # detect the largest face
        face = face_detector.detect(grayImg)

        # if a face was detected
        if face is not None:

            # increment sequence count
            sequence += 1

            # get bounding boxes
            # bb = clamp_rectangle(x1=face.left(), y1=face.top(
            # ), x2=face.right(), y2=face.bottom(), x2_max=grayImg.shape[0]-1, y2_max=grayImg.shape[1]-1)

            # draw a rectangle around the detected face
            cv2.rectangle(frame, (face.left(), face.top()),
                          (face.right(), face.bottom()), (255, 0, 255))

            # get the landmarks
            landmark = landmark_detector.predict(face, grayImg)

            # accumulate face and landmarks till we get a batch of batch_size
            if landmark is not None:
                faces.append(grayImg)
                landmarks.append(landmark)

            # recognize the face in the batch
            if len(faces) == batch_size:
                start_time = time.time()
                logger.debug("Start timestamp: {}".format(start_time))

                face_embeddings = face_recognizer.embed(
                    images=faces, landmarks=landmarks)

                predicted_identity = face_recognizer.infer(
                    face_embeddings, threshold=face_recognition_confidence_threshold, unknown_index=unknown_class)

                end_time = time.time()  # batch:100 s: ~1.5 sec; p:
                logger.debug("End time: {}. Runtime: {}".format(
                    end_time, (end_time-start_time)))

                if predicted_identity == unknown_class:
                    speak(unknown=True)
                else:
                    speak(unknown=False, person_name=predicted_identity)

                logger.info("Predicted identity: {}".format(
                    predicted_identity))

                # start a new face recognition activity
                start_over()

        else:
            # start a new face recognition activity, because noo face face was detected in the frame
            start_over()

        # get frame rate
        fps_text = "FPS:" + str(fps)
        cv2.putText(frame, fps_text, (1, 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255))

        cv2.imshow("output", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cleanup()


def cleanup():
    """
    Runs cleanup services
    """
    global source
    global fps_counter
    global fps_queue

    source.release()
    cv2.destroyAllWindows()
    fps_counter.stop()

    print("Avg. FPS:", np.mean(np.array(fps_queue)))


def start_over():
    """
    Resets the following variables, if there is a discontinuity in detecting a face among consecutive frames:
    1. faces - all detected faces
    2. landmarks - facial landmarks of the detected faces
    3. sequence - the counter for the sequence
    """

    global sequence
    global landmarks
    global faces

    sequence = 0
    faces = []
    landmarks = []


def fps_count():
    """
    Outputs the frames per second
    """
    global frame_count
    global fps
    global fps_queue

    fps = frame_count/1.0
    fps_queue.append(fps)

    frame_count = 0


import logging
if __name__ == "__main__":

    # logging.basicConfig(level=logging.DEBUG)
    setup_logging()
    config = setup_config()

    try:
        run(config=config)
    except Exception as e:
        print(e)
        traceback.print_exc()
    finally:
        cleanup()
