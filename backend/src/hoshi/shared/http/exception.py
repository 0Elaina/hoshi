from hoshi.shared.http.api_code import ApiCode


class BusinessException(Exception):
    def __init__(self, api_code: ApiCode, message: str | None = None) -> None:
        self.api_code = api_code
        self.message = api_code.message if message is None else message
        super().__init__(self.message)
