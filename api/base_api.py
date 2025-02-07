from abc import ABC, abstractmethod
from typing import Dict, List


class BaseApi(ABC):
    @abstractmethod
    def reason(self, messages: List[Dict[str, str]]) -> str:
        pass
