import os
from typing import List, Optional


def load_keys_from_env(env_var_name: str) -> List[str]:
    """Carrega chaves de uma variável de ambiente, separadas por vírgula."""
    keys_str = os.getenv(env_var_name)
    if not keys_str:
        return []
    return [key.strip() for key in keys_str.split(',') if key.strip()]


class KeyPool:
    """Gerencia um pool de chaves de API com rotação."""

    def __init__(self, keys: List[str]):
        self.keys = keys
        self.current_index = 0

    def get_key(self) -> Optional[str]:
        """Retorna a chave atual."""
        if not self.keys:
            return None
        return self.keys[self.current_index]

    def rotate_key(self) -> Optional[str]:
        """Gira para a próxima chave e a retorna."""
        if not self.keys:
            return None
        self.current_index = (self.current_index + 1) % len(self.keys)
        return self.get_key()