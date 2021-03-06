__author__ = 'sibirrer'

from lenstronomy.ImSim.Numerics.numerics_subframe import NumericsSubFrame
from lenstronomy.ImSim.image2source_mapping import Image2SourceMapping
from lenstronomy.LensModel.lens_model import LensModel
from lenstronomy.LightModel.light_model import LightModel
from lenstronomy.PointSource.point_source import PointSource
from lenstronomy.ImSim.differential_extinction import DifferentialExtinction

import numpy as np


class ImageModel(object):
    """
    this class uses functions of lens_model and source_model to make a lensed image
    """
    def __init__(self, data_class, psf_class, lens_model_class=None, source_model_class=None,
                 lens_light_model_class=None, point_source_class=None, extinction_class=None, kwargs_numerics={}):
        """
        :param data_class: instance of ImageData() or PixelGrid() class
        :param psf_class: instance of PSF() class
        :param lens_model_class: instance of LensModel() class
        :param source_model_class: instance of LightModel() class describing the source parameters
        :param lens_light_model_class: instance of LightModel() class describing the lens light parameters
        :param point_source_class: instance of PointSource() class describing the point sources
        :param kwargs_numerics: keyword argument with various numeric description (see ImageNumerics class for options)
        """
        self.type = 'single-band'
        self.PSF = psf_class
        self.Data = data_class
        self.PSF.set_pixel_size(self.Data.pixel_width)
        self.ImageNumerics = NumericsSubFrame(pixel_grid=self.Data, psf=self.PSF, **kwargs_numerics)
        if lens_model_class is None:
            lens_model_class = LensModel(lens_model_list=[])
        self.LensModel = lens_model_class
        if point_source_class is None:
            point_source_class = PointSource(point_source_type_list=[])
        self.PointSource = point_source_class
        self.PointSource.update_lens_model(lens_model_class=lens_model_class)
        x_center, y_center = self.Data.center
        self.PointSource.update_search_window(search_window=np.max(self.Data.width), x_center=x_center,
                                                  y_center=y_center, min_distance=self.Data.pixel_width)
        self._psf_error_map = self.PSF.psf_error_map_bool

        if source_model_class is None:
            source_model_class = LightModel(light_model_list=[])
        self.SourceModel = source_model_class
        if lens_light_model_class is None:
            lens_light_model_class = LightModel(light_model_list=[])
        self.LensLightModel = lens_light_model_class
        self.source_mapping = Image2SourceMapping(lensModel=lens_model_class, sourceModel=source_model_class)
        self.num_bands = 1
        self._kwargs_numerics = kwargs_numerics
        if extinction_class is None:
            extinction_class = DifferentialExtinction(optical_depth_model=[])
        self._extinction = extinction_class

    def reset_point_source_cache(self, bool=True):
        """
        deletes all the cache in the point source class and saves it from then on

        :param bool: boolean, if True, saves the next occuring point source positions in the cache
        :return: None
        """
        self.PointSource.delete_lens_model_cache()
        self.PointSource.set_save_cache(bool)

    def update_psf(self, psf_class):
        """

        update the instance of the class with a new instance of PSF() with a potentially different point spread function

        :param psf_class:
        :return: no return. Class is updated.
        """
        self.PSF = psf_class
        self.PSF.set_pixel_size(self.Data.pixel_width)
        self.ImageNumerics = NumericsSubFrame(pixel_grid=self.Data, psf=self.PSF, **self._kwargs_numerics)

    def source_surface_brightness(self, kwargs_source, kwargs_lens=None, kwargs_extinction=None, kwargs_special=None,
                                  unconvolved=False, de_lensed=False, k=None):
        """

        computes the source surface brightness distribution

        :param kwargs_source: list of keyword arguments corresponding to the superposition of different source light profiles
        :param kwargs_lens: list of keyword arguments corresponding to the superposition of different lens profiles
        :param kwargs_extinction: list of keyword arguments of extinction model
        :param unconvolved: if True: returns the unconvolved light distribution (prefect seeing)
        :param de_lensed: if True: returns the un-lensed source surface brightness profile, otherwise the lensed.
        :param k: integer, if set, will only return the model of the specific index
        :return: 1d array of surface brightness pixels
        """
        if len(self.SourceModel.profile_type_list) == 0:
            return np.zeros((self.Data.num_pixel_axes))
        ra_grid, dec_grid = self.ImageNumerics.coordinates_evaluate
        if de_lensed is True:
            source_light = self.SourceModel.surface_brightness(ra_grid, dec_grid, kwargs_source, k=k)
        else:
            source_light = self.source_mapping.image_flux_joint(ra_grid, dec_grid, kwargs_lens, kwargs_source, k=k)
            source_light *= self._extinction.extinction(ra_grid, dec_grid, kwargs_extinction=kwargs_extinction,
                                                        kwargs_special=kwargs_special)
        source_light_final = self.ImageNumerics.re_size_convolve(source_light, unconvolved=unconvolved)
        return source_light_final

    def lens_surface_brightness(self, kwargs_lens_light, unconvolved=False, k=None):
        """

        computes the lens surface brightness distribution

        :param kwargs_lens_light: list of keyword arguments corresponding to different lens light surface brightness profiles
        :param unconvolved: if True, returns unconvolved surface brightness (perfect seeing), otherwise convolved with PSF kernel
        :return: 1d array of surface brightness pixels
        """
        ra_grid, dec_grid = self.ImageNumerics.coordinates_evaluate
        lens_light = self.LensLightModel.surface_brightness(ra_grid, dec_grid, kwargs_lens_light, k=k)
        lens_light_final = self.ImageNumerics.re_size_convolve(lens_light, unconvolved=unconvolved)
        return lens_light_final

    def point_source(self, kwargs_ps, kwargs_lens=None, kwargs_special=None, unconvolved=False, k=None):
        """

        computes the point source positions and paints PSF convolutions on them

        :param kwargs_ps:
        :param k:
        :return:
        """
        point_source_image = np.zeros((self.Data.num_pixel_axes))
        if unconvolved or self.PointSource is None:
            return point_source_image
        ra_pos, dec_pos, amp = self.PointSource.point_source_list(kwargs_ps, kwargs_lens=kwargs_lens, k=k)
        ra_pos, dec_pos = self._displace_astrometry(ra_pos, dec_pos, kwargs_special=kwargs_special)
        point_source_image += self.ImageNumerics.point_source_rendering(ra_pos, dec_pos, amp)
        return point_source_image

    def image(self, kwargs_lens=None, kwargs_source=None, kwargs_lens_light=None, kwargs_ps=None,
              kwargs_extinction=None, kwargs_special=None, unconvolved=False, source_add=True, lens_light_add=True, point_source_add=True):
        """

        make an image with a realisation of linear parameter values "param"

        :param kwargs_lens: list of keyword arguments corresponding to the superposition of different lens profiles
        :param kwargs_source: list of keyword arguments corresponding to the superposition of different source light profiles
        :param kwargs_lens_light: list of keyword arguments corresponding to different lens light surface brightness profiles
        :param kwargs_ps: keyword arguments corresponding to "other" parameters, such as external shear and point source image positions
        :param unconvolved: if True: returns the unconvolved light distribution (prefect seeing)
        :param source_add: if True, compute source, otherwise without
        :param lens_light_add: if True, compute lens light, otherwise without
        :param point_source_add: if True, add point sources, otherwise without
        :return: 1d array of surface brightness pixels of the simulation
        """
        model = np.zeros((self.Data.num_pixel_axes))
        if source_add is True:
            model += self.source_surface_brightness(kwargs_source, kwargs_lens, kwargs_extinction=kwargs_extinction,
                                                    kwargs_special=kwargs_special, unconvolved=unconvolved)
        if lens_light_add is True:
            model += self.lens_surface_brightness(kwargs_lens_light, unconvolved=unconvolved)
        if point_source_add is True:
            model += self.point_source(kwargs_ps, kwargs_lens, kwargs_special=kwargs_special, unconvolved=unconvolved)
        return model

    def extinction_map(self, kwargs_extinction=None, kwargs_special=None):
        """
        differential extinction per pixel

        :param kwargs_extinction: list of keyword arguments corresponding to the optical depth models tau, such that extinction is exp(-tau)
        :param kwargs_special: keyword arguments, additional parameter to the extinction
        :return: 2d array of size of the image
        """
        ra_grid, dec_grid = self.ImageNumerics.coordinates_evaluate
        extinction = self._extinction.extinction(ra_grid, dec_grid, kwargs_extinction=kwargs_extinction,
                                                        kwargs_special=kwargs_special)
        extinction_array = np.ones_like(ra_grid) * extinction
        extinction = self.ImageNumerics.re_size_convolve(extinction_array, unconvolved=True)
        return extinction

    def _displace_astrometry(self, x_pos, y_pos, kwargs_special=None):
        """
        displaces point sources by shifts specified in kwargs_special

        :param x_pos: list of point source positions according to point source model list
        :param y_pos: list of point source positions according to point source model list
        :param kwargs_special: keyword arguments, can contain 'delta_x_image' and 'delta_y_image'
        The list is defined in order of the image positions
        :return: shifted image positions in same format as input
        """
        if kwargs_special is not None:
            if 'delta_x_image' in kwargs_special:
                delta_x, delta_y = kwargs_special['delta_x_image'], kwargs_special['delta_y_image']
                delta_x_new = np.zeros(len(x_pos))
                delta_x_new[0:len(delta_x)] = delta_x[:]
                delta_y_new = np.zeros(len(y_pos))
                delta_y_new[0:len(delta_y)] = delta_y
                x_pos = x_pos + delta_x_new
                y_pos = y_pos + delta_y_new
        return x_pos, y_pos
