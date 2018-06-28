from __future__ import division
import os
import cv2
import tqdm
import numpy as np

from Dataset import Dataset

"""
Trains a face recognition model based on the given dataset and algorithm
"""


class FaceRecognizer():

    def __init__(self):
        """
        Instantiate a FaceRecognizer object
        """

        self.model = cv2.face.LBPHFaceRecognizer_create()

    def train(self, images, labels):
        """
        Train the recognizer on the training set

        :param images: the images to train on
        :type images: numpy.ndarray shape: (num_images, image_height, image_width)
        :param labels: the labels/subjects the corresponding faces belong to
        :type labels: numpy.ndarray shape: (num_images,)
        """

        self.model.train(images, labels)

    def predict(self, images):
        """
        Predicts the labels of the given images

        :param images: the images to test on
        :type images: numpy.ndarray shape: (num_images, image_height, image_width)
        :return predictions: the predicted labels
        :rtype predictions: array
        """

        predictions = []
        for i in tqdm.trange(0, len(images)):
            prediction = self.model.predict(images[i])
            predictions.append(prediction)
            i += 1

        return predictions

    def evaluate(self, predictions, ground_truths):

        assert(len(predictions) == len(ground_truths))

        true_positive = np.count_nonzero(
            np.equal(ground_truths, np.array(predictions)[:, 0]))

        precision_perc = true_positive/len(predictions)*100

        print "Precision@1:", true_positive, "/", len(
            predictions), "(", precision_perc, "%)"

    def save(self, name):

        self.model.write(name)

    def load(self, name):

        self.model.read(name)