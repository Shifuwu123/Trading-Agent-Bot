import time
import requests
from typing import Optional
from tradingbot.utils.logger import log

class CLPConverter:
    """
    Utility class for fetching and converting USD to Chilean Pesos (CLP).
    Uses mindicador.cl API with in-memory caching to minimize API requests.
    """
    
    # Class-level variables to share cache across multiple instances
    _cached_rate: Optional[float] = None
    _last_update: float = 0
    
    def __init__(self, cache_hours: float = 4.0, default_rate: float = 950.0):
        """
        :param cache_hours: Time in hours to keep the exchange rate in cache.
        :param default_rate: Fallback rate in case the API is unreachable and no previous rate is cached.
        """
        self.cache_duration = cache_hours * 3600
        self.default_rate = default_rate

    def get_usd_to_clp_rate(self) -> float:
        """
        Fetches the current USD to CLP exchange rate.
        Returns cached rate if available and not expired.
        """
        current_time = time.time()
        
        # Return cached rate if valid
        if self.__class__._cached_rate is not None:
            if (current_time - self.__class__._last_update) < self.cache_duration:
                return self.__class__._cached_rate
                
        try:
            log.debug("Fetching current USD to CLP rate from mindicador.cl API...")
            response = requests.get("https://mindicador.cl/api/dolar", timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if "serie" in data and isinstance(data["serie"], list) and len(data["serie"]) > 0:
                rate = float(data["serie"][0]["valor"])
                self.__class__._cached_rate = rate
                self.__class__._last_update = current_time
                log.info(f"Successfully updated USD to CLP rate: {rate}")
                return rate
            else:
                raise ValueError("API response missing or malformed 'serie' data.")
                
        except requests.RequestException as e:
            log.warning(f"Network error fetching CLP rate: {e}")
        except (ValueError, KeyError, TypeError) as e:
            log.warning(f"Data parsing error for CLP rate response: {e}")
        except Exception as e:
            log.warning(f"Unexpected error fetching CLP rate: {e}")

        # Fallback mechanism if fetch fails
        if self.__class__._cached_rate is not None:
            log.warning(f"Falling back to last known USD to CLP rate: {self.__class__._cached_rate}")
            return self.__class__._cached_rate
        
        log.error(f"No cached rate available. Using default fallback rate: {self.default_rate}")
        return self.default_rate

    def convert_usd_to_clp(self, usd_amount: float) -> float:
        """
        Converts the given USD amount to CLP using the fetched or cached rate.
        """
        rate = self.get_usd_to_clp_rate()
        return float(usd_amount) * rate
