"""参数定义和校验模块

定义了服务商参数的元数据结构和校验逻辑
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple


class ParamType(Enum):
    """参数类型枚举"""
    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"


@dataclass
class ProviderParam:
    """服务商参数定义
    
    用于定义服务商需要的参数及其约束条件
    """
    name: str  # 参数名（如 "api_key"）
    param_type: ParamType  # 参数类型
    required: bool = True  # 是否必填
    default: Optional[Any] = None  # 默认值
    description: str = ""  # 参数描述
    
    def to_config_key(self) -> str:
        """转换为配置文件中的键名（大写）
        
        Returns:
            配置文件中的键名
        """
        return self.name.upper()
    
    def parse_value(self, value: str) -> Any:
        """解析配置文件中的字符串值
        
        Args:
            value: 配置文件中的字符串值
        
        Returns:
            解析后的值（根据 param_type 转换类型）
        """
        if self.param_type == ParamType.BOOLEAN:
            return value.lower() in ("true", "1", "yes")
        elif self.param_type == ParamType.INTEGER:
            return int(value)
        elif self.param_type == ParamType.FLOAT:
            return float(value)
        else:
            return value
    
    def validate(self, value: Any) -> Tuple[bool, Optional[str]]:
        """验证参数值是否有效
        
        Args:
            value: 要验证的值
        
        Returns:
            (是否有效, 错误信息)
        """
        if value is None or value == "":
            if self.required:
                return False, f"参数 '{self.name}' 是必填项"
            return True, None
        
        # 类型验证
        if self.param_type == ParamType.BOOLEAN:
            if not isinstance(value, bool):
                return False, f"参数 '{self.name}' 必须是布尔值"
        elif self.param_type == ParamType.INTEGER:
            if not isinstance(value, int):
                return False, f"参数 '{self.name}' 必须是整数"
        elif self.param_type == ParamType.FLOAT:
            if not isinstance(value, (int, float)):
                return False, f"参数 '{self.name}' 必须是数字"
        
        return True, None
