import logging
import time
from turtle import pos

import numpy as np
import tensorflow as tf
import tensorflow_probability as tfp

from scripts.extraction import extract_cutouts
from scripts.FlowVAEnet import FlowVAEnet

tfd = tfp.distributions

# logging level set to INFO
logging.basicConfig(format="%(message)s", level=logging.INFO)

LOG = logging.getLogger(__name__)


class Deblend:
    def __init__(
        self,
        postage_stamp,
        detected_positions,
        cutout_size=59,
        num_components=1,
        max_iter=60,
        lr=0.3,
        latent_dim=10,
        initZ=None,
        use_likelihood=True,
        channel_last=False,
    ):
        """
        Parameters
        __________
        postage_stamp: np.ndarray
            input stamp/field that is to be deblended
        detected_positions: as in array and not image
        cutout_size:
        num_components: int
            number of galaxies present in the image.
        max_iter: int
            number of iterations in the deblending step
        lr: float
            learning rate for the gradient descent in the latent space.
        initZ: np.ndarry
            initial value for the latent space
        use_likelihood: bool
            decides whether or not to use the log_prob output of the flow deblender in the optimization.
        channel_last: bool
            if channel is the last column of the postage_stamp
        """

        self.postage_stamp = postage_stamp
        self.max_iter = max_iter
        self.lr = lr
        self.num_components = num_components
        self.use_likelihood = use_likelihood
        self.components = None
        self.channel_last = channel_last
        self.detected_positions = detected_positions
        self.cutout_size = cutout_size
        if channel_last: 
            self.num_bands = np.shape(postage_stamp)[-1]
        else:
            self.num_bands = np.shape(postage_stamp)[0]

        self.latent_dim = latent_dim
        self.flow_vae_net = FlowVAEnet(latent_dim=latent_dim)

        self.flow_vae_net.load_flow_weights(
            weights_path="/pbs/throng/lsst/users/bbiswas/train_debvader/cosmos/updated_cosmos10dim_small_sig/fvae/"
        )
        self.flow_vae_net.load_vae_weights(
            weights_path="/pbs/throng/lsst/users/bbiswas/train_debvader/cosmos/updated_cosmos10dim_small_sig/deblender/val_loss"
        )

        # self.flow_vae_net.vae_model.trainable = False
        # self.flow_vae_net.flow_model.trainable = False

        # self.flow_vae_net.vae_model.summary()
        self.optimizer=None
        self.gradient_decent(initZ)

    def get_components(self):
        """
        Function to return the predicted components. 

        The final returned image has same value of channel_last as input image.
        """
        if self.channel_last:
            return self.components.copy()
        return np.transpose(self.components, axes=(0, 3, 1, 2)).copy()

    @tf.function
    def compute_residual(self, postage_stamp=None, reconstructions=None):
        postage_stamp = tf.cast(postage_stamp, tf.float32)
        if reconstructions is None:
            reconstructions = self.components
        if self.channel_last:
            residual_field = postage_stamp
        else:
            residual_field = tf.transpose(postage_stamp, perm=[1, 2, 0])

        for i in range(self.num_components):
            detected_position = self.detected_positions[i]

            # TODO: make this optional

            # cutout prediction
            reconstruction = reconstructions[i]

            starting_pos_x = int(detected_position[0] - (self.cutout_size - 1) / 2)
            starting_pos_y = int(detected_position[1] - (self.cutout_size - 1) / 2)

            indices = (
                np.indices(
                    (self.cutout_size, self.cutout_size, self.num_bands)
                )
                .reshape(3, -1)
                .T
            )
            indices[:, 0] += int(starting_pos_x)
            indices[:, 1] += int(starting_pos_y)

            #print(reconstruction.shape)  # (59, 59, 6)
            #print(tf.reshape(reconstruction, [tf.math.reduce_prod(reconstruction.shape)]))  # (59*59*6)
            #print(indices.shape)
            residual_field = tf.tensor_scatter_nd_sub(
                residual_field, indices, tf.reshape(reconstruction, [tf.math.reduce_prod(reconstruction.shape)])
            )

        return residual_field

    @tf.function
    def gradient_tape_loss(self, z, postage_stamp):
        with tf.GradientTape() as tape:

            reconstructions = self.flow_vae_net.decoder(z).mean()

            residual_field = self.compute_residual(postage_stamp, reconstructions)

            sig = tf.math.reduce_std(residual_field)
            reconstruction_loss = tf.cast(
                tf.math.reduce_sum(tf.square(residual_field)), tf.float32
            ) / tf.cast(tf.square(sig), tf.float32)

            reconstruction_loss = tf.divide(reconstruction_loss, 2)

            log_likelihood = tf.cast(
                tf.math.reduce_sum(
                    self.flow_vae_net.flow(
                        tf.reshape(z, (self.num_components, self.latent_dim))
                    )
                ),
                tf.float32,
            )
            if self.use_likelihood:
                loss = tf.math.subtract(reconstruction_loss, log_likelihood)
            else:
                loss = reconstruction_loss

            grad = tape.gradient(loss, [z])
        
            return grad, loss, reconstruction_loss, log_likelihood

    def gradient_decent(self, optimizer=None, initZ=None):
        """
        perform the gradient descent step to separate components (galaxies)

        Parameters
        ----------
        optimizer: tf.keras.optimizers
            optimizer to be used for hte gradient descent
        initZ: np.ndarray
            initial value of the latent space.
        """
        X = self.postage_stamp
        if not self.channel_last:
            X = np.transpose(X, axes=(1, 2, 0))

        m, n, b = np.shape(X)

        if initZ is not None:
            # check constraint parameter over here
            z = tf.Variable(initial_value=initZ, name="z")

        else:
            # z = tf.Variable(name="z", initial_value=tf.random_normal_initializer(mean=0, stddev=1)(shape=[self.num_components, self.latent_dim], dtype=tf.float32))
            # use the encoder to find a good starting point.
            distances_to_center = list(
                np.array(self.detected_positions) - int((m - 1) / 2)
            )
            cutouts = extract_cutouts(
                X, m, distances_to_center, cutout_size=self.cutout_size, nb_of_bands=b
            )
            initZ = tfp.layers.MultivariateNormalTriL(self.latent_dim)(
                self.flow_vae_net.encoder(cutouts)
            )
            LOG.info("\n\nUsing encoder for initial point")
            z = tf.Variable(initZ.mean())

        self.optimizer = tf.keras.optimizers.Adam(lr=self.lr)

        sig = tf.math.reduce_std(X)

        LOG.info("\n--- Starting gradient descent in the latent space ---")
        LOG.info("Number of iterations: " + str(self.max_iter))
        LOG.info("Learning rate: " + str(self.lr))
        LOG.info("Number of Galaxies: " + str(self.num_components))
        LOG.info("Dimensions of latent space: " + str(self.latent_dim))

        t0 = time.time()

        for i in range(self.max_iter):

            print(i)
            #print("log prob flow:" + str(log_likelihood.numpy()))
            #print("reconstruction loss"+str(reconstruction_loss.numpy()))
            grad, loss, reconstruction_loss, log_likelihood = self.gradient_tape_loss(z, self.postage_stamp)
            print("log prob flow:" + str(log_likelihood.numpy()))
            print("reconstruction loss"+str(reconstruction_loss.numpy()))
            print(loss)

            self.optimizer.apply_gradients(zip(grad, [z]))
            

        LOG.info("--- Gradient descent complete ---")
        LOG.info("\nTime taken for gradient descent: " + str(time.time() - t0))
        print(z)
        self.components = self.flow_vae_net.decoder(z).mean().numpy()
        #print(self.components)
