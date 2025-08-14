import os
import time
from typing import List, Optional, Dict

from .config import SCHEDULE_CONFIG

def load_keys_from_env(env_var_name: str) -> List[str]:
    """Carrega chaves de uma variável de ambiente, separadas por vírgula."""
    keys_str = os.getenv(env_var_name)
    if not keys_str:
        return []
    return [key.strip() for key in keys_str.split(',') if key.strip()]


class KeyPool:
    """
    Gerencia um pool de chaves de API com rotação e cooldown para falhas.
    """

    def __init__(self, keys: List[str]):
        """
        Inicializa o pool de chaves.

        Args:
            keys: Uma lista de chaves de API.
        """
        # Usamos um dicionário para rastrear o tempo da última falha de cada chave
        self.keys: Dict[str, float] = {key: 0 for key in keys if key}
        self._key_list = list(self.keys.keys())
        self.current_index = 0
        # Define o tempo de cooldown com base na configuração de delay da API
        self.cooldown_seconds = SCHEDULE_CONFIG.get('api_call_delay', 30) * 2

    def get_key(self) -> Optional[str]:
        """
        Retorna uma chave válida que não esteja em cooldown.
        Gira pelas chaves até encontrar uma disponível ou retorna None se todas estiverem em cooldown.
        """
        if not self._key_list:
            return None

        now = time.time()
        initial_index = self.current_index

        for _ in range(len(self._key_list)):
            key = self._key_list[self.current_index]
            last_failure = self.keys.get(key, 0)

            if now - last_failure > self.cooldown_seconds:
                return key

            # Chave em cooldown, passa para a próxima
            self.current_index = (self.current_index + 1) % len(self._key_list)

        return None # Todas as chaves estão em cooldown

    def report_failure(self, key: str):
        """Reporta uma falha para uma chave, colocando-a em cooldown e avançando o ponteiro."""
        if key in self.keys:
            self.keys[key] = time.time()
            self.current_index = (self.current_index + 1) % len(self._key_list)