from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from api.param_schema import ProviderParam


class BaseApi(ABC):
    """API 基类，定义了所有服务商必须实现的接口"""
    
    @classmethod
    def get_params(cls) -> List[ProviderParam]:
        """获取该服务商需要的参数列表
        
        子类应重写此方法来定义自己的参数
        
        Returns:
            参数定义列表
        """
        return []
    
    @classmethod
    def get_param(cls, name: str) -> Optional[ProviderParam]:
        """获取指定参数的定义
        
        Args:
            name: 参数名
        
        Returns:
            参数定义，如果不存在则返回 None
        """
        for param in cls.get_params():
            if param.name == name:
                return param
        return None
    
    @classmethod
    def validate_config(cls, config: Dict[str, Any]) -> tuple[bool, List[str]]:
        """验证配置是否符合参数定义
        
        Args:
            config: 配置字典（键为参数名，值为参数值）
        
        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []
        params = cls.get_params()
        
        # 检查必填参数
        for param in params:
            if param.required and param.name not in config:
                errors.append(f"缺少必填参数: {param.name}")
            elif param.name in config:
                is_valid, error_msg = param.validate(config[param.name])
                if not is_valid:
                    errors.append(error_msg)
        
        # 检查未知参数
        config_keys = set(config.keys())
        param_names = {p.name for p in params}
        unknown_keys = config_keys - param_names
        if unknown_keys:
            errors.append(f"未知参数: {', '.join(unknown_keys)}")
        
        return len(errors) == 0, errors
    
    @abstractmethod
    def reason(self, messages: List[Dict[str, str]]) -> str:
        """推理方法，必须由子类实现"""
        pass
