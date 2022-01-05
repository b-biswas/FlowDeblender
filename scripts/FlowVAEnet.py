from scripts.model import create_model_fvae, create_flow
import tensorflow as tf
import tensorflow_probability as tfp

from tensorflow.keras.layers import Input
import tensorflow.keras.backend as K

tfd = tfp.distributions
tfb = tfp.bijectors

def vae_loss_fn(x, x_decoded_mean):
    # tf.print(tf.shape(x_decoded_mean.log_prob(x)))
    return -tf.math.reduce_sum(x_decoded_mean.log_prob(x), axis=[1, 2, 3])

def flow_loss_fn(x, output):
    tf.print(tf.shape(output))
    return -output #TODO: is there a problem here too?

class FlowVAEnet:

    def __init__(self,
        input_shape = (64, 64, 6),
        latent_dim = 32,
        filters = [32,64,128,256],
        kernels = [3,3,3,3],
        conv_activation=None,
        dense_activation=None,
        linear_norm=True,
        num_nf_layers=5,
    ):

        self.input_shape = input_shape
        self.latent_dim = latent_dim

        self.filters = filters
        self.kernels = kernels
        self.nb_of_bands = input_shape[2]
        self.conv_activation = conv_activation
        self.dense_activation = dense_activation
        self.num_nf_layers = num_nf_layers
        self.linear_norm = linear_norm

        self.vae_model, self.flow_model, self.encoder, self.decoder, self.td = create_model_fvae(input_shape=self.input_shape, 
                                                                                latent_dim=self.latent_dim, 
                                                                                filters=self.filters, 
                                                                                kernels=self.kernels, 
                                                                                conv_activation=self.conv_activation, 
                                                                                dense_activation=self.dense_activation, 
                                                                                linear_norm=self.linear_norm, 
                                                                                num_nf_layers=self.num_nf_layers)

        self.optimizer = None
        self.callbacks = None

    def train_vae(self, 
                    train_generator, 
                    validation_generator, 
                    path_weights, 
                    callbacks, 
                    optimizer=tf.keras.optimizers.Adam(1e-4), 
                    epochs = 35, 
                    verbose=1):

        self.encoder.trainable=True
        self.decoder.trainable=True
        self.vae_model.summary()
        print("Training only VAE network")
        terminate_on_nan = [tf.keras.callbacks.TerminateOnNaN()]
        self.vae_model.compile(optimizer=optimizer, loss={"decoder": vae_loss_fn}, experimental_run_tf_function=False)
        self.vae_model.fit_generator(generator=train_generator, 
                                    epochs=epochs,
                                    verbose=verbose,
                                    shuffle=True,
                                    validation_data=validation_generator,
                                    callbacks= callbacks + terminate_on_nan,
                                    workers=0, 
                                    use_multiprocessing = True)

    def train_flow(self, 
                    train_generator, 
                    validation_generator, 
                    path_weights, 
                    callbacks, 
                    optimizer=tf.keras.optimizers.Adam(1e-2), 
                    epochs = 35, 
                    verbose=1):

        print("Training only Flow net")
        
        self.td.trainable = True
        self.encoder.trainable = False
        self.flow_model.summary()
        self.flow_model.compile(optimizer=optimizer, loss={"flow": flow_loss_fn}, experimental_run_tf_function=False)
        #self.model.compile(optimizer=optimizer, loss={'flow': flow_loss_fn})
        terminate_on_nan = [tf.keras.callbacks.TerminateOnNaN()]
        self.flow_model.fit_generator(generator=train_generator,
                                    epochs=epochs,
                                    verbose=verbose,
                                    shuffle=True,
                                    validation_data=validation_generator,
                                    callbacks=callbacks + terminate_on_nan,
                                    workers=0, 
                                    use_multiprocessing=True)

    def load_vae_weights(self, weights_path, Folder=True):
        if Folder:
            weights_path = tf.train.latest_checkpoint(weights_path)
        self.vae_model.load_weights(weights_path)

    def load_flow_weights(self, weights_path, Folder=True):
        if Folder:
            weights_path = tf.train.latest_checkpoint(weights_path)
        self.flow_model.load_weights(weights_path)
