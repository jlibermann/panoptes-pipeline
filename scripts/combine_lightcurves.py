#!/usr/bin/env python3

import os
import json
import argparse
import warnings

from pocs.utils.google.storage import PanStorage


class LightCurveCombiner(object):

    """
    Class to combine light curve segments into master light curve
    """

    def __init__(self, storage=None, temp_dir='/tmp/lc-combine'):
        assert storage is not None, warnings.warn(
            "A valid storage object is required.")
        self.storage = storage
        self.temp_dir = temp_dir

    def run(self, pic):
        """Build a master light curve for a given PIC and output it as JSON.

        :param pic: The PIC object to combine light curves for
        """
        curves = self.get_curves_for_pic(pic)
        master = self.combine_curves(curves)
        filename = 'MLC/{}.json'.format(pic)
        self.upload_output(filename, master)

    def get_curves_for_pic(self, pic):
        """Read light curve files and add all curves to array.

        :param pic: the PIC id for the star to make a master light curve for
        :return: an array containing all the light curves for the given PIC
        """
        curves = []
        prefix = "LC/{}/".format(pic)

        storage = self.storage
        files = pan_storage.list_remote(prefix)
        for filename in files:
            local_path = "{}/{}".format(self.temp_dir, filename)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            data = storage.download_string(filename)
            try:
                curve = json.load(data.decode())
                curves.append(curve)
            except ValueError as err:
                raise ValueError("Error: Object {} could not be decoded as JSON.".format(
                    filename))
        if len(curves) == 0:
            raise NameError("No light curves for object '{}' found in bucket '{}'.".format(
                pic, pan_storage.bucket_name))
        return curves

    def combine_curves(self, curves):
        """Flatten all the data points in the curves into one master curve array.

        Each data point has a timestamp, exposure duration, RGB fluxes, and
        RGB flux uncertainties.
        :param curves: an array of light curves, each with many data points, to be combined
        :return: a master light curve stored in a single array
        """
        master = []
        for c in curves:
            for data_point in c:
                master.append(data_point)
        return master

    def upload_output(self, filename, data):
        """Write the data to a local file.

        :param filename: the name of the file to upload
        :param data: the data to upload
        """
        storage = self.storage
        storage.upload_string(json.dumps(data), filename)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('pic', type=str, help="The PIC ID of the star to build a"
                                              " master light curve for.")
    args = parser.parse_args()
    pan_storage = PanStorage(bucket_name='panoptes-simulated-data')
    combiner = LightCurveCombiner(storage=pan_storage)
    combiner.run(args.pic)
