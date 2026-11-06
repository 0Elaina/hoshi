package com.nep.user.constant;

import org.springframework.http.HttpStatus;

import com.nep.common.api.ApiCode;

public final class UserApiCode {
    private UserApiCode() {
    }

    public static final ApiCode USERNAME_TAKEN = new ApiCode(HttpStatus.CONFLICT, "USERNAME_TAKEN", "用户名已被占用");
    public static final ApiCode USER_NOT_FOUND = new ApiCode(HttpStatus.NOT_FOUND, "USER_NOT_FOUND", "用户不存在");
    public static final ApiCode PROTECTED_ADMIN_ACCOUNT = new ApiCode(HttpStatus.FORBIDDEN, "PROTECTED_ADMIN_ACCOUNT",
            "不能通过普通用户维护功能修改管理员");
    public static final ApiCode PASSWORD_NOT_CHANGE = new ApiCode(HttpStatus.BAD_REQUEST, "PASSWORD_NOT_CHANGE",
            "新密码不能与旧密码相同");
}
