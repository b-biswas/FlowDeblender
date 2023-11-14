"""Simulate test dataset."""

import logging
import os
import sys

import btk
import hickle
import yaml

from btksims.sampling import CustomSampling
from btksims.utils import get_btksims_config_path

# logging level set to INFO
logging.basicConfig(format="%(message)s", level=logging.INFO)

LOG = logging.getLogger(__name__)

stamp_size = 41
density = sys.argv[1]

if density not in ["high", "low"]:
    raise ValueError("The first arguemnt should be either high or low")

if density == "high":
    min_number = 12
    max_number = 20
else:
    min_number = 8
    max_number = 15

with open(get_btksims_config_path()) as f:
    btksims_config = yaml.safe_load(f)

COSMOS_CATALOG_PATHS = btksims_config["CAT_PATH"]

simulation_path = btksims_config["TEST_DATA_SAVE_PATH"]


batch_size = 20
maxshift = 15
num_repetations = 300
catalog = btk.catalog.CatsimCatalog.from_file(COSMOS_CATALOG_PATHS)
survey = btk.survey.get_surveys("LSST")
seed = 13

index_range = [200000, len(catalog.table)]
sampling_function = CustomSampling(
    index_range=index_range,
    min_number=min_number,
    max_number=max_number,
    maxshift=maxshift,
    stamp_size=stamp_size,
    seed=seed,
    unique=False,
)

draw_generator = btk.draw_blends.CatsimGenerator(
    catalog,
    sampling_function,
    survey,
    batch_size=batch_size,
    stamp_size=stamp_size,
    cpus=1,
    add_noise="all",
    verbose=False,
    seed=seed,
    augment_data=False,
)

for file_num in range(num_repetations):
    print("Processing file " + str(file_num))
    blend = next(draw_generator)

    save_file_name = os.path.join(
        simulation_path,
        density,
        str(file_num) + ".hkl",
    )
    print(save_file_name)
    hickle.dump(blend, save_file_name, mode="w")
