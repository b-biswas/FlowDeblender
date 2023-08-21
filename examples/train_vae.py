"""Train all models."""

import os

import btk
import numpy as np
import tensorflow as tf
import tensorflow_probability as tfp
import tensorflow_datasets as tfds
from galcheat.utilities import mean_sky_level

from maddeb.batch_generator import COSMOSsequence
from maddeb.FlowVAEnet import FlowVAEnet
   
from maddeb.losses import deblender_loss_fn_wrapper

from maddeb.callbacks import define_callbacks, changeAlpha
from maddeb.utils import get_data_dir_path
from maddeb.dataset_generator import batched_CATSIMDataset

tfd = tfp.distributions

# define the parameters
batch_size = 100
vae_epochs = 150
flow_epochs = 150
deblender_epochs = 150
lr_scheduler_epochs = 40
latent_dim = 16
linear_norm_coeff = 10000

survey = btk.survey.get_surveys("LSST")

noise_sigma = []
for b, name in enumerate(survey.available_filters):
    filt = survey.get_filter(name)
    noise_sigma.append(np.sqrt(mean_sky_level(survey, filt).to_value("electron")))

noise_sigma = np.array(noise_sigma, dtype=np.float32) / linear_norm_coeff

kl_prior = tfd.Independent(
    tfd.Normal(loc=tf.zeros(latent_dim), scale=1), reinterpreted_batch_ndims=1
)
kl_weight = 0.0001

f_net = FlowVAEnet(
    latent_dim=latent_dim,
    kl_prior=kl_prior,
    kl_weight=kl_weight,
)

# Keras Callbacks
data_path = get_data_dir_path()

path_weights = os.path.join(data_path, "catsim_kl01" + str(latent_dim) + "d")

# Define the generators
ds_isolated_train, ds_isolated_val = batched_CATSIMDataset(
    tf_dataset_dir='/sps/lsst/users/bbiswas/simulations/CATSIM_tfDataset/isolated_tfDataset',
    linear_norm_coeff=linear_norm_coeff,
    batch_size=batch_size,
    x_col_name="blended_gal_stamps",
    y_col_name="isolated_gal_stamps",
)

# Define all used callbacks
callbacks = define_callbacks(
    os.path.join(path_weights, "ssim"), lr_scheduler_epochs=lr_scheduler_epochs, patience=vae_epochs,
)

ch_alpha=changeAlpha(max_epochs=int(vae_epochs/5))

hist_vae = f_net.train_vae(
    ds_isolated_train,
    ds_isolated_val,
    callbacks=callbacks+[ch_alpha],
    epochs=int(vae_epochs/5),
    train_encoder=True,
    train_decoder=True,
    track_kl=True,
    optimizer=tf.keras.optimizers.Adam(1e-4, clipvalue=0.1),
    loss_function=deblender_loss_fn_wrapper(sigma_cutoff=noise_sigma, use_ssim=True, ch_alpha=ch_alpha, linear_norm_coeff=linear_norm_coeff),
    # loss_function=vae_loss_fn_wrapper(sigma=noise_sigma, linear_norm_coeff=linear_norm_coeff),
)

np.save(path_weights + "/train_vae_ssim_history.npy", hist_vae.history)

callbacks = define_callbacks(
    os.path.join(path_weights, "vae"), lr_scheduler_epochs=lr_scheduler_epochs
)

hist_vae = f_net.train_vae(
    ds_isolated_train,
    ds_isolated_val,
    callbacks=callbacks,
    epochs=int(8*vae_epochs/10),
    train_encoder=True,
    train_decoder=True,
    track_kl=True,
    optimizer=tf.keras.optimizers.Adam(1e-5, clipvalue=0.01),
    loss_function=deblender_loss_fn_wrapper(sigma_cutoff=noise_sigma),
    # loss_function=vae_loss_fn_wrapper(sigma=noise_sigma, linear_norm_coeff=linear_norm_coeff),
)

np.save(path_weights + "/train_vae_history.npy", hist_vae.history)
num_nf_layers = 8
f_net = FlowVAEnet(
    latent_dim=latent_dim,
    kl_prior=None,
    kl_weight=0,
    num_nf_layers=num_nf_layers,
)

f_net.load_vae_weights(os.path.join(path_weights, "vae", "val_loss"))
# f_net.load_flow_weights(os.path.join(path_weights, f"flow{num_nf_layers}", "val_loss"))

# Define all used callbacks
callbacks = define_callbacks(
    os.path.join(path_weights, f"flow{num_nf_layers}"),
    lr_scheduler_epochs=lr_scheduler_epochs,
)

# now train the model
hist_flow = f_net.train_flow(
    ds_isolated_train,
    ds_isolated_val,
    callbacks=callbacks,
    optimizer=tf.keras.optimizers.Adam(1e-3),
    epochs=flow_epochs,
)

np.save(os.path.join(path_weights, "train_flow_history.npy"), hist_flow.history)

f_net.flow.trainable = False
# deblend_prior = f_net.td
# deblend_prior.trainable = False
# print(f_net.flow.trainable_variables)


f_net = FlowVAEnet(
    latent_dim=latent_dim,
    kl_prior=kl_prior,
    kl_weight=0,
)
f_net.load_vae_weights(os.path.join(path_weights, "vae", "val_loss"))
# f_net.randomize_encoder()


# Define all used callbacks
callbacks = define_callbacks(
    os.path.join(path_weights, "deblender"),
    lr_scheduler_epochs=lr_scheduler_epochs,
)

# f_net.vae_model.get_layer("latent_space").activity_regularizer=None

ds_blended_train, ds_blended_val = batched_CATSIMDataset(
    tf_dataset_dir='/sps/lsst/users/bbiswas/simulations/CATSIM_tfDataset/blended_tfDataset',
    linear_norm_coeff=linear_norm_coeff,
    batch_size=batch_size,
    x_col_name="blended_gal_stamps",
    y_col_name="isolated_gal_stamps",
)

hist_deblender = f_net.train_vae(
    ds_blended_train,
    ds_blended_val,
    callbacks=callbacks,
    epochs=deblender_epochs,
    train_encoder=True,
    train_decoder=False,
    track_kl=True,
    optimizer=tf.keras.optimizers.Adam(1e-4, clipvalue=0.01),
    loss_function=deblender_loss_fn_wrapper(sigma_cutoff=noise_sigma),
    # loss_function=vae_loss_fn_wrapper(sigma=noise_sigma, linear_norm_coeff=linear_norm_coeff),
)

np.save(path_weights + "/train_deblender_history.npy", hist_deblender.history)
