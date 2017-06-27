"""
Support for HydroQuebec.

Get data from 'My Consumption Profile' page:
https://www.hydroquebec.com/portail/en/group/clientele/portrait-de-consommation

For more details about this platform, please refer to the documentation at
https://home-assistant.io/components/sensor.hydroquebec/
"""
import logging
from datetime import timedelta

import requests
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import (
    CONF_USERNAME, CONF_PASSWORD,
    CONF_NAME, CONF_MONITORED_VARIABLES, TEMP_CELSIUS)
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle
import homeassistant.helpers.config_validation as cv

REQUIREMENTS = ['pyhydroquebec==1.2.0']

_LOGGER = logging.getLogger(__name__)

KILOWATT_HOUR = 'kWh'  # type: str
PRICE = 'CAD'  # type: str
DAYS = 'days'  # type: str
CONF_CONTRACT = 'contract'  # type: str

DEFAULT_NAME = 'HydroQuebec'

REQUESTS_TIMEOUT = 15
MIN_TIME_BETWEEN_UPDATES = timedelta(hours=1)

SENSOR_TYPES = {
    'balance':
    ['Balance', PRICE, 'mdi:square-inc-cash'],
    'period_total_bill':
    ['Current period bill', PRICE, 'mdi:square-inc-cash'],
    'period_length':
    ['Current period length', DAYS, 'mdi:calendar-today'],
    'period_total_days':
    ['Total number of days in this period', DAYS, 'mdi:calendar-today'],
    'period_mean_daily_bill':
    ['Period daily average bill', PRICE, 'mdi:square-inc-cash'],
    'period_mean_daily_consumption':
    ['Period daily average consumption', KILOWATT_HOUR, 'mdi:flash'],
    'period_total_consumption':
    ['Total Consumption', KILOWATT_HOUR, 'mdi:flash'],
    'period_lower_price_consumption':
    ['Period Lower price consumption', KILOWATT_HOUR, 'mdi:flash'],
    'period_higher_price_consumption':
    ['Period Higher price consumption', KILOWATT_HOUR, 'mdi:flash'],
    'yesterday_total_consumption':
    ['Yesterday total consumption', KILOWATT_HOUR, 'mdi:flash'],
    'yesterday_lower_price_consumption':
    ['Yesterday lower price consumption', KILOWATT_HOUR, 'mdi:flash'],
    'yesterday_higher_price_consumption':
    ['Yesterday higher price consumption', KILOWATT_HOUR, 'mdi:flash'],
    'yesterday_average_temperature':
    ['Yesterday average temperature', TEMP_CELSIUS, 'mdi:thermometer'],
    'period_average_temperature':
    ['Period average temperature', TEMP_CELSIUS, 'mdi:thermometer'],
}

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MONITORED_VARIABLES):
        vol.All(cv.ensure_list, [vol.In(SENSOR_TYPES)]),
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Required(CONF_CONTRACT): cv.string,
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
})

HOST = 'https://www.hydroquebec.com'
HOME_URL = '{}/portail/web/clientele/authentification'.format(HOST)
PROFILE_URL = ('{}/portail/fr/group/clientele/'
               'portrait-de-consommation'.format(HOST))
MONTHLY_MAP = (('period_total_bill', 'montantFacturePeriode'),
               ('period_length', 'nbJourLecturePeriode'),
               ('period_total_days', 'nbJourPrevuPeriode'),
               ('period_mean_daily_bill', 'moyenneDollarsJourPeriode'),
               ('period_mean_daily_consumption', 'moyenneKwhJourPeriode'),
               ('period_total_consumption', 'consoTotalPeriode'),
               ('period_lower_price_consumption', 'consoRegPeriode'),
               ('period_higher_price_consumption', 'consoHautPeriode'))
DAILY_MAP = (('yesterday_total_consumption', 'consoTotalQuot'),
             ('yesterday_lower_price_consumption', 'consoRegQuot'),
             ('yesterday_higher_price_consumption', 'consoHautQuot'))


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the HydroQuebec sensor."""
    # Create a data fetcher to support all of the configured sensors. Then make
    # the first call to init the data.

    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)
    contract = config.get(CONF_CONTRACT)

    try:
        hydroquebec_data = HydroquebecData(username, password, contract)
        _LOGGER.info("Contract list: %s",
                     ", ".join(hydroquebec_data.get_contract_list()))
    except requests.exceptions.HTTPError as error:
        _LOGGER.error("Failt login: %s", error)
        return False

    name = config.get(CONF_NAME)

    sensors = []
    for variable in config[CONF_MONITORED_VARIABLES]:
        sensors.append(HydroQuebecSensor(hydroquebec_data, variable, name))

    add_devices(sensors, True)


class HydroQuebecSensor(Entity):
    """Implementation of a HydroQuebec sensor."""

    def __init__(self, hydroquebec_data, sensor_type, name):
        """Initialize the sensor."""
        self.client_name = name
        self.type = sensor_type
        self.entity_id = "sensor.{}_{}".format(name, sensor_type)
        self._name = SENSOR_TYPES[sensor_type][0]
        self._unit_of_measurement = SENSOR_TYPES[sensor_type][1]
        self._icon = SENSOR_TYPES[sensor_type][2]
        self.hydroquebec_data = hydroquebec_data
        self._state = None

    @property
    def name(self):
        """Return the name of the sensor."""
        return '{} {}'.format(self.client_name, self._name)

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return self._icon

    def update(self):
        """Get the latest data from Hydroquebec and update the state."""
        self.hydroquebec_data.update()
        if self.type in self.hydroquebec_data.data:
            self._state = round(self.hydroquebec_data.data[self.type], 2)


class HydroquebecData(object):
    """Get data from HydroQuebec."""

    def __init__(self, username, password, contract=None):
        """Initialize the data object."""
        from pyhydroquebec import HydroQuebecClient
        self.client = HydroQuebecClient(
            username, password, REQUESTS_TIMEOUT)
        self._contract = contract
        self.data = {}

    def get_contract_list(self):
        """Return the contract list."""
        # Fetch data
        self._fetch_data()
        return self.client.get_contracts()

    def _fetch_data(self):
        """Fetch latest data from HydroQuebec."""
        from pyhydroquebec.client import PyHydroQuebecError
        try:
            self.client.fetch_data()
        except PyHydroQuebecError as exp:
            _LOGGER.error("Error on receive last Hydroquebec data: %s", exp)
            return

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Return the latest collected data from HydroQuebec."""
        self._fetch_data()
        self.data = self.client.get_data(self._contract)[self._contract]
