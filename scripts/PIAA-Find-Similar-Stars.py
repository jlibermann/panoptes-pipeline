#!/usr/bin/env python3

# ## Find similar stars
# 
# Because a simple differential photometry doesn't work well we need to find a suitable set of reference stars that undergo the same changes (e.g. airmass, cloud cover, etc) as our target star.
# 
# Ultimately we are concerned about how the flux of our target changes with respect to a suitable set of reference stars and therefore we need to be careful **not** to use flux as a selection parameter for determining the "best" reference stars. That is, we **do not** want to choose reference stars that undergo a reduction of flux in the middle of the observation as this will hide the transit signal in our target.
# 
# We can marginalize across the flux by normalizing each stamp to the total flux in the stamp (see [Normalize](Algorithm.ipynb#normalize) in algorithm description). By doing so we are effectively looking at the shape of the star as it appears on the RGB pixel pattern. This morphology will change slightly from frame to frame so we want to look for reference stars that change similarly to our target star with respect to this morphology.
# 
# By taking the summed squared difference (SSD) between each pixel of the normalized target and reference star we can get a single metric that defines how well the reference star matches the target. Because the SSD is looking at the difference between the target and a reference, a lower metric value for the refernce indicates a better match with the target. The target stamp compared with itself would yield a value of zero.
# 
# We perform the SSD for each frame in the observation and take the sum of all the SSDs for each source as the final metric score to compare against our target. Again, lower scores mean that the reference is more "similar" in a morphological sense: it's shape on the RGB pattern changes similar to that of the target. See [Find Reference Stars](Algorithm.ipynb#find_reference) for details and mathematical description.

# ### Get the ranking for comparison stars
# 
# For each source that was identified above we want to find the most "similar" stars by ranking them according to how the shape of their PSF differs from that of the target. This is done for each frame and the sum across all frames determines the "similarity", with smaller final sums indicating stars that are similar to the target. The target ranked against itself would yield a value of zero.
# 
# By the numbers, this is doing the sum of the summed squared difference (SSD) for each pixel in the stamp for each frame. Importantly, it is doing this comparision on the normalized version of each stamp. The stamp is normalized according to the total sum of the stamp. See [Step 1](Algorithm.ipynb#normalize) below for the Normalization and [Step 2](Algorithm.ipynb#find_references) for the sum of the SSD.

import os
import logging
from contextlib import suppress
from itertools import zip_longest
import concurrent.futures

import pandas as pd
import numpy as np
from collections import defaultdict

from matplotlib import pyplot as plt

from glob import glob
from tqdm import tqdm

from pocs.utils import current_time
from pocs.utils.logger import get_root_logger

import logging
logger = get_root_logger()
logger.setLevel(logging.DEBUG)


# How many matches to save
SAVE_NUM=500


def find_similar(find_params):
    """ The worker thread to find the stars """
    
    psc_fn = find_params[0]
    params = find_params[1]
    
    base_dir = params['base_dir']
    processed_dir = params['processed_dir']
    force = params['force']
    camera_bias = params['camera_bias']
    psc_dir = os.path.dirname(psc_fn)
    
    # Get the relative path starting from processed_dir; picid is then first folder.
    picid = os.path.relpath(psc_fn, start=processed_dir).split('/')[0]
    
    similar_fn = os.path.normpath(os.path.join(psc_dir, 'similar_sources.csv'))
    
    if force or not os.path.exists(similar_fn): 
        # Normalize target PSC.
        target_table = pd.read_csv(psc_fn).set_index(['obstime', 'picid'])
        target_psc = np.array(target_table) - camera_bias

        # Normalize
        normalized_target_psc = (target_psc.T / target_psc.sum(1)).T

        # Get all the psc files.
        processed_dir_glob = os.path.join(processed_dir, '*', base_dir) 
        psc_files = glob(os.path.join(processed_dir_glob, 'psc.csv'), recursive=True)

        # Loop through all other stamp files.
        vary = dict()
        for comp_psc_fn in psc_files:
            # See note on picid above.
            ref_picid = os.path.relpath(comp_psc_fn, start=processed_dir).split('/')[0]

            # Normalize reference PSC.
            ref_table = pd.read_csv(comp_psc_fn).set_index(['obstime', 'picid'])
            ref_psc = np.array(ref_table) - camera_bias

            # Normalize
            normalized_ref_psc = (ref_psc.T / ref_psc.sum(1)).T

            try:
                score = ((normalized_target_psc - normalized_ref_psc)**2).sum()
                vary[ref_picid] = score
            except ValueError as e:
                logger.warning(f'{picid} Error in finding similar star: {e}')

        vary_series = pd.Series(vary).sort_values()
        vary_series[:SAVE_NUM].to_csv(similar_fn)
    
    return picid

def main(base_dir,
         processed_dir=None,
         picid=None,
         force=False,
         camera_bias=2048,
         num_workers=8,
         chunk_size=12,
    ):
    print(f'Finding similar stars for observation in {base_dir}')
    
    if picid:
        print(f'Searching for picid={picid}')
        processed_dir_glob = os.path.join(processed_dir, str(picid), base_dir) 
    else:
        processed_dir_glob = os.path.join(processed_dir, '*', base_dir) 
        
    psc_files = glob(os.path.join(processed_dir_glob, 'psc.csv'), recursive=True)
        
    print(f'Found {len(psc_files)} PSC files')
    
    call_params = {
        'base_dir': base_dir,
        'processed_dir': processed_dir,
        'force': force,
        'camera_bias': camera_bias
    }
                                  
    # Build up the parameter list (NB: "clever" zip_longest usage)
    params = zip_longest(psc_files, [], fillvalue=call_params)
    
    start_time = current_time()
    print(f'Starting at {start_time}')

    with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
        picids = list(tqdm(executor.map(find_similar, params, chunksize=chunk_size), total=len(psc_files)))
        logging.debug(f'Found similar stars for {len(picids)} sources')
            
    end_time = current_time()
    print(f'Ending at {end_time}')
    total_time = (end_time - start_time).sec
    print(f'Total: {total_time:.02f} seconds')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Find similar stars for each star.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--directory', dest="base_dir", default=None, type=str,
                       help="Directory containing observation images.")
    parser.add_argument('--processed-dir', default='/var/panoptes/processed', type=str,
                       help=("All artifacts are processed and placed in this directory. "
                             "A subdirectory will be created for each PICID if it does not "
                             "exist and a directory corresponding to the sequence id is made for "
                             "this observation inside the PICID dir. Defaults to $PANDIR/processed/."
                            ))
    parser.add_argument('--picid', default=None, type=str, help="Create PSC only for given PICID")
    parser.add_argument('--num-workers', default=None, type=int, help="Number of workers to use")
    parser.add_argument('--chunk-size', default=1, type=int, help="Chunks per worker")
    parser.add_argument('--force', action='store_true', default=False, 
                        help="Force creation (deletes existing files)")

    args = parser.parse_args()

    print(f'Using {args.num_workers} workers with {args.chunk_size} chunks')
    main(**vars(args))
    print('Finished creating stamps')
    