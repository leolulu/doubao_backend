import os
from typing import Dict, List

from volcenginesdkarkruntime import Ark


class Doubao:
    def __init__(self) -> None:
        api_key, access_point = self._get_credentials()
        self.access_point = access_point
        self.client = self.client = Ark(api_key=api_key)

    def _get_credentials(self):
        credential_file = "credentials.config"
        delimiter = " : "
        key_name_api_key = "API KEY"
        key_name_access_point = "ACCESS POINT"

        if not os.path.exists(credential_file):
            with open(credential_file, "w", encoding="utf-8") as f:
                for k in [key_name_api_key, key_name_access_point]:
                    f.write(f'{k}{delimiter}""\n')
            raise UserWarning(f"已在当前目录生成{credential_file}文件，请填入凭据信息!")
        else:
            with open(credential_file, "r", encoding="utf-8") as f:
                return [line.split(delimiter)[-1].strip('"') for line in f.read().strip().split("\n")]

    def reason(self, messages: List[Dict[str, str]]):
        completion = self.client.chat.completions.create(
            model=self.access_point,
            messages=messages,
        )
        response_content = completion.choices[0].message.content
        return response_content
