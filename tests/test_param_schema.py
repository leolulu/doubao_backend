import typing
import unittest

if not hasattr(typing, "override"):
    typing.override = lambda func: func

from api.base_api import BaseApi
from api.param_schema import ParamType, ProviderParam


class ConfigurableApi(BaseApi):
    @classmethod
    def get_params(cls) -> list[ProviderParam]:
        return [
            ProviderParam("api_key", ParamType.STRING, required=True),
            ProviderParam("enabled", ParamType.BOOLEAN, required=False, default=True),
            ProviderParam("timeout", ParamType.INTEGER, required=False),
            ProviderParam("temperature", ParamType.FLOAT, required=False),
        ]

    def reason(self, messages: list[dict[str, str]]) -> str:
        return "ok"


class ProviderParamTest(unittest.TestCase):
    def test_parse_value_converts_supported_types(self) -> None:
        self.assertIs(ProviderParam("flag", ParamType.BOOLEAN).parse_value("yes"), True)
        self.assertIs(ProviderParam("flag", ParamType.BOOLEAN).parse_value("false"), False)
        self.assertEqual(ProviderParam("count", ParamType.INTEGER).parse_value("3"), 3)
        self.assertEqual(ProviderParam("ratio", ParamType.FLOAT).parse_value("1.5"), 1.5)
        self.assertEqual(ProviderParam("name", ParamType.STRING).parse_value("model-a"), "model-a")

    def test_validate_rejects_required_empty_and_wrong_types(self) -> None:
        required = ProviderParam("api_key", ParamType.STRING, required=True)
        optional = ProviderParam("note", ParamType.STRING, required=False)
        boolean = ProviderParam("enabled", ParamType.BOOLEAN)
        integer = ProviderParam("timeout", ParamType.INTEGER)
        floating = ProviderParam("temperature", ParamType.FLOAT)

        self.assertFalse(required.validate("")[0])
        self.assertTrue(optional.validate("")[0])
        self.assertFalse(boolean.validate("true")[0])
        self.assertFalse(integer.validate("30")[0])
        self.assertFalse(floating.validate("0.8")[0])
        self.assertTrue(floating.validate(1)[0])

    def test_validate_config_reports_missing_unknown_and_type_errors(self) -> None:
        is_valid, errors = ConfigurableApi.validate_config({
            "enabled": "true",
            "unknown": "value",
        })

        self.assertFalse(is_valid)
        self.assertTrue(any("api_key" in error for error in errors))
        self.assertTrue(any("enabled" in error for error in errors))
        self.assertTrue(any("unknown" in error for error in errors))

    def test_get_param_and_valid_config(self) -> None:
        self.assertEqual(ConfigurableApi.get_param("api_key").name, "api_key")
        self.assertIsNone(ConfigurableApi.get_param("missing"))

        is_valid, errors = ConfigurableApi.validate_config({
            "api_key": "key",
            "enabled": True,
            "timeout": 30,
            "temperature": 0.7,
        })
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
