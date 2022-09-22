from typing import Literal
import numpy as np
import tensorflow as tf
from tensorflow.keras import Model, Sequential
from tensorflow.keras.layers import Conv1D, Conv1DTranspose, Flatten
from tensorflow.keras.optimizers import Adam
from sklearn.model_selection import train_test_split
from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier

from datasets import load_arrhythmia_dataset, load_PTB_dataset
from utils import upsample, get_debug_data, set_seeds

DEBUG = False
UPSAMPLE = False
VALIDATION_SPLIT = 0.1
BATCH_SIZE = 128
EPOCHS = 3
EARLY_STOPPING_PATIENCE = 2
FILTER_SIZE = 3
SEED = 1337


class AutoencoderTree:
    """Autoencoder model combined with decision tree classifier.

    Uses an autoencoder to project signals into a latent space of
    lower dimensionality. The features generated by the encoder are
    passed to a classifier employing the Extremely Randomized Trees
    algorithm for constructing an ensemble of decision trees.

    Attributes:
        dataset: Literal specifying which dataset to use.
        train_ae_on: Trains the autoencoder on both datasets if set
            to 'full', and on the same dataset as used for evaluation
            otherwise.
    """

    def __init__(self, dataset: Literal['mithb', 'ptbdb'],
                 train_ae_on: Literal['full', 'same']):
        set_seeds(SEED)
        self.train_ae_on = train_ae_on

        self.init_autoencoder()
        self.load_data(dataset)
        self.clf = ExtraTreesClassifier(n_estimators=100)

    def init_autoencoder(self):
        input_shape = (188, 1)

        self.autoencoder = Sequential([
            Conv1D(8,
                   FILTER_SIZE,
                   strides=2,
                   activation='relu',
                   padding='same',
                   input_shape=input_shape),
            Conv1D(2, FILTER_SIZE, strides=2, activation='relu',
                   padding='same'),
            Conv1DTranspose(2, FILTER_SIZE, strides=2, padding='same'),
            Conv1DTranspose(8, FILTER_SIZE, strides=2, padding='same'),
            Conv1DTranspose(1, 1, strides=1, padding='same')
        ])

        self.autoencoder.compile(loss='mse',
                                 optimizer=Adam(0.001),
                                 metrics=['mse'])

    def _pad(self, X):
        return np.append(X, np.zeros((X.shape[0], 1, 1)), axis=1)

    def load_data(self, dataset: Literal['mithb', 'ptbdb']) -> None:
        """Loads and splits the dataset.

        The train and test datasets are loaded from files. Each sample
        is padded with an extra zero to make the dimension divisible
        by 2. The train dataset is then split into a train and a
        validation dataset.

        Global options:
            DEBUG: if set to true, a small subsample of the dataset
                is used to expediate training.
            UPSAMPLE: if set to true, underrepresented classes are
                upsampled to match the sample size of the majority
                class.

        Args:
            dataset: Literal specifying which dataset to load.

        Raises:
            ValueError: Raised if an invalid dataset argument is
                passed.
        """
        X_mit, y_mit, X_test_mit, y_test_mit = load_arrhythmia_dataset()
        X_ptb, y_ptb, X_test_ptb, y_test_ptb = load_PTB_dataset()
        if dataset == 'mithb':
            X, y, X_test, y_test = X_mit, y_mit, X_test_mit, y_test_mit
        elif dataset == 'ptbdb':
            X, y, X_test, y_test = X_ptb, y_ptb, X_test_ptb, y_test_ptb
        else:
            raise ValueError(dataset, 'is not a valid dataset')

        X, X_test, X_mit, X_ptb = self._pad(X), self._pad(X_test), self._pad(
            X_mit), self._pad(X_ptb)
        X_train, X_valid, y_train, y_valid = train_test_split(
            X, y, test_size=VALIDATION_SPLIT, stratify=y)

        if DEBUG:
            X_train, y_train, X_valid, y_valid, X_test, y_test = get_debug_data(
                X_train, y_train, X_valid, y_valid, X_test, y_test)

        if UPSAMPLE:
            X_train, y_train = upsample(X_train, y_train)

        self.X_train = X_train
        self.y_train = y_train
        self.X_valid = X_valid
        self.y_valid = y_valid
        self.X_test = X_test
        self.y_test = y_test

        # The autoencoder does not need labels, so we can use all data
        self.X_train_full = np.concatenate((X_mit, X_ptb), axis=0)
        self.y_train_full = np.concatenate((y_mit, y_ptb), axis=0)

    def train(self):
        print('Fitting autoencoder...')
        X_train_ae = self.X_train_full if self.train_ae_on == 'full' else self.X_train
        self.autoencoder.fit(X_train_ae,
                             X_train_ae,
                             batch_size=BATCH_SIZE,
                             shuffle=True,
                             epochs=EPOCHS)

        print('Generating training features...')
        flat = Flatten()(self.autoencoder.layers[1].output)
        self.featurizer = Model(self.autoencoder.input, flat)

        X_train = self.featurizer.predict(self.X_train)

        print('Fitting classifier...')
        self.clf.fit(X_train, self.y_train)

    def predict(self):
        X_test = self.featurizer.predict(self.X_test)
        self.y_pred = self.clf.predict(X_test)
        self.y_pred_proba = self.clf.predict_proba(X_test)


if __name__ == '__main__':
    from sklearn.metrics import confusion_matrix, accuracy_score
    import seaborn as sn
    import matplotlib.pyplot as plt
    from evaluation import evaluate

    model = AutoencoderTree(dataset='mithb', train_ae_on='full')
    model.train()
    model.predict()

    evaluate('AutoencoderTree',
             model.y_pred_proba,
             model.y_test,
             save_results=False)