"""Constants for the Elräkning integration."""

DOMAIN = "elrakning"
NORD_POOL_DOMAIN = "nordpool"
ELECTRICITY_PROVIDER_CONFIG_KEY = "electricity_provider"
ELECTRICITY_PROVIDER_CONFIG_DATA_KEY = "electricity_provider_config"
GREENELY_PROVIDER = "greenely"
EON_GRID_PROVIDER = "eon_grid"
EON_GRID_CONFIG_KEY = "eon_grid_config"
GRID_CONFIG_KEY = "grid_config"
EON_GRID_UPDATE_EVENT = "elrakning_eon_grid_update"
SOLAR_WEATHER_UPDATE_EVENT = "elrakning_solar_weather_update"
SUPPORTED_ELECTRICITY_PROVIDERS = {
    GREENELY_PROVIDER: "Greenely",
}
GREENELY_EMAIL = "email"
GREENELY_PASSWORD = "password"
GREENELY_FACILITY_ID = "facility_id"
ELECTRICITY_PROVIDER_UPDATE_EVENT = "elrakning_electricity_provider_update"
INTEGRATION_READY_EVENT = "elrakning_integration_ready"
