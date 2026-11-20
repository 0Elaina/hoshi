from fastapi import Response


def set_cookie(
    response: Response, name: str, value: str, path: str, max_age: int, secure: bool
) -> None:
    """在响应中设置 HttpOnly 且 SameSite=strict 的 Cookie"""
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        path=path,
        httponly=True,
        secure=secure,
        samesite="strict",
    )


def clear_cookie(response: Response, name: str, path: str, secure: bool) -> None:
    """清除响应中指定名称与路径的 Cookie"""
    response.delete_cookie(
        key=name, path=path, httponly=True, secure=secure, samesite="strict"
    )


def clear_cookie_headers(name: str, path: str, secure: bool) -> dict[str, str]:
    """生成用于清除指定 Cookie 的 Set-Cookie 响应头字典"""
    temp_response = Response()
    clear_cookie(temp_response, name=name, path=path, secure=secure)
    return {"Set-Cookie": temp_response.headers["set-cookie"]}
