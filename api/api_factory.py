import configparser
import os
from typing import Any, Dict, Optional, Type

from api.base_api import BaseApi
from api.deepseek import DeepSeek
from api.doubao import Doubao
from api.zhipu import Zhipu


class ApiFactory:
    """API 工厂类，用于管理和创建不同 AI 服务商的客户端实例"""
    
    def __init__(self):
        self._clients: Dict[str, BaseApi] = {}
        self._designated_provider: str = "doubao"
        self._credentials: Dict[str, Any] = {
            "designated_provider": "doubao"
        }
        # 存储服务商类，用于配置生成和校验
        self._provider_classes: Dict[str, Type[BaseApi]] = {}
        self._register_provider_classes()
        self._load_config()
        self._register_designated_provider()
    
    def _register_provider_classes(self):
        """注册可用的服务商类"""
        self._provider_classes["doubao"] = Doubao
        self._provider_classes["zhipu"] = Zhipu
        self._provider_classes["deepseek"] = DeepSeek
    
    def _create_minimal_config(self, credential_file: str):
        """创建最小化配置文件，包含所有可用服务商"""
        # 直接写入文件内容，完全控制输出格式
        lines = []
        
        # 添加系统配置
        lines.append("[designated_provider]")
        lines.append("# 系统配置")
        lines.append("# 指定使用的服务商名称")
        lines.append("PROVIDER = doubao")
        lines.append("")
        
        # 遍历所有注册的服务商类，根据参数定义生成配置
        for provider_name, provider_class in self._provider_classes.items():
            section_name = provider_name.upper()
            lines.append(f"[{section_name}]")
            
            # 获取参数定义
            params = provider_class.get_params()
            
            for param in params:
                # 添加描述注释
                lines.append(f"# {param.description}")
                # 添加配置项
                default_value = "" if param.default is None else str(param.default)
                lines.append(f"{param.to_config_key()} = {default_value}")
            
            lines.append("")
        
        with open(credential_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    
    def _load_config(self):
        """从配置文件加载配置，并进行校验"""
        credential_file = "credentials.config"
        
        if not os.path.exists(credential_file):
            self._create_minimal_config(credential_file)
            raise UserWarning(f"已在当前目录生成 {credential_file} 文件，请填入凭据信息!")
        
        try:
            config = configparser.ConfigParser()
            config.read(credential_file, encoding="utf-8")
            
            # 读取指定的服务商
            if config.has_section("designated_provider"):
                provider = config.get("designated_provider", "PROVIDER", fallback="doubao").strip('"').strip()
                if provider:
                    self._credentials["designated_provider"] = provider
            
            self._designated_provider = self._credentials["designated_provider"]
            
            # 只校验指定的服务商配置
            section_name = self._designated_provider.upper()
            section_lower = self._designated_provider.lower()
            
            if config.has_section(section_name):
                # 查找对应的服务商类
                provider_class = self._provider_classes.get(section_lower)
                if provider_class:
                    # 解析参数 - 读取所有配置项
                    provider_config = {}
                    params = provider_class.get_params()
                    
                    # 读取配置文件中的所有键值对
                    for config_key, raw_value in config.items(section_name):
                        # 跳过注释（以 # 开头的键）
                        if config_key.startswith("#"):
                            continue
                        
                        # 转换为小写参数名
                        param_name = config_key.lower()
                        provider_config[param_name] = raw_value
                    
                    # 解析参数值
                    for param in params:
                        if param.name in provider_config:
                            provider_config[param.name] = param.parse_value(provider_config[param.name])
                        elif param.default is not None:
                            provider_config[param.name] = param.default
                    
                    # 校验配置
                    is_valid, errors = provider_class.validate_config(provider_config)
                    if not is_valid:
                        error_msg = f"服务商 [{section_name}] 配置错误:\n" + "\n".join(f"  - {e}" for e in errors)
                        raise ValueError(error_msg)
                    
                    self._credentials[section_lower] = provider_config
            else:
                raise ValueError(f"配置文件中未找到服务商 [{section_name}] 的配置段")
            
        except ValueError:
            # 重新抛出配置校验错误
            raise
        except Exception as e:
            # 其他错误
            raise ValueError(f"配置文件读取失败: {str(e)}")
    
    def _ensure_provider_config(self, provider_name: str, credential_file: str):
        """确保服务商配置段存在，不存在则创建"""
        # 读取现有文件内容
        if os.path.exists(credential_file):
            with open(credential_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
        
        section_name = provider_name.upper()
        section_exists = any(f"[{section_name}]" in line for line in lines)
        
        if not section_exists:
            # 查找对应的服务商类
            provider_class = self._provider_classes.get(provider_name.lower())
            if provider_class:
                # 添加新段
                lines.append(f"\n[{section_name}]\n")
                
                # 根据参数定义生成配置项
                params = provider_class.get_params()
                for param in params:
                    lines.append(f"# {param.description}\n")
                    default_value = "" if param.default is None else str(param.default)
                    lines.append(f"{param.to_config_key()} = {default_value}\n")
                
                # 写回文件
                with open(credential_file, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                
                raise UserWarning(f"已添加 {provider_name} 配置段到 {credential_file}，请填入凭据信息!")
    
    def _register_designated_provider(self):
        """注册指定的服务商（只注册配置文件中指定的服务商）"""
        provider_mapping = {
            "doubao": Doubao,
            "zhipu": Zhipu,
            "deepseek": DeepSeek
        }
        
        # 只注册指定的服务商
        provider_name = self._designated_provider.lower()
        if provider_name in provider_mapping:
            self._register_provider(provider_name, provider_mapping[provider_name])
    
    def _register_provider(self, name: str, client_class: Type[BaseApi], **kwargs):
        """内部注册方法，自动处理配置和校验"""
        credential_file = "credentials.config"
        
        # 确保配置段存在
        if name.lower() not in self._credentials:
            self._ensure_provider_config(name, credential_file)
            # 重新加载配置
            self._load_config()
        
        # 获取配置
        creds = self._credentials.get(name.lower(), {})
        
        # 合并配置和额外参数
        client_kwargs = creds.copy()
        client_kwargs.update(kwargs)
        
        # 再次校验参数（防止 kwargs 传入无效参数）
        is_valid, errors = client_class.validate_config(client_kwargs)
        if not is_valid:
            error_msg = f"服务商 '{name}' 参数错误:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)
        
        # 创建实例
        client = client_class(**client_kwargs)  # type: ignore
        self._clients[name] = client
    
    def register_provider(self, name: str, client: BaseApi):
        """
        注册新的服务商（直接传入实例）
        
        Args:
            name: 服务商名称
            client: 服务商客户端实例，必须实现 BaseApi 接口
        """
        if not isinstance(client, BaseApi):
            raise TypeError(f"客户端必须实现 BaseApi 接口，当前类型: {type(client)}")
        self._clients[name] = client
    
    def register_provider_class(self, name: str, client_class: Type[BaseApi], **kwargs):
        """
        注册新的服务商（通过类自动创建实例，自动处理凭证）
        
        Args:
            name: 服务商名称
            client_class: 服务商客户端类，必须实现 BaseApi 接口
            **kwargs: 传递给客户端类的额外参数
        """
        self._register_provider(name, client_class, **kwargs)
    
    def get_client(self, provider: Optional[str] = None) -> BaseApi:
        """
        获取指定服务商的客户端实例
        
        Args:
            provider: 服务商名称，如果为 None 则使用指定的服务商
        
        Returns:
            对应的客户端实例
        
        Raises:
            ValueError: 当指定的服务商不存在时抛出
        """
        if provider is None:
            provider = self._designated_provider
        
        # 将 provider 转换为小写以实现大小写不敏感
        provider = provider.lower()
        
        if provider not in self._clients:
            available_providers = ", ".join(self._clients.keys())
            raise ValueError(
                f"未找到服务商 '{provider}'，可用的服务商: {available_providers}"
            )
        
        return self._clients[provider]
    
    def set_designated_provider(self, provider: str):
        """
        设置指定的服务商
        
        Args:
            provider: 服务商名称
        
        Raises:
            ValueError: 当指定的服务商不存在时抛出
        """
        # 将 provider 转换为小写以实现大小写不敏感
        provider = provider.lower()
        
        if provider not in self._clients:
            available_providers = ", ".join(self._clients.keys())
            raise ValueError(
                f"无法设置服务商 '{provider}'，可用的服务商: {available_providers}"
            )
        self._designated_provider = provider
    
    def get_designated_provider(self) -> str:
        """
        获取当前指定的服务商名称
        
        Returns:
            指定的服务商名称
        """
        return self._designated_provider
    
    def list_providers(self) -> list:
        """
        列出所有已注册的服务商
        
        Returns:
            服务商名称列表
        """
        return list(self._clients.keys())
